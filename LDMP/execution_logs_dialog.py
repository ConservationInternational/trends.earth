"""Execution logs dialog for Trends.Earth QGIS plugin."""

import datetime
import os
import typing
from pathlib import Path

import requests
from qgis.PyQt import QtCore, QtGui, QtWidgets, uic
from te_schemas.jobs import JobStatus

from .dialog_manager import dialog_manager
from .jobs.models import Job
from .logger import log

DlgExecutionLogsUi, _ = uic.loadUiType(
    str(Path(__file__).parents[0] / "gui/DlgExecutionLogs.ui")
)

ICON_PATH = os.path.join(os.path.dirname(__file__), "icons")


class DlgExecutionLogs(QtWidgets.QDialog, DlgExecutionLogsUi):
    """Dialog for displaying execution logs."""

    job: Job

    jobInfoLabel: QtWidgets.QLabel
    logsTextEdit: QtWidgets.QTextEdit
    refreshButton: QtWidgets.QPushButton
    closeButton: QtWidgets.QPushButton
    statusLabel: QtWidgets.QLabel
    autoRefreshCheckBox: QtWidgets.QCheckBox

    def __init__(self, job: Job, parent=None):
        super().__init__(parent)
        self.setupUi(self)
        self.job = job
        self.dialog_id = f"logs_{str(job.id)}"

        # Set window title with execution ID
        self.setWindowTitle(f"Execution Logs - {str(job.id)}")

        # Hide job info label
        self.jobInfoLabel.hide()

        # Make this a standalone window
        self.setWindowFlags(
            QtCore.Qt.Window
            | QtCore.Qt.WindowCloseButtonHint
            | QtCore.Qt.WindowMinMaxButtonsHint
        )

        # Register with dialog manager to prevent garbage collection
        dialog_manager.register_dialog(self.dialog_id, self)

        # Connect signals
        self.refreshButton.clicked.connect(self.refresh_logs)
        self.autoRefreshCheckBox.toggled.connect(self._on_auto_refresh_toggled)

        # Setup auto-refresh timer
        self.auto_refresh_timer = QtCore.QTimer()
        self.auto_refresh_timer.timeout.connect(self.refresh_logs)
        self.auto_refresh_timer.setSingleShot(False)  # Repeat timer

        # Set monospace font for logs
        font = QtGui.QFont()
        font.setFamily("Consolas, Monaco, 'Courier New', monospace")
        font.setPointSize(9)
        self.logsTextEdit.setFont(font)

        # Set text edit styling similar to API UI
        self.logsTextEdit.setStyleSheet("""
            QTextEdit {
                background-color: #f8f9fa;
                border: 1px solid #dee2e6;
                border-radius: 4px;
                padding: 8px;
                color: #212529;
            }
        """)

        # Initial load of logs
        self.refresh_logs()

    def refresh_logs(self):
        """Fetch and display logs from the API."""
        self.statusLabel.setText("Fetching logs...")
        self.refreshButton.setEnabled(False)

        try:
            logs = self._fetch_logs_from_api()
            current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            if logs:
                formatted_logs = self._format_logs(logs)
                self.logsTextEdit.setPlainText(formatted_logs)
                self.statusLabel.setText(
                    f"Loaded {len(logs)} log entries - Last updated: {current_time}"
                )
            else:
                self.logsTextEdit.setPlainText("No logs found for this execution.")
                self.statusLabel.setText(
                    f"No logs available - Last updated: {current_time}"
                )

        except Exception as e:
            error_msg = f"Failed to fetch logs: {str(e)}"

            self.logsTextEdit.setPlainText(error_msg)
            self.statusLabel.setText("Error fetching logs")
            log(f"Error fetching logs for job {self.job.id}: {e}")

        finally:
            self.refreshButton.setEnabled(True)

    def _on_auto_refresh_toggled(self, checked: bool):
        """Handle auto-refresh checkbox toggle."""
        if checked:
            # Start auto-refresh timer (30 seconds = 30000 milliseconds)
            self.auto_refresh_timer.start(30000)
            log(f"Auto-refresh enabled for execution logs {self.job.id}")
        else:
            # Stop auto-refresh timer
            self.auto_refresh_timer.stop()
            log(f"Auto-refresh disabled for execution logs {self.job.id}")

    def _fetch_logs_from_api(self) -> typing.Optional[typing.List[typing.Dict]]:
        """Fetch logs from the trends.earth API."""
        # Get API settings
        from .constants import API_URL

        api_url = API_URL
        if not api_url:
            raise Exception("API URL not configured")

        # Get access token
        from .jobs.manager import _get_access_token

        token = _get_access_token()
        if not token:
            raise Exception("No access token available. Please log in to Trends.Earth.")

        # Make API request
        url = f"{api_url}/api/v1/execution/{self.job.id}/log"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            # Note: Don't include 'br' (Brotli) - requests library doesn't support it
            # without the brotli package, and we don't want to add that dependency
            "Accept-Encoding": "gzip, deflate",
        }

        log(f"Fetching logs from: {url}")
        response = requests.get(url, headers=headers, timeout=30)

        if response.status_code == 200:
            try:
                data = response.json()
                return data.get("data", [])
            except ValueError as e:
                log(f"Failed to parse JSON response: {e}")
                log(f"Response content (first 500 chars): {response.text[:500]}")
                raise Exception(
                    "Server returned invalid response. Please try again later."
                )
        elif response.status_code == 404:
            raise Exception("Execution not found on server")
        elif response.status_code == 401:
            raise Exception("Authentication failed. Please log in again.")
        elif response.status_code in [502, 503, 504]:
            raise Exception(
                f"The Trends.Earth server is temporarily unavailable (error {response.status_code}). "
                "Please try again in a few minutes."
            )
        elif response.status_code == 500:
            raise Exception(
                "The Trends.Earth server encountered an internal error. "
                "Please try again. If the problem persists, contact the Trends.Earth team."
            )
        else:
            raise Exception(
                f"API request failed: {response.status_code} - {response.text}"
            )

    def _format_logs(self, logs: typing.List[typing.Dict]) -> str:
        """Format logs for display."""
        if not logs:
            return "No logs available for this execution."

        formatted_lines = []

        # Sort logs by register_date in descending order (newest first)
        sorted_logs = sorted(
            logs, key=lambda x: x.get("register_date", ""), reverse=True
        )

        for log_entry in sorted_logs:
            # Extract log fields (matching API model structure)
            register_date = log_entry.get("register_date", "")
            level = log_entry.get("level", "INFO")
            text = log_entry.get("text", "")

            # Format the timestamp
            formatted_date = self._format_timestamp(register_date)

            # Create formatted log line similar to API UI style:
            # "2025-01-15 10:30:45 - INFO - Log message text"
            log_line = f"{formatted_date} - {level} - {text}"
            formatted_lines.append(log_line)

        # Add summary at the top
        summary_line = f"=== Execution Logs ({len(logs)} entries) ==="
        return f"{summary_line}\n\n" + "\n".join(formatted_lines)

    def _format_timestamp(self, timestamp_str: str) -> str:
        """Format timestamp string for display."""
        if not timestamp_str:
            return "Unknown Time"

        try:
            # Parse ISO format timestamp
            if timestamp_str.endswith("Z"):
                timestamp_str = timestamp_str[:-1] + "+00:00"

            dt = datetime.datetime.fromisoformat(timestamp_str)

            # Convert to local time if it's UTC
            if dt.tzinfo is not None:
                dt = dt.astimezone()

            # Format as: "2025-01-15 10:30:45"
            return dt.strftime("%Y-%m-%d %H:%M:%S")

        except (ValueError, TypeError):
            # If parsing fails, return the original string
            return timestamp_str

    def closeEvent(self, event):
        """Handle dialog close event."""
        # Stop auto-refresh timer if running
        if hasattr(self, "auto_refresh_timer"):
            self.auto_refresh_timer.stop()

        # Unregister from dialog manager when closing
        dialog_manager.unregister_dialog(self.dialog_id)
        # Accept the close event
        event.accept()

    @staticmethod
    def show_logs_for_job(job: Job, parent=None) -> None:
        """Static method to show logs for a job."""
        # Only show logs for non-local jobs
        if job.status == JobStatus.GENERATED_LOCALLY:
            QtWidgets.QMessageBox.information(
                parent,
                "Logs Not Available",
                "Logs are not available for locally generated datasets.",
            )
            return

        dialog = DlgExecutionLogs(job, parent)
        dialog.exec_()
