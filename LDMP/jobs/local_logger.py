"""File-based logging for local job executions.

Provides a logging handler that writes structured log entries to a JSONL file
(one JSON object per line), mirroring the format used by the remote API's
ExecutionLog model.

Using JSONL (append-only) rather than a JSON array avoids the need to
read-parse-rewrite the entire file on every log entry.  This eliminates
O(N²) I/O growth and — critically — prevents file contention with the
periodic job scanner that globs ``datasets/**/*.json``.  The old JSON-array
handler held the file open in write-truncate mode on every emit, which on
Windows created intermittent file-system level stalls when the scanner
tried to read the same file simultaneously, leading to QGIS freezes.
"""

import datetime as dt
import json
import logging
from pathlib import Path

from .. import conf

MAX_ENTRY_TEXT_LENGTH = 10240  # 10KB per entry


def get_local_job_log_path(job) -> Path:
    """Return the canonical log file path for a local job."""
    base_dir = Path(conf.settings_manager.get_value(conf.Setting.BASE_DIR))
    return base_dir / "datasets" / str(job.id) / "execution.log.jsonl"


def read_local_job_logs(job) -> list:
    """Read and return log entries from a local job's log file.

    Returns an empty list if the file doesn't exist or is malformed.
    """
    log_path = get_local_job_log_path(job)
    if not log_path.exists():
        return []
    try:
        entries = []
        with open(log_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        return entries
    except (OSError, ValueError):
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
    """Logging handler that appends structured entries to a JSONL log file.

    Each log record is serialized as a single JSON object and appended as one
    line.  The file is opened in append mode so there is no need to read or
    rewrite existing content, making each emit() O(1) regardless of log size.

    Thread-safety is provided by the parent class's lock (acquired by
    ``handle()`` before ``emit()`` is called).
    """

    def __init__(self, log_file_path: Path):
        super().__init__()
        self.log_file_path = log_file_path

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

            with open(self.log_file_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")

        except Exception:
            self.handleError(record)
