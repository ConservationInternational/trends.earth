"""Owner controls for expiring unlisted web maps."""

from qgis.core import QgsApplication, QgsTask
from qgis.PyQt import QtCore, QtGui, QtWidgets

from . import api
from .constants import TIMEOUT, get_api_url
from .utils import FileUtils
from .webmap_mask import MaskSelector
from .webmap_sharing import ShareClient, ShareError


def commit_layer_name_edit(view):
    """Commit an active inline title editor before reading the model."""
    editor = view.findChild(QtWidgets.QLineEdit)
    if editor is not None and editor.isVisible():
        view.itemDelegate().commitData.emit(editor)


def confirm_public_sharing(parent, layer_names, map_title=None):
    """Ask for explicit consent immediately before content is made public."""
    box = QtWidgets.QMessageBox(parent)
    box.setIcon(QtWidgets.QMessageBox.Warning)
    box.setWindowTitle(box.tr("Share publicly?"))
    box.setText(
        box.tr("Add these layers to “{title}”?").format(title=map_title)
        if map_title
        else box.tr("Create a public web map with these layers?")
        if layer_names
        else box.tr("Create a public web map?")
    )
    box.setInformativeText(
        box.tr(
            "The link is unlisted: it is not published or searchable, but anyone "
            "who has it can view the map, forward the link and save its content "
            "until it expires. \n\n"
            "Only continue if you have the right to share these layers publicly "
            "and they contain no sensitive information."
        )
        if layer_names
        else box.tr(
            "The link is unlisted: it is not published or searchable, but anyone "
            "who has it can view the map, including any layers you add later, "
            "forward the link and save its content until it expires."
        )
    )
    if layer_names:
        box.setDetailedText("\n".join(layer_names))
    share = box.addButton(
        box.tr("Share publicly"), QtWidgets.QMessageBox.ButtonRole.AcceptRole
    )
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
    def __init__(
        self,
        base_url,
        token,
        operation,
        share_id,
        callback,
        mask=None,
        mask_version=None,
        layer_ids=None,
        layers=None,
    ):
        super().__init__("Trends.Earth web-map sharing")
        self.base_url = base_url
        self.token = token
        self.operation = operation
        self.share_id = share_id
        self.callback = callback
        self.mask = mask
        self.mask_version = mask_version
        self.layer_ids = layer_ids
        self.layers = layers
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
            elif self.operation == "update_mask":
                self.result = client.update_mask(
                    self.share_id, self.mask, self.mask_version
                )
                if (
                    not isinstance(self.result, dict)
                    or self.result.get("mask_version") != self.mask_version + 1
                    or self.result.get("has_mask") is not (self.mask is not None)
                ):
                    raise ShareError(
                        "Invalid response from the web-map sharing service"
                    )
            elif self.operation == "remove_layers":
                self.result = client.remove_layers(self.share_id, self.layer_ids)
                if (
                    not isinstance(self.result, dict)
                    or not isinstance(self.result.get("share"), dict)
                    or type(self.result.get("cleanup_scheduled")) is not bool
                ):
                    raise ShareError(
                        "Invalid response from the web-map sharing service"
                    )
            elif self.operation == "reorder_layers":
                self.result = client.reorder_layers(self.share_id, self.layer_ids)
                if not isinstance(self.result, dict) or not isinstance(
                    self.result.get("layers"), list
                ):
                    raise ShareError(
                        "Invalid response from the web-map sharing service"
                    )
            elif self.operation == "edit_layers":
                self.result = client.edit_layers(self.share_id, self.layers)
                if not isinstance(self.result, dict) or not isinstance(
                    self.result.get("layers"), list
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
                "Unlisted links work for anyone who has them."
            )
        )
        warning.setWordWrap(True)
        layout.addWidget(warning)
        header = QtWidgets.QHBoxLayout()
        self.storage = QtWidgets.QLabel()
        self.storage.setWordWrap(True)
        header.addWidget(self.storage, 1)
        self.usage = None
        self.quota_button = QtWidgets.QPushButton(self.tr("Quota..."))
        self.quota_button.setToolTip(self.tr("View your remaining sharing quota"))
        self.quota_button.setEnabled(False)
        header.addWidget(self.quota_button)
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
        self.publish_button = QtWidgets.QPushButton(self.tr("Publish"))
        self.edit_layers_button = QtWidgets.QPushButton(self.tr("Remove layers..."))
        self.order_layers_button = QtWidgets.QPushButton(self.tr("Edit map layers..."))
        self.mask_button = QtWidgets.QPushButton(self.tr("Change mask..."))
        self.rotate_button = QtWidgets.QPushButton(self.tr("New link"))
        self.rotate_button.setToolTip(
            self.tr("Replace the link; the current link stops working")
        )
        self.delete_button = QtWidgets.QPushButton(self.tr("Revoke"))
        self.close_button = QtWidgets.QPushButton(self.tr("Close"))
        for button in (
            self.create_button,
            self.edit_layers_button,
            self.order_layers_button,
            self.mask_button,
            self.publish_button,
            self.rotate_button,
            self.delete_button,
        ):
            controls.addWidget(button)
        controls.addStretch()
        controls.addWidget(self.close_button)
        layout.addLayout(controls)
        self.create_button.clicked.connect(self._create)
        self.refresh_button.clicked.connect(self.refresh)
        self.publish_button.clicked.connect(self._publish)
        self.edit_layers_button.clicked.connect(self._edit_layers)
        self.order_layers_button.clicked.connect(self._order_layers)
        self.quota_button.clicked.connect(self._show_quota)
        self.mask_button.clicked.connect(self._change_mask)
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
        editable = bool(
            ready
            and published
            and share.get("update_state") == "idle"
            and self.task is None
        )
        published_layers = (
            [layer for layer in share.get("layers", []) if layer.get("published")]
            if share
            else []
        )
        self.edit_layers_button.setEnabled(editable and bool(published_layers))
        self.order_layers_button.setEnabled(editable and bool(published_layers))
        self.mask_button.setEnabled(
            ready
            and published
            and self.task is None
            and isinstance(share.get("mask_version"), int)
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

    def _start(
        self, operation, mask=None, mask_version=None, layer_ids=None, layers=None
    ):
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
            mask=mask,
            mask_version=mask_version,
            layer_ids=layer_ids,
            layers=layers,
        )
        self.create_button.setEnabled(False)
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
            self.usage = usage
            self.quota_button.setEnabled(True)
            storage = self.tr(
                "Storage: {used} of {quota} used, {free} remaining"
            ).format(
                used=format_bytes(usage["reserved_bytes"]),
                quota=format_bytes(usage["quota_limit_bytes"]),
                free=format_bytes(usage["available_bytes"]),
            )
            if usage["cleanup_pending_bytes"]:
                storage += self.tr(" ({pending} awaiting cleanup)").format(
                    pending=format_bytes(usage["cleanup_pending_bytes"])
                )
            maps = self._active_maps(usage)
            if maps:
                storage += "; " + maps
            self.storage.setText(storage)
            self._selection_changed()
        elif operation in ("publish", "rotate"):
            self._show_link(result)
            self.refresh()
        elif operation in ("reorder_layers", "edit_layers"):
            self.refresh()
        elif operation == "remove_layers":
            if not result["cleanup_scheduled"]:
                QtWidgets.QMessageBox.warning(
                    self,
                    self.tr("Web-map sharing"),
                    self.tr(
                        "Layers were removed, but cleanup could not be scheduled. "
                        "The server will retry it automatically."
                    ),
                )
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

    def _edit_layers(self):
        share = self._selected()
        if not share or not self.edit_layers_button.isEnabled():
            return
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle(self.tr("Edit shared map layers"))
        layout = QtWidgets.QVBoxLayout(dialog)
        hint = QtWidgets.QLabel(
            self.tr("Select the layers to remove from this shared map.")
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layers = QtWidgets.QListWidget()
        for layer in share.get("layers", []):
            if layer.get("published"):
                item = QtWidgets.QListWidgetItem(layer["name"], layers)
                item.setData(QtCore.Qt.UserRole, layer["id"])
                item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
                item.setCheckState(QtCore.Qt.Unchecked)
        layout.addWidget(layers)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Cancel)
        remove = buttons.addButton(
            self.tr("Remove selected"),
            QtWidgets.QDialogButtonBox.ButtonRole.AcceptRole,
        )
        remove.setEnabled(False)
        layers.itemChanged.connect(
            lambda _item: remove.setEnabled(
                any(
                    layers.item(index).checkState() == QtCore.Qt.Checked
                    for index in range(layers.count())
                )
            )
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if not dialog.exec():
            return
        layer_ids = [
            layers.item(index).data(QtCore.Qt.UserRole)
            for index in range(layers.count())
            if layers.item(index).checkState() == QtCore.Qt.Checked
        ]
        if not layer_ids:
            return
        answer = QtWidgets.QMessageBox.question(
            self,
            self.tr("Remove shared layers"),
            self.tr(
                "Remove the selected layers for everyone with this link? "
                "The uploaded snapshots will be deleted."
            ),
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No,
        )
        if answer == QtWidgets.QMessageBox.Yes:
            self._start("remove_layers", layer_ids=layer_ids)

    def _active_maps(self, usage):
        count, limit = usage.get("active_share_count"), usage.get("active_share_limit")
        # Older API versions do not report the active-map limit.
        if not isinstance(count, int) or not isinstance(limit, int):
            return ""
        return self.tr("Maps: {count} of {limit} active").format(
            count=count, limit=limit
        )

    def _show_quota(self):
        usage = self.usage
        if not usage:
            return
        lines = [
            self.tr("Storage used: {used} of {quota}").format(
                used=format_bytes(usage["reserved_bytes"]),
                quota=format_bytes(usage["quota_limit_bytes"]),
            ),
            self.tr("Storage remaining: {free}").format(
                free=format_bytes(usage["available_bytes"])
            ),
            self.tr("Awaiting cleanup: {pending}").format(
                pending=format_bytes(usage["cleanup_pending_bytes"])
            ),
        ]
        count, limit = usage.get("active_share_count"), usage.get("active_share_limit")
        if isinstance(count, int) and isinstance(limit, int):
            lines.append(
                self.tr("Active maps: {count} of {limit} ({free} remaining)").format(
                    count=count, limit=limit, free=max(0, limit - count)
                )
            )
        max_layers = usage.get("max_layers_per_share")
        max_bytes = usage.get("max_share_bytes")
        if isinstance(max_layers, int) and isinstance(max_bytes, int):
            lines.append(
                self.tr("Each map: up to {layers} layers and {size}").format(
                    layers=max_layers, size=format_bytes(max_bytes)
                )
            )
        lines.append("")
        lines.append(
            self.tr(
                "Storage used by revoked or expired maps is released after "
                "cleanup. Removing layers or revoking maps frees quota."
            )
        )
        QtWidgets.QMessageBox.information(
            self, self.tr("Web-map sharing quota"), "\n".join(lines)
        )

    def _order_layers(self):
        share = self._selected()
        if not share or not self.order_layers_button.isEnabled():
            return
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle(self.tr("Edit map layers"))
        layout = QtWidgets.QVBoxLayout(dialog)
        hint = QtWidgets.QLabel(
            self.tr(
                "Double-click a layer title or use Rename to edit it. Drag layers or "
                "use the buttons to change their order. The first layer is drawn "
                "on top in the web map."
            )
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)
        row = QtWidgets.QHBoxLayout()
        layers = QtWidgets.QListWidget()
        layers.setDragDropMode(QtWidgets.QAbstractItemView.DragDropMode.InternalMove)
        layers.setDefaultDropAction(QtCore.Qt.DropAction.MoveAction)
        layers.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.DoubleClicked)
        original = []
        for layer in share.get("layers", []):
            if layer.get("published"):
                item = QtWidgets.QListWidgetItem(layer["name"], layers)
                item.setData(QtCore.Qt.ItemDataRole.UserRole, layer["id"])
                item.setFlags(item.flags() | QtCore.Qt.ItemFlag.ItemIsEditable)
                original.append({"id": layer["id"], "name": layer["name"]})
        row.addWidget(layers)
        moves = QtWidgets.QVBoxLayout()
        up = QtWidgets.QPushButton(self.tr("Move up"))
        down = QtWidgets.QPushButton(self.tr("Move down"))
        rename = QtWidgets.QPushButton(self.tr("Rename"))
        moves.addWidget(rename)
        moves.addWidget(up)
        moves.addWidget(down)
        moves.addStretch()
        row.addLayout(moves)
        layout.addLayout(row)
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        save = buttons.addButton(
            self.tr("Save changes"), QtWidgets.QDialogButtonBox.ButtonRole.AcceptRole
        )

        def layer_edits():
            return [
                {
                    "id": layers.item(index).data(QtCore.Qt.ItemDataRole.UserRole),
                    "name": layers.item(index).text().strip(),
                }
                for index in range(layers.count())
            ]

        def update():
            current = layers.currentRow()
            up.setEnabled(current > 0)
            down.setEnabled(0 <= current < layers.count() - 1)
            rename.setEnabled(current >= 0)
            save.setEnabled(layer_edits() != original)

        def move(offset):
            current = layers.currentRow()
            target = current + offset
            if current < 0 or not 0 <= target < layers.count():
                return
            layers.insertItem(target, layers.takeItem(current))
            layers.setCurrentRow(target)
            update()

        up.clicked.connect(lambda: move(-1))
        down.clicked.connect(lambda: move(1))
        def edit_selected():
            if layers.currentItem() is not None:
                save.setEnabled(True)
                layers.editItem(layers.currentItem())

        rename.clicked.connect(edit_selected)
        layers.itemDoubleClicked.connect(lambda _item: save.setEnabled(True))
        layers.currentRowChanged.connect(lambda _row: update())
        layers.itemChanged.connect(lambda _item: update())
        for signal in ("rowsMoved", "rowsInserted", "rowsRemoved"):
            getattr(layers.model(), signal).connect(lambda *_args: update())

        def accept():
            commit_layer_name_edit(layers)
            names = [layer["name"] for layer in layer_edits()]
            if any(not name or len(name) > 120 for name in names) or len(
                {name.casefold() for name in names}
            ) != len(names):
                QtWidgets.QMessageBox.warning(
                    dialog,
                    self.tr("Edit map layers"),
                    self.tr("Each layer needs a unique name of up to 120 characters."),
                )
                return
            dialog.accept()

        buttons.accepted.connect(accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        update()
        if dialog.exec() and layer_edits() != original:
            self._start("edit_layers", layers=layer_edits())

    def _change_mask(self):
        share = self._selected()
        if not share or not isinstance(share.get("mask_version"), int):
            return
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle(self.tr("Change display mask"))
        layout = QtWidgets.QVBoxLayout(dialog)
        selector = MaskSelector(dialog)
        selector.setChecked(bool(share.get("has_mask")))
        layout.addWidget(selector)
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Save | QtWidgets.QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if not dialog.exec():
            return
        try:
            mask = selector.geometry()
        except ShareError as exc:
            QtWidgets.QMessageBox.warning(self, self.tr("Web-map sharing"), str(exc))
            return
        answer = QtWidgets.QMessageBox.question(
            self,
            self.tr("Update display mask"),
            self.tr("Update the mask for everyone with this map link?"),
        )
        if answer == QtWidgets.QMessageBox.Yes:
            self._start("update_mask", mask, share["mask_version"])

    def _rotate(self):
        answer = QtWidgets.QMessageBox.question(
            self,
            self.tr("Create a new link"),
            self.tr(
                "The current link and open viewer sessions will be invalidated. "
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
                "Revoke this link and schedule its storage for deletion?"
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
        dialog.tr("Copy link"), QtWidgets.QDialogButtonBox.ButtonRole.ActionRole
    )
    browse = buttons.addButton(
        dialog.tr("Open in browser"), QtWidgets.QDialogButtonBox.ButtonRole.ActionRole
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
