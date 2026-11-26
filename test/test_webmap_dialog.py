"""Tests for owner share controls."""

import unittest
from unittest.mock import Mock, patch

from qgis.core import QgsApplication
from qgis.PyQt import QtCore, QtGui, QtWidgets

from LDMP.webmap_dialog import (
    WebmapSharesDialog,
    _OwnerTask,
    confirm_public_sharing,
    show_link,
)
from LDMP.webmap_sharing import ShareError


class TestWebmapSharesDialog(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QgsApplication.instance() or QgsApplication([], False)

    def setUp(self):
        self.api_patch = patch("LDMP.webmap_dialog.api.APIClient")
        self.api_mock = self.api_patch.start()
        self.addCleanup(self.api_patch.stop)
        with patch.object(QtCore.QTimer, "singleShot"):
            self.dialog = WebmapSharesDialog()
        self.addCleanup(self.dialog.deleteLater)

    def test_owner_list_and_actions_follow_publication_state(self):
        usage = {
            "uploaded_bytes": 4,
            "reserved_bytes": 5,
            "cleanup_pending_bytes": 1,
            "available_bytes": 15,
            "quota_limit_bytes": 20,
        }
        shares = [
            {"id": "a", "title": "Draft", "state": "ready", "ready_at": None},
            {
                "id": "b",
                "title": "Published",
                "state": "ready",
                "ready_at": "2026-01-01T00:00:00Z",
                "expires_at": "2026-01-08T00:00:00Z",
            },
            {
                "id": "c",
                "title": "Failed",
                "state": "failed",
                "validation_errors": [{"error": "Invalid COG"}],
            },
        ]
        self.dialog._finished("refresh", True, (shares, usage), None)
        self.dialog.table.selectRow(0)
        self.assertTrue(self.dialog.publish_button.isEnabled())
        self.assertFalse(self.dialog.rotate_button.isEnabled())
        self.dialog.table.selectRow(1)
        self.assertFalse(self.dialog.publish_button.isEnabled())
        self.assertTrue(self.dialog.rotate_button.isEnabled())
        self.assertEqual(self.dialog.table.item(1, 2).text(), "2026-01-08T00:00:00Z")
        self.dialog.table.selectRow(2)
        self.assertEqual(self.dialog.details.toPlainText(), "Invalid COG")
        self.assertIn("1 bytes awaiting cleanup", self.dialog.storage.text())

    def test_public_sharing_confirmation_accept_and_cancel(self):
        for accept in (True, False):
            with self.subTest(accept=accept):
                shown = []

                def respond(accept=accept, shown=shown):
                    box = QtWidgets.QApplication.activeModalWidget()
                    cancel = box.button(QtWidgets.QMessageBox.StandardButton.Cancel)
                    shown.append(
                        (box.text(), box.detailedText(), box.defaultButton() is cancel)
                    )
                    button = (
                        next(
                            button
                            for button in box.buttons()
                            if box.buttonRole(button)
                            == QtWidgets.QMessageBox.ButtonRole.AcceptRole
                        )
                        if accept
                        else cancel
                    )
                    button.click()

                QtCore.QTimer.singleShot(0, respond)
                self.assertEqual(
                    confirm_public_sharing(self.dialog, ["Layer"], "Map"), accept
                )
                self.assertIn("Map", shown[0][0])
                self.assertEqual(shown[0][1], "Layer")
                self.assertTrue(shown[0][2])

    def test_edit_layers_selects_removals_and_confirms(self):
        share = {
            "id": "map",
            "state": "ready",
            "ready_at": "2026-01-01",
            "update_state": "idle",
            "layers": [
                {"id": "first", "name": "First", "published": True},
                {"id": "second", "name": "Second", "published": True},
            ],
        }
        self.dialog.shares = [share]
        self.dialog.table.setRowCount(1)
        self.dialog.table.selectRow(0)
        self.dialog._selection_changed()
        self.assertTrue(self.dialog.edit_layers_button.isEnabled())
        observed = []

        def select_layers():
            dialog = QtWidgets.QApplication.activeModalWidget()
            layers = dialog.findChild(QtWidgets.QListWidget)
            buttons = dialog.findChild(QtWidgets.QDialogButtonBox)
            remove = next(
                button
                for button in buttons.buttons()
                if buttons.buttonRole(button)
                == QtWidgets.QDialogButtonBox.ButtonRole.AcceptRole
            )
            observed.append((layers.count(), remove.isEnabled()))
            layers.item(0).setCheckState(QtCore.Qt.Checked)
            observed.append(remove.isEnabled())
            remove.click()

        with (
            patch.object(self.dialog, "_start") as start,
            patch.object(
                QtWidgets.QMessageBox,
                "question",
                return_value=QtWidgets.QMessageBox.Yes,
            ),
        ):
            QtCore.QTimer.singleShot(0, select_layers)
            self.dialog._edit_layers()
        self.assertEqual(observed, [(2, False), True])
        start.assert_called_once_with("remove_layers", layer_ids=["first"])
        with (
            patch.object(self.dialog, "_start") as start,
            patch.object(
                QtWidgets.QMessageBox,
                "question",
                return_value=QtWidgets.QMessageBox.No,
            ),
        ):
            QtCore.QTimer.singleShot(0, select_layers)
            self.dialog._edit_layers()
        start.assert_not_called()
        share["update_state"] = "validating"
        self.dialog._selection_changed()
        self.assertFalse(self.dialog.edit_layers_button.isEnabled())

    @patch("LDMP.webmap_dialog.ShareClient")
    def test_remove_layers_task_sends_selected_ids(self, client):
        client.return_value.remove_layers.return_value = {
            "share": {"id": "map"},
            "cleanup_scheduled": True,
        }
        task = _OwnerTask(
            "https://api.test",
            "token",
            "remove_layers",
            "map",
            Mock(),
            layer_ids=["first", "second"],
        )
        self.assertTrue(task.run(), task.error)
        client.return_value.remove_layers.assert_called_once_with(
            "map", ["first", "second"]
        )

    def test_order_layers_moves_layers_and_saves_new_order(self):
        share = {
            "id": "map",
            "state": "ready",
            "ready_at": "2026-01-01",
            "update_state": "idle",
            "layers": [
                {"id": "first", "name": "First", "published": True},
                {"id": "second", "name": "Second", "published": True},
                {"id": "third", "name": "Third", "published": True},
            ],
        }
        self.dialog.shares = [share]
        self.dialog.table.setRowCount(1)
        self.dialog.table.selectRow(0)
        self.dialog._selection_changed()
        self.assertTrue(self.dialog.order_layers_button.isEnabled())
        observed = []

        def reorder():
            dialog = QtWidgets.QApplication.activeModalWidget()
            layers = dialog.findChild(QtWidgets.QListWidget)
            buttons = dialog.findChild(QtWidgets.QDialogButtonBox)
            save = next(
                button
                for button in buttons.buttons()
                if buttons.buttonRole(button)
                == QtWidgets.QDialogButtonBox.ButtonRole.AcceptRole
            )
            up = next(
                button
                for button in dialog.findChildren(QtWidgets.QPushButton)
                if button.text() == "Move up"
            )
            observed.append(save.isEnabled())
            layers.setCurrentRow(2)
            up.click()
            up.click()
            observed.append(([layers.item(i).text() for i in range(3)], up.isEnabled()))
            save.click()

        with patch.object(self.dialog, "_start") as start:
            QtCore.QTimer.singleShot(0, reorder)
            self.dialog._order_layers()
        self.assertEqual(observed, [False, (["Third", "First", "Second"], False)])
        start.assert_called_once_with(
            "reorder_layers", layer_ids=["third", "first", "second"]
        )
        share["layers"] = share["layers"][:1]
        self.dialog._selection_changed()
        self.assertFalse(self.dialog.order_layers_button.isEnabled())

    @patch("LDMP.webmap_dialog.ShareClient")
    def test_reorder_layers_task_sends_order(self, client):
        client.return_value.reorder_layers.return_value = {"id": "map", "layers": []}
        task = _OwnerTask(
            "https://api.test",
            "token",
            "reorder_layers",
            "map",
            Mock(),
            layer_ids=["second", "first"],
        )
        self.assertTrue(task.run(), task.error)
        client.return_value.reorder_layers.assert_called_once_with(
            "map", ["second", "first"]
        )

    def test_quota_shows_remaining_storage_and_maps(self):
        usage = {
            "uploaded_bytes": 4,
            "reserved_bytes": 5,
            "cleanup_pending_bytes": 0,
            "available_bytes": 15,
            "quota_limit_bytes": 20,
        }
        self.dialog._finished("refresh", True, ([], usage), None)
        self.assertIn("15 bytes remaining", self.dialog.storage.text())
        self.assertNotIn("Maps", self.dialog.storage.text())
        usage.update(
            active_share_count=2,
            active_share_limit=10,
            max_layers_per_share=10,
            max_share_bytes=30,
        )
        self.dialog._finished("refresh", True, ([], usage), None)
        self.assertIn("Maps: 2 of 10 active", self.dialog.storage.text())
        self.assertTrue(self.dialog.quota_button.isEnabled())
        with patch.object(QtWidgets.QMessageBox, "information") as information:
            self.dialog.quota_button.click()
        text = information.call_args.args[2]
        self.assertIn("Storage remaining: 15 bytes", text)
        self.assertIn("Active maps: 2 of 10 (8 remaining)", text)
        self.assertIn("up to 10 layers and 30 bytes", text)

    def test_published_share_link_is_viewable_and_copyable(self):
        usage = {
            "uploaded_bytes": 0,
            "reserved_bytes": 0,
            "cleanup_pending_bytes": 0,
            "available_bytes": 1,
            "quota_limit_bytes": 1,
        }
        published = {"state": "ready", "ready_at": "2026-01-01T00:00:00Z"}
        shares = [
            dict(published, id="a", title="Current", link="https://viewer.test/a#s"),
            dict(published, id="b", title="Legacy", link=None),
        ]
        self.dialog._finished("refresh", True, (shares, usage), None)
        self.dialog.table.selectRow(0)
        self.assertEqual(self.dialog.link.text(), "https://viewer.test/a#s")
        self.assertEqual(self.dialog.table.item(0, 4).text(), "https://viewer.test/a#s")
        self.dialog._copy_link()
        self.assertEqual(
            QtWidgets.QApplication.clipboard().text(), "https://viewer.test/a#s"
        )
        self.dialog.table.selectRow(1)
        self.assertEqual(self.dialog.link.text(), "")
        self.assertFalse(self.dialog.copy_link_button.isEnabled())
        self.assertIn("New link", self.dialog.link.placeholderText())

    def test_published_link_dialog_copies_and_opens_link(self):
        url = "https://viewer.test/share/s/token"
        result = {"link": url, "share": {"expires_at": "2026-01-08T00:00:00Z"}}
        shown = []

        def interact():
            dialog = QtWidgets.QApplication.activeModalWidget()
            link = dialog.findChild(QtWidgets.QLineEdit)
            buttons = dialog.findChild(QtWidgets.QDialogButtonBox)
            actions = {
                button.text(): button
                for button in buttons.buttons()
                if buttons.buttonRole(button)
                == QtWidgets.QDialogButtonBox.ButtonRole.ActionRole
            }
            shown.append((link.text(), link.isReadOnly()))
            actions["Copy link"].click()
            actions["Open in browser"].click()
            buttons.button(QtWidgets.QDialogButtonBox.StandardButton.Close).click()

        QtWidgets.QApplication.clipboard().clear()
        with patch.object(QtGui.QDesktopServices, "openUrl") as open_url:
            QtCore.QTimer.singleShot(0, interact)
            show_link(self.dialog, result)
            open_url.assert_called_once_with(QtCore.QUrl(url))
        self.assertEqual(shown, [(url, True)])
        self.assertEqual(QtWidgets.QApplication.clipboard().text(), url)

    @patch("LDMP.webmap_dialog.ShareClient")
    def test_refresh_fetches_links_only_for_published_shares(self, client):
        client.return_value.list.return_value = [
            {"id": "a", "state": "ready", "ready_at": "2026-01-01T00:00:00Z"},
            {"id": "b", "state": "ready", "ready_at": "2026-01-01T00:00:00Z"},
            {"id": "c", "state": "ready", "ready_at": None},
        ]
        client.return_value.storage.return_value = {
            "uploaded_bytes": 0,
            "reserved_bytes": 0,
            "cleanup_pending_bytes": 0,
            "available_bytes": 1,
            "quota_limit_bytes": 1,
        }
        client.return_value.link.side_effect = [
            {"link": "https://viewer.test/a#s"},
            ShareError("Not stored", 409),
        ]
        task = _OwnerTask("https://api.test", "owner-token", "refresh", None, Mock())
        self.assertTrue(task.run())
        shares, _ = task.result
        self.assertEqual(
            [share["link"] for share in shares],
            ["https://viewer.test/a#s", None, None],
        )
        self.assertEqual(client.return_value.link.call_count, 2)

    def test_busy_dialog_cannot_be_dismissed(self):
        self.dialog.task = Mock()
        with patch.object(QtWidgets.QDialog, "reject") as reject:
            self.dialog.reject()
            reject.assert_not_called()
        self.dialog.task = None

    @patch("LDMP.webmap_dialog.ShareClient")
    def test_task_uses_owner_token_and_closes_client(self, client):
        client.return_value.publish.return_value = {
            "link": "one-time-secret",
            "share": {"expires_at": "2026-01-08T00:00:00Z"},
        }
        task = _OwnerTask("https://api.test", "owner-token", "publish", "id", Mock())
        self.assertTrue(task.run())
        client.assert_called_once()
        client.return_value.publish.assert_called_once_with("id")
        client.return_value.close.assert_called_once()
        self.assertIsNone(task.token)

    @patch("LDMP.webmap_dialog.ShareClient")
    def test_task_surfaces_api_failure(self, client):
        client.return_value.list.side_effect = ShareError("HTTP 403")
        task = _OwnerTask("https://api.test", "owner-token", "refresh", None, Mock())
        self.assertFalse(task.run())
        self.assertEqual(task.error, "HTTP 403")
        client.return_value.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
