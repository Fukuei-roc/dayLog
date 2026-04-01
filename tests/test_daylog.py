from __future__ import annotations

import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path

from app.commands import apply_command, run_command
from app.markdown_codec import parse_markdown
from app.models import SECTION_CARRY, SECTION_ROUTINE, SECTION_TODAY
from app.storage import build_new_daily_document, ensure_project_layout, load_or_create_today


class DayLogTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.paths = ensure_project_layout(self.root)
        self.paths.template.write_text("- [ ] 例行一\n- [ ] 例行二\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_create_new_daily_file(self) -> None:
        doc, path = load_or_create_today(self.root, date(2026, 4, 1))
        self.assertTrue(path.exists())
        self.assertEqual(doc.date_text, "2026-04-01")
        self.assertIn(SECTION_ROUTINE, doc.sections)
        self.assertIn(SECTION_CARRY, doc.sections)
        self.assertIn(SECTION_TODAY, doc.sections)

    def test_template_copy(self) -> None:
        doc = build_new_daily_document(self.paths, date(2026, 4, 1))
        self.assertEqual([item.text for item in doc.sections[SECTION_ROUTINE]], ["例行一", "例行二"])

    def test_carry_over_only_unfinished_temporary_tasks(self) -> None:
        yesterday = self.paths.daily_file(date(2026, 3, 31))
        yesterday.write_text(
            "\n".join(
                [
                    "# 2026-03-31",
                    "",
                    "## 每日例行任務",
                    "- [ ] 不應延續的例行",
                    "",
                    "## 延續的臨時任務",
                    "- [ ] 保留 A",
                    "  - 備註 A",
                    "  - [x] 已完成子任務",
                    "  - [ ] 未完成子任務",
                    "- [x] 不保留 B",
                    "",
                    "## 今日臨時任務",
                    "- [ ] 保留 C",
                    "- [-] 不保留 D",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        doc = build_new_daily_document(self.paths, date(2026, 4, 1))
        carried = doc.sections[SECTION_CARRY]
        self.assertEqual([item.text for item in carried], ["保留 A", "保留 C"])
        self.assertEqual(carried[0].children[0].text, "備註 A")
        self.assertEqual(carried[0].children[-1].text, "未完成子任務")

    def test_todo_command(self) -> None:
        doc = build_new_daily_document(self.paths, date(2026, 4, 1))
        apply_command(doc, "/todo 寫測試", SECTION_TODAY, now=datetime(2026, 4, 1, 9, 30))
        self.assertEqual(doc.sections[SECTION_TODAY][-1].text, "寫測試")

    def test_date_command(self) -> None:
        doc = build_new_daily_document(self.paths, date(2026, 4, 1))
        apply_command(doc, "/date", SECTION_TODAY, now=datetime(2026, 4, 1, 9, 30))
        self.assertEqual(doc.sections[SECTION_TODAY][-1].text, "2026-04-01")

    def test_time_command(self) -> None:
        doc = build_new_daily_document(self.paths, date(2026, 4, 1))
        apply_command(doc, "/time", SECTION_TODAY, now=datetime(2026, 4, 1, 9, 30))
        self.assertEqual(doc.sections[SECTION_TODAY][-1].text, "09:30")

    def test_hierarchy_parsing(self) -> None:
        doc = parse_markdown(
            "\n".join(
                [
                    "# 2026-04-01",
                    "",
                    "## 每日例行任務",
                    "- [ ] 父任務",
                    "  - [ ] 子任務",
                    "  - 筆記",
                    "",
                    "## 延續的臨時任務",
                    "",
                    "## 今日臨時任務",
                    "",
                ]
            )
        )
        parent = doc.sections[SECTION_ROUTINE][0]
        self.assertEqual(parent.text, "父任務")
        self.assertEqual(parent.children[0].text, "子任務")
        self.assertEqual(parent.children[1].text, "筆記")

    def test_command_parser(self) -> None:
        result = run_command("/todo 收信", now=datetime(2026, 4, 1, 8, 0))
        self.assertEqual(result.kind, "todo")
        self.assertEqual(result.payload, "收信")


if __name__ == "__main__":
    unittest.main()
