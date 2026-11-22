"""Tests for owner share controls."""

import unittest
from unittest.mock import Mock, patch

from qgis.core import QgsApplication
from qgis.PyQt import QtCore, QtWidgets

from LDMP.webmap_dialog import WebmapSharesDialog, _OwnerTask
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
        self.assertIn("pending cleanup 1", self.dialog.storage.text())

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
