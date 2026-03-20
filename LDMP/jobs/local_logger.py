"""File-based logging for local job executions.

Provides a logging handler that writes structured log entries to a JSON file,
mirroring the format used by the remote API's ExecutionLog model.
"""

import datetime as dt
import json
import logging
import threading
from pathlib import Path

from .. import conf

MAX_ENTRY_TEXT_LENGTH = 10240  # 10KB per entry


def get_local_job_log_path(job) -> Path:
    """Return the canonical log file path for a local job."""
    base_dir = Path(conf.settings_manager.get_value(conf.Setting.BASE_DIR))
    return base_dir / "datasets" / str(job.id) / "execution.log.json"


def read_local_job_logs(job) -> list:
    """Read and return log entries from a local job's log file.

    Returns an empty list if the file doesn't exist or is malformed.
    """
    log_path = get_local_job_log_path(job)
    if not log_path.exists():
        return []
    try:
        with open(log_path, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
        return []
    except (json.JSONDecodeError, OSError, ValueError):
        return []


def setup_local_job_logger(job) -> logging.Logger:
    """Create a per-job logger that writes structured entries to the job's log file.

    Also attaches a stderr handler for development visibility.
    """
    logger = logging.getLogger(f"trendsearth.local_job.{job.id}")
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    # Remove any existing handlers (in case of re-setup)
    for h in logger.handlers[:]:
        logger.removeHandler(h)

    log_path = get_local_job_log_path(job)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    logger.addHandler(LocalJobLogHandler(log_path))
    logger.addHandler(logging.StreamHandler())

    return logger


class LocalJobLogHandler(logging.Handler):
    """Logging handler that appends structured entries to a JSON log file.

    Thread-safe via a lock, suitable for use from QgsTask background threads.
    """

    def __init__(self, log_file_path: Path):
        super().__init__()
        self.log_file_path = log_file_path
        self._lock = threading.Lock()

    def emit(self, record: logging.LogRecord):
        try:
            text = self.format(record)
            if len(text) > MAX_ENTRY_TEXT_LENGTH:
                text = text[:MAX_ENTRY_TEXT_LENGTH] + "... [truncated]"

            entry = {
                "text": text,
                "level": record.levelname,
                "register_date": dt.datetime.now(dt.timezone.utc).isoformat(),
            }

            with self._lock:
                entries = []
                if self.log_file_path.exists():
                    try:
                        with open(self.log_file_path, encoding="utf-8") as f:
                            data = json.load(f)
                        if isinstance(data, list):
                            entries = data
                    except (json.JSONDecodeError, OSError):
                        entries = []

                entries.append(entry)

                with open(self.log_file_path, "w", encoding="utf-8") as f:
                    json.dump(entries, f, indent=2, ensure_ascii=False)

        except Exception:
            self.handleError(record)
