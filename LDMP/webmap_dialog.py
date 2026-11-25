"""Owner controls for expiring unlisted web maps."""

from qgis.core import QgsApplication, QgsTask
from qgis.PyQt import QtCore, QtGui, QtWidgets

from . import api
from .constants import TIMEOUT, get_api_url
from .utils import FileUtils
from .webmap_sharing import ShareClient, ShareError


def confirm_public_sharing(parent, layer_names, map_title=None):
    """Ask for explicit consent immediately before content is made public."""
    box = QtWidgets.QMessageBox(parent)
    box.setIcon(QtWidgets.QMessageBox.Warning)
    box.setWindowTitle(box.tr("Share publicly?"))
    box.setText(
        box.tr("Add these layers to “{title}”?").format(title=map_title)
        if map_title
        else box.tr("Create a public web map with these layers?")
    )
    box.setInformativeText(
        box.tr(
            "The link is unlisted: it is not published or searchable, but anyone "
            "who has it can view the map, forward the link and save its content "
            "until it expires. Tiles may be cached publicly for up to four days. "
            "Revocation requests cache removal, which takes time to propagate.\n\n"
            "Only continue if you have the right to share these layers publicly "
            "and they contain no sensitive information."
        )
    )
    box.setDetailedText("\n".join(layer_names))
    share = box.addButton(box.tr("Share publicly"), QtWidgets.QMessageBox.AcceptRole)
    box.addButton(QtWidgets.QMessageBox.Cancel)
    box.setDefaultButton(QtWidgets.QMessageBox.Cancel)
    box.exec()
    return box.clickedButton() is share


