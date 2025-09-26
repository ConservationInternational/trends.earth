"""Global dialog manager to keep strong references to open dialogs."""


class DialogManager:
    """Singleton class to manage open dialogs and prevent garbage collection."""

    _instance = None
    _open_dialogs = {}

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(DialogManager, cls).__new__(cls)
        return cls._instance

    def register_dialog(self, dialog_id: str, dialog):
        """Register a dialog to keep it alive."""
        self._open_dialogs[dialog_id] = dialog

    def unregister_dialog(self, dialog_id: str):
        """Unregister a dialog when it's closed."""
        if dialog_id in self._open_dialogs:
            del self._open_dialogs[dialog_id]

    def get_dialog(self, dialog_id: str):
        """Get an existing dialog by ID."""
        return self._open_dialogs.get(dialog_id)

    def is_dialog_open(self, dialog_id: str) -> bool:
        """Check if a dialog is currently open."""
        dialog = self._open_dialogs.get(dialog_id)
        return dialog is not None and not dialog.isHidden()

    def close_all_dialogs(self):
        """Close all managed dialogs."""
        for dialog in list(self._open_dialogs.values()):
            if dialog and not dialog.isHidden():
                dialog.close()
        self._open_dialogs.clear()


# Global instance
dialog_manager = DialogManager()
