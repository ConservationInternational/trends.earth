import tempfile
import unittest
from pathlib import Path

from scripts.check_ruff import new_diagnostics


class TestRuffBaseline(unittest.TestCase):
    def test_empty_module_diagnostic_is_compared(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "empty.py"
            path.touch()
            item = {
                "filename": str(path),
                "code": "N999",
                "message": "Invalid module name",
                "location": {"row": 1, "column": 1},
            }
            self.assertEqual(new_diagnostics([item], [item], root, root), [])
            self.assertEqual(new_diagnostics([], [item], root, root), [item])

    def test_shifted_lines_do_not_hide_new_or_duplicate_violations(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory) / "base"
            current = Path(directory) / "current"
            base.mkdir()
            current.mkdir()
            (base / "example.py").write_text("bad()\n", encoding="utf-8")
            (current / "example.py").write_text(
                "\nbad()\nother_bad()\nbad()\n", encoding="utf-8"
            )

            def diagnostic(root, row, code="B008"):
                return {
                    "filename": str(root / "example.py"),
                    "code": code,
                    "message": "Violation",
                    "location": {"row": row, "column": 1},
                }

            added = [
                diagnostic(current, 3),
                diagnostic(current, 4),
                diagnostic(current, 2, "F821"),
            ]
            self.assertEqual(
                new_diagnostics(
                    [diagnostic(base, 1)],
                    [diagnostic(current, 2), *added],
                    base,
                    current,
                ),
                added,
            )