def format_bytes(size):
    size = float(size or 0)
    for unit in ("bytes", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "bytes" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


def share_status(share):
    if share.get("state") == "ready" and share.get("ready_at"):
        if share.get("update_state") == "validating":
            return QtCore.QCoreApplication.translate("webmap", "Published (updating)")
        if share.get("update_state") == "failed":
            return QtCore.QCoreApplication.translate(
                "webmap", "Published (update failed)"
            )
        return QtCore.QCoreApplication.translate("webmap", "Published")
    return {
        "draft": QtCore.QCoreApplication.translate("webmap", "Draft"),
        "uploading": QtCore.QCoreApplication.translate("webmap", "Uploading"),
        "validating": QtCore.QCoreApplication.translate("webmap", "Validating"),
        "ready": QtCore.QCoreApplication.translate("webmap", "Ready to publish"),
        "failed": QtCore.QCoreApplication.translate("webmap", "Failed"),
    }.get(share.get("state"), str(share.get("state", "")))


def can_add_layers(share):
    return (
        share.get("state") == "ready"
        and bool(share.get("ready_at"))
        and share.get("update_state") in ("idle", "uploading", "failed")
    )


class _OwnerTask(QgsTask):
    def __init__(self, base_url, token, operation, share_id, callback):
        super().__init__("Trends.Earth web-map sharing")
        self.base_url = base_url
        self.token = token
        self.operation = operation
        self.share_id = share_id
        self.callback = callback
        self.result = None
        self.error = None

    def run(self):
        client = None
        try:
            client = ShareClient(self.base_url, self.token, timeout=TIMEOUT)
            if self.operation == "list":
                self.result = client.list()
                if not isinstance(self.result, list) or not all(
                    isinstance(share, dict) for share in self.result
                ):
                    raise ShareError(
                        "Invalid response from the web-map sharing service"
                    )
            elif self.operation == "refresh":
                self.result = (client.list(), client.storage())
                shares, usage = self.result
                if (
                    not isinstance(shares, list)
                    or not all(isinstance(share, dict) for share in shares)
                    or not isinstance(usage, dict)
                    or not {
                        "uploaded_bytes",
                        "reserved_bytes",
                        "cleanup_pending_bytes",
                        "available_bytes",
                        "quota_limit_bytes",
                    }
                    <= usage.keys()
                ):
                    raise ShareError(
                        "Invalid response from the web-map sharing service"
                    )
                for share in shares:
                    share["link"] = self._link(client, share)
            else:
                self.result = getattr(client, self.operation)(self.share_id)
                if not isinstance(self.result, dict):
                    raise ShareError(
                        "Invalid response from the web-map sharing service"
                    )
                if self.operation in ("publish", "rotate") and (
                    not isinstance(self.result.get("link"), str)
                    or not isinstance(self.result.get("share"), dict)
                    or not self.result["share"].get("expires_at")
                ):
                    raise ShareError(
                        "Invalid response from the web-map sharing service"
                    )
            return True
        except ShareError as exc:
            self.error = str(exc)
            return False
        except (KeyError, TypeError, ValueError):
            self.error = "Invalid response from the web-map sharing service"
            return False
        finally:
            self.token = None
            if client:
                client.close()

    @staticmethod
    def _link(client, share):
        if share.get("state") != "ready" or not share.get("ready_at"):
            return None
        try:
            result = client.link(share["id"])
        except ShareError as exc:
            # Links minted before the API stored them must be rotated once.
            if exc.status_code == 409:
                return None
            raise
        link = result.get("link") if isinstance(result, dict) else None
        if not isinstance(link, str) or not link.startswith("https://"):
            raise ShareError("Invalid response from the web-map sharing service")
        return link

    def finished(self, result):
        self.callback(self.operation, result, self.result, self.error)


class WebmapSharesDialog(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(self.tr("Shared web maps"))
        self.resize(760, 440)
        self.api_client = api.APIClient(get_api_url(), TIMEOUT)
        self.task = None
        self.shares = []
        self._select_id = None
        layout = QtWidgets.QVBoxLayout(self)
        warning = QtWidgets.QLabel(
            self.tr(
                "Unlisted links work for anyone who has them. Cached tiles can "
                "remain available while revocation propagates."
            )
        )
        warning.setWordWrap(True)
        layout.addWidget(warning)
        header = QtWidgets.QHBoxLayout()
        self.storage = QtWidgets.QLabel()
        self.storage.setWordWrap(True)
        header.addWidget(self.storage, 1)
        self.refresh_button = QtWidgets.QToolButton()
        self.refresh_button.setIcon(FileUtils.get_icon("mActionRefresh.svg"))
        self.refresh_button.setToolTip(self.tr("Refresh"))
        header.addWidget(self.refresh_button)
        layout.addLayout(header)
        self.table = QtWidgets.QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            [
                self.tr("Title"),
                self.tr("Status"),
                self.tr("Expires (UTC)"),
                self.tr("Size"),
                self.tr("Link"),
            ]
        )
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.itemSelectionChanged.connect(self._selection_changed)
        self.table.itemDoubleClicked.connect(lambda _item: self._open_link())
        layout.addWidget(self.table)
        link_row = QtWidgets.QHBoxLayout()
        link_row.addWidget(QtWidgets.QLabel(self.tr("Link:")))
        self.link = QtWidgets.QLineEdit()
        self.link.setReadOnly(True)
        link_row.addWidget(self.link)
        self.copy_link_button = QtWidgets.QPushButton(self.tr("Copy link"))
        self.open_link_button = QtWidgets.QPushButton(self.tr("Open in browser"))
        link_row.addWidget(self.copy_link_button)
        link_row.addWidget(self.open_link_button)
        layout.addLayout(link_row)
        self.copy_link_button.clicked.connect(self._copy_link)
        self.open_link_button.clicked.connect(self._open_link)
        self.details = QtWidgets.QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setMaximumHeight(80)
        layout.addWidget(self.details)
        controls = QtWidgets.QHBoxLayout()
        self.create_button = QtWidgets.QPushButton(self.tr("New web map..."))
        self.create_button.setDefault(True)
        self.add_layers_button = QtWidgets.QPushButton(self.tr("Add layers..."))
        self.publish_button = QtWidgets.QPushButton(self.tr("Publish"))
        self.rotate_button = QtWidgets.QPushButton(self.tr("New link"))
        self.rotate_button.setToolTip(
            self.tr("Replace the link; the current link stops working")
        )
        self.delete_button = QtWidgets.QPushButton(self.tr("Revoke"))
        self.close_button = QtWidgets.QPushButton(self.tr("Close"))
        for button in (
            self.create_button,
            self.add_layers_button,
            self.publish_button,
            self.rotate_button,
            self.delete_button,
        ):
            controls.addWidget(button)
        controls.addStretch()
        controls.addWidget(self.close_button)
        layout.addLayout(controls)
        self.create_button.clicked.connect(self._create)
        self.add_layers_button.clicked.connect(self._add_layers)
        self.refresh_button.clicked.connect(self.refresh)
        self.publish_button.clicked.connect(self._publish)
        self.rotate_button.clicked.connect(self._rotate)
        self.delete_button.clicked.connect(self._revoke)
        self.close_button.clicked.connect(self.close)
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(5000)
        self.timer.timeout.connect(self._poll)
        self.timer.start()
        self._selection_changed()
        QtCore.QTimer.singleShot(0, self.refresh)

    def _selected(self):
        row = self.table.currentRow()
        return self.shares[row] if 0 <= row < len(self.shares) else None

    def _selection_changed(self):
        share = self._selected()
        ready = bool(share and share.get("state") == "ready")
        published = bool(share and share.get("ready_at"))
        self.publish_button.setVisible(ready and not published)
        self.publish_button.setEnabled(ready and not published and self.task is None)
        self.rotate_button.setEnabled(ready and published and self.task is None)
        self.add_layers_button.setEnabled(
            bool(share) and can_add_layers(share) and self.task is None
        )
        self.delete_button.setEnabled(bool(share) and self.task is None)
        link = share.get("link") if share else None
        self.link.setText(link or "")
        if share and ready and published and not link:
            self.link.setPlaceholderText(
                self.tr(
                    "This link was created before links were stored; choose New link."
                )
            )
        else:
            self.link.setPlaceholderText(
                self.tr("Select a published map to view its link.")
            )
        self.copy_link_button.setEnabled(bool(link))
        self.open_link_button.setEnabled(bool(link))
        errors = share.get("validation_errors", []) if share else []
        self.details.setPlainText(
            "\n".join(str(error.get("error", "")) for error in errors)
        )

    def _start(self, operation):
        if self.task is not None:
            return
        share = self._selected()
        if operation != "refresh" and not share:
            return
        base_url = get_api_url()
        self.api_client.url = base_url
        token = self.api_client.login()
        if not token:
            QtWidgets.QMessageBox.warning(
                self, self.tr("Web-map sharing"), self.tr("Authentication is required.")
            )
            return
        self.task = _OwnerTask(
            base_url,
            token,
            operation,
            share["id"] if share else None,
            self._finished,
        )
        self.create_button.setEnabled(False)
        self.add_layers_button.setEnabled(False)
        self.refresh_button.setEnabled(False)
        self._selection_changed()
        QgsApplication.taskManager().addTask(self.task)

    def refresh(self):
        self._start("refresh")

    def _create(self):
        from .webmap_create_dialog import CreateWebmapDialog

        self.timer.stop()
        self.create_button.setEnabled(False)
        dialog = CreateWebmapDialog(self, on_published=self._show_link)
        dialog.exec()
        self._select_id = dialog.share_id
        self.create_button.setEnabled(True)
        self.add_layers_button.setEnabled(True)
        self.refresh()

    def _add_layers(self):
        share = self._selected()
        if not share or share.get("state") != "ready" or not share.get("ready_at"):
            return
        from .webmap_create_dialog import CreateWebmapDialog

        self.timer.stop()
        self.add_layers_button.setEnabled(False)
        CreateWebmapDialog(
            self, existing_share_id=share["id"], shares=self.shares
        ).exec()
        self.add_layers_button.setEnabled(True)
        self.refresh()

    def _poll(self):
        if self.task is None and any(
            item.get("state") == "validating"
            or item.get("update_state") == "validating"
            for item in self.shares
        ):
            self.refresh()

    def _finished(self, operation, succeeded, result, error):
        self.task = None
        self.create_button.setEnabled(True)
        self.add_layers_button.setEnabled(True)
        self.refresh_button.setEnabled(True)
        if not succeeded:
            self.timer.stop()
            QtWidgets.QMessageBox.warning(self, self.tr("Web-map sharing"), error)
            self._selection_changed()
            return
        if operation == "refresh":
            self.timer.start()
            shares, usage = result
            selected = self._selected()
            selected_id = self._select_id or (selected.get("id") if selected else None)
            self._select_id = None
            self.shares = shares
            self.table.setRowCount(len(shares))
            for row, share in enumerate(shares):
                values = (
                    share.get("title", ""),
                    share_status(share),
                    share.get("expires_at") or "",
                    format_bytes(share.get("quota_reserved_bytes", 0)),
                    share.get("link") or "",
                )
                for column, value in enumerate(values):
                    self.table.setItem(
                        row, column, QtWidgets.QTableWidgetItem(str(value))
                    )
                if share.get("id") == selected_id:
                    self.table.selectRow(row)
            if self.table.currentRow() < 0 and shares:
                self.table.selectRow(0)
            self.table.resizeColumnsToContents()
            storage = self.tr("Storage: {used} of {quota} used").format(
                used=format_bytes(usage["reserved_bytes"]),
                quota=format_bytes(usage["quota_limit_bytes"]),
            )
            if usage["cleanup_pending_bytes"]:
                storage += self.tr(" ({pending} awaiting cleanup)").format(
                    pending=format_bytes(usage["cleanup_pending_bytes"])
                )
            self.storage.setText(storage)
            self._selection_changed()
        elif operation in ("publish", "rotate"):
            self._show_link(result)
            self.refresh()
        else:
            if not result.get("cleanup_scheduled", True):
                QtWidgets.QMessageBox.warning(
                    self,
                    self.tr("Web-map sharing"),
                    self.tr("Revoked. Cleanup will be retried by the server."),
                )
            self.refresh()

    def _show_link(self, result):
        show_link(self, result)

    def _copy_link(self):
        if self.link.text():
            QtWidgets.QApplication.clipboard().setText(self.link.text())

    def _open_link(self):
        if self.link.text().startswith("https://"):
            QtGui.QDesktopServices.openUrl(QtCore.QUrl(self.link.text()))

    def _publish(self):
        share = self._selected()
        if share and confirm_public_sharing(
            self, [layer.get("name", "") for layer in share.get("layers", [])]
        ):
            self._start("publish")

    def _rotate(self):
        answer = QtWidgets.QMessageBox.question(
            self,
            self.tr("Create a new link"),
            self.tr(
                "The current link and open viewer sessions will be invalidated. "
                "Cached tiles may remain available until CDN removal completes. "
                "Create a new link?"
            ),
        )
        if answer == QtWidgets.QMessageBox.Yes:
            self._start("rotate")

    def _revoke(self):
        answer = QtWidgets.QMessageBox.question(
            self,
            self.tr("Revoke share"),
            self.tr(
                "Revoke this link and schedule its storage for deletion? "
                "Cached tiles may remain available until CDN removal completes."
            ),
        )
        if answer == QtWidgets.QMessageBox.Yes:
            self._start("revoke")

    def closeEvent(self, event):
        if self.task is not None:
            event.ignore()
            return
        super().closeEvent(event)

    def reject(self):
        if self.task is None:
            super().reject()


def show_link(parent, result, message=None):
    dialog = QtWidgets.QDialog(parent)
    dialog.setWindowTitle(dialog.tr("Web-map link"))
    layout = QtWidgets.QVBoxLayout(dialog)
    label = QtWidgets.QLabel(
        message
        or dialog.tr(
            "Your map is ready. Anyone with this link can view it until it expires, "
            "forward the link or save its content. Revocation takes time to propagate. "
            "You can find the link again under Shared web maps."
        )
    )
    label.setWordWrap(True)
    layout.addWidget(label)
    layout.addWidget(
        QtWidgets.QLabel(
            dialog.tr("Expires (UTC): {expiry}").format(
                expiry=result["share"]["expires_at"]
            )
        )
    )
    link = QtWidgets.QLineEdit(result["link"])
    link.setReadOnly(True)
    layout.addWidget(link)
    buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Close)
    copy = buttons.addButton(
        dialog.tr("Copy link"), QtWidgets.QDialogButtonBox.ActionRole
    )
    browse = buttons.addButton(
        dialog.tr("Open in browser"), QtWidgets.QDialogButtonBox.ActionRole
    )
    copy.clicked.connect(
        lambda: QtWidgets.QApplication.clipboard().setText(link.text())
    )
    browse.clicked.connect(
        lambda: QtGui.QDesktopServices.openUrl(QtCore.QUrl(link.text()))
    )
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    copy.setDefault(True)
    dialog.exec()
    link.clear()
