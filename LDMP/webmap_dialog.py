"""Owner controls for expiring unlisted web maps."""

from qgis.core import QgsApplication, QgsTask
from qgis.PyQt import QtCore, QtWidgets

from . import api
from .constants import TIMEOUT, get_api_url
from .webmap_sharing import ShareClient, ShareError


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
            if self.operation == "refresh":
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

    def finished(self, result):
        self.callback(self.operation, result, self.result, self.error)


class WebmapSharesDialog(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(self.tr("Manage web-map shares"))
        self.resize(760, 420)
        self.api_client = api.APIClient(get_api_url(), TIMEOUT)
        self.task = None
        self.shares = []
        layout = QtWidgets.QVBoxLayout(self)
        warning = QtWidgets.QLabel(
            self.tr(
                "Unlisted links grant access to anyone who has them. Recipients can "
                "forward links or save content. Revocation blocks access immediately; "
                "storage is released after cleanup."
            )
        )
        warning.setWordWrap(True)
        layout.addWidget(warning)
        self.storage = QtWidgets.QLabel()
        self.storage.setWordWrap(True)
        layout.addWidget(self.storage)
        self.table = QtWidgets.QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(
            [
                self.tr("Title"),
                self.tr("Status"),
                self.tr("Expires (UTC)"),
                self.tr("Size"),
            ]
        )
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.itemSelectionChanged.connect(self._selection_changed)
        layout.addWidget(self.table)
        self.details = QtWidgets.QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setMaximumHeight(80)
        layout.addWidget(self.details)
        controls = QtWidgets.QHBoxLayout()
        self.create_button = QtWidgets.QPushButton(self.tr("Share web map"))
        self.add_layers_button = QtWidgets.QPushButton(self.tr("Add layers..."))
        self.refresh_button = QtWidgets.QPushButton(self.tr("Refresh"))
        self.publish_button = QtWidgets.QPushButton(self.tr("Publish"))
        self.rotate_button = QtWidgets.QPushButton(self.tr("Rotate link"))
        self.delete_button = QtWidgets.QPushButton(self.tr("Revoke"))
        self.close_button = QtWidgets.QPushButton(self.tr("Close"))
        for button in (
            self.create_button,
            self.add_layers_button,
            self.refresh_button,
            self.publish_button,
            self.rotate_button,
            self.delete_button,
            self.close_button,
        ):
            controls.addWidget(button)
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
        self.publish_button.setEnabled(ready and not published and self.task is None)
        self.rotate_button.setEnabled(ready and published and self.task is None)
        self.add_layers_button.setEnabled(
            ready
            and published
            and share.get("update_state") in ("idle", "uploading", "failed")
            and self.task is None
        )
        self.delete_button.setEnabled(bool(share) and self.task is None)
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
        CreateWebmapDialog(self, on_published=self._show_link).exec()
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
        CreateWebmapDialog(self, existing_share_id=share["id"]).exec()
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
            selected_id = selected.get("id") if selected else None
            self.shares = shares
            self.table.setRowCount(len(shares))
            for row, share in enumerate(shares):
                values = (
                    share.get("title", ""),
                    share.get("state", ""),
                    share.get("expires_at") or "",
                    str(share.get("quota_reserved_bytes", 0)),
                )
                for column, value in enumerate(values):
                    self.table.setItem(
                        row, column, QtWidgets.QTableWidgetItem(str(value))
                    )
                if share.get("id") == selected_id:
                    self.table.selectRow(row)
            self.storage.setText(
                self.tr(
                    "Storage (bytes): uploaded {uploaded}; reserved {reserved}; "
                    "pending cleanup {pending}; available {available}; quota {quota}."
                ).format(
                    uploaded=usage["uploaded_bytes"],
                    reserved=usage["reserved_bytes"],
                    pending=usage["cleanup_pending_bytes"],
                    available=usage["available_bytes"],
                    quota=usage["quota_limit_bytes"],
                )
            )
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

    def _publish(self):
        answer = QtWidgets.QMessageBox.question(
            self,
            self.tr("Publish web map"),
            self.tr(
                "Anyone with the unlisted link can access, forward or save this map. "
                "Do you have the rights to share all included content and have you "
                "checked it for sensitive information and locations?"
            ),
        )
        if answer == QtWidgets.QMessageBox.Yes:
            self._start("publish")

    def _rotate(self):
        answer = QtWidgets.QMessageBox.question(
            self,
            self.tr("Rotate link"),
            self.tr(
                "The previous link and all open viewer sessions will stop working."
            ),
        )
        if answer == QtWidgets.QMessageBox.Yes:
            self._start("rotate")

    def _revoke(self):
        answer = QtWidgets.QMessageBox.question(
            self,
            self.tr("Revoke share"),
            self.tr(
                "Revoke this link immediately and schedule its storage for deletion?"
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


def show_link(parent, result):
    dialog = QtWidgets.QDialog(parent)
    dialog.setWindowTitle(dialog.tr("Unlisted web-map link"))
    layout = QtWidgets.QVBoxLayout(dialog)
    label = QtWidgets.QLabel(
        dialog.tr(
            "Copy this link now. It cannot be retrieved again; anyone with it "
            "can access and redistribute the map until it expires or is revoked."
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
    copy = QtWidgets.QPushButton(dialog.tr("Copy link"))
    copy.clicked.connect(
        lambda: QtWidgets.QApplication.clipboard().setText(link.text())
    )
    layout.addWidget(copy)
    dialog.exec()
    link.clear()
