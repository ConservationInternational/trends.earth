"""Global dialog manager to keep strong references to open dialogs."""

import typing

from qgis.PyQt import QtCore


class DialogManager:
    """Singleton class to manage open dialogs and prevent garbage collection.

    All access to the internal ``_open_dialogs`` dict is serialised with a
    mutex so callers from background threads (e.g. worker finished-callbacks)
    cannot corrupt the dict.
    """

    _instance: typing.ClassVar[typing.Optional["DialogManager"]] = None
    _instance_lock: typing.ClassVar[QtCore.QMutex] = QtCore.QMutex()

    _open_dialogs: typing.Dict[str, typing.Any]
    _lock: QtCore.QMutex

    def __new__(cls):
        if cls._instance is None:
            cls._instance_lock.lock()
            try:
                if cls._instance is None:
                    instance = super().__new__(cls)
                    instance._open_dialogs = {}
                    instance._lock = QtCore.QMutex()
                    cls._instance = instance
            finally:
                cls._instance_lock.unlock()
        return cls._instance

    def register_dialog(self, dialog_id: str, dialog):
        """Register a dialog to keep it alive."""
        self._lock.lock()
        try:
            self._open_dialogs[dialog_id] = dialog
        finally:
            self._lock.unlock()

    def unregister_dialog(self, dialog_id: str):
        """Unregister a dialog when it's closed."""
        self._lock.lock()
        try:
            self._open_dialogs.pop(dialog_id, None)
        finally:
            self._lock.unlock()

    def get_dialog(self, dialog_id: str):
        """Get an existing dialog by ID."""
        self._lock.lock()
        try:
            return self._open_dialogs.get(dialog_id)
        finally:
            self._lock.unlock()

    def is_dialog_open(self, dialog_id: str) -> bool:
        """Check if a dialog is currently open."""
        self._lock.lock()
        try:
            dialog = self._open_dialogs.get(dialog_id)
        finally:
            self._lock.unlock()
        return dialog is not None and not dialog.isHidden()

    def close_all_dialogs(self):
        """Close all managed dialogs."""
        self._lock.lock()
        try:
            dialogs = list(self._open_dialogs.values())
            self._open_dialogs.clear()
        finally:
            self._lock.unlock()
        for dialog in dialogs:
            if dialog and not dialog.isHidden():
                dialog.close()


# Global instance
dialog_manager = DialogManager()
