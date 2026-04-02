from __future__ import annotations

import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path

from app.commands import apply_command, expand_note_macro, run_command
from app.markdown_codec import parse_markdown, serialize_document
from app.models import Item, SECTION_ROUTINE, SECTION_TEMPORARY, TASK_CANCELED, TASK_OPEN
from app.storage import build_new_daily_document, ensure_project_layout, find_previous_daily_file, load_or_create_today
from app.tui import CHAR_UNION, DIALOG_UNAVAILABLE, DayLogApp, EditorState, KEY_EVENT_RECORD, SHIFT_PRESSED, VisibleRow, apply_editor_key


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
        self.assertIn(SECTION_TEMPORARY, doc.sections)

    def test_template_copy(self) -> None:
        doc = build_new_daily_document(self.paths, date(2026, 4, 1))
        self.assertEqual([item.text for item in doc.sections[SECTION_ROUTINE]], ["例行一", "例行二"])

    def test_carry_over_from_previous_existing_day_keeps_open_and_canceled_tasks(self) -> None:
        previous = self.paths.daily_file(date(2026, 3, 30))
        previous.write_text(
            "\n".join(
                [
                    "# 2026-03-30",
                    "",
                    "## 每日例行任務",
                    "- [ ] 不應延續的例行",
                    "",
                    "## 臨時任務",
                    "- [ ] 保留 A",
                    "  - 備註 A",
                    "  - [x] 已完成子任務",
                    "  - [ ] 未完成子任務",
                    "- [x] 不保留 B",
                    "- [-] 保留 C",
                    "  - 取消原因",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        doc = build_new_daily_document(self.paths, date(2026, 4, 1))
        carried = doc.sections[SECTION_TEMPORARY]
        self.assertEqual([item.text for item in carried], ["保留 A", "保留 C"])
        self.assertEqual(carried[0].children[0].text, "備註 A")
        self.assertEqual(carried[0].children[-1].text, "未完成子任務")
        self.assertEqual(carried[1].status, TASK_CANCELED)
        self.assertEqual(carried[1].children[0].text, "取消原因")

    def test_todo_command(self) -> None:
        doc = build_new_daily_document(self.paths, date(2026, 4, 1))
        apply_command(doc, "/todo 寫測試", SECTION_TEMPORARY, now=datetime(2026, 4, 1, 9, 30))
        self.assertEqual(doc.sections[SECTION_TEMPORARY][-1].text, "寫測試")

    def test_date_command(self) -> None:
        with self.assertRaises(ValueError):
            run_command("/date", now=datetime(2026, 4, 1, 9, 30))

    def test_time_command(self) -> None:
        with self.assertRaises(ValueError):
            run_command("/time", now=datetime(2026, 4, 1, 9, 30))

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
                    "## 臨時任務",
                    "",
                ]
            )
        )
        parent = doc.sections[SECTION_ROUTINE][0]
        self.assertEqual(parent.text, "父任務")
        self.assertEqual(parent.children[0].text, "子任務")
        self.assertEqual(parent.children[1].text, "筆記")

    def test_serialize_document_removes_extra_blank_preamble_lines(self) -> None:
        doc = parse_markdown(
            "\n".join(
                [
                    "# 2026-04-01",
                    "",
                    "",
                    "",
                    "## 每日例行任務",
                    "- [ ] 任務",
                    "",
                    "## 臨時任務",
                    "",
                ]
            )
        )
        serialized = serialize_document(doc)
        self.assertTrue(serialized.startswith("# 2026-04-01\n\n## 每日例行任務"))

    def test_command_parser(self) -> None:
        result = run_command("/todo 收信", now=datetime(2026, 4, 1, 8, 0))
        self.assertEqual(result.kind, "todo")
        self.assertEqual(result.payload, "收信")

    def test_expand_note_macro_date_with_suffix(self) -> None:
        result = expand_note_macro("/date 開始處理", now=datetime(2026, 4, 1, 8, 0))
        self.assertEqual(result, "2026-04-01 開始處理")

    def test_editor_inserts_and_moves_cursor(self) -> None:
        state = EditorState(text="ab", cursor=1)
        state = apply_editor_key(state, "X")
        self.assertEqual(state.text, "aXb")
        self.assertEqual(state.cursor, 2)
        state = apply_editor_key(state, "LEFT")
        self.assertEqual(state.cursor, 1)

    def test_editor_delete_and_backspace(self) -> None:
        state = EditorState(text="abc", cursor=2)
        state = apply_editor_key(state, "BACKSPACE")
        self.assertEqual(state.text, "ac")
        self.assertEqual(state.cursor, 1)
        state = apply_editor_key(state, "DELETE")
        self.assertEqual(state.text, "a")
        self.assertEqual(state.cursor, 1)

    def test_outdent_moves_item_back_to_parent_level(self) -> None:
        doc = build_new_daily_document(self.paths, date(2026, 4, 1))
        parent = Item(kind="task", text="父任務", status=TASK_OPEN)
        child = Item(kind="task", text="子任務", status=TASK_OPEN)
        parent.children.append(child)
        doc.sections[SECTION_TEMPORARY] = [parent]
        app = DayLogApp(doc, self.paths.daily_file(date(2026, 4, 1)))
        visible = [
            VisibleRow(row_type="section", section=SECTION_TEMPORARY),
            VisibleRow(row_type="item", section=SECTION_TEMPORARY, item=parent, parent_list=doc.sections[SECTION_TEMPORARY], parent_item=None, depth=0),
            VisibleRow(row_type="item", section=SECTION_TEMPORARY, item=child, parent_list=parent.children, parent_item=parent, depth=1),
        ]
        app.selected_index = 2
        app._outdent_current(visible)
        self.assertEqual([item.text for item in doc.sections[SECTION_TEMPORARY]], ["父任務", "子任務"])
        self.assertEqual(parent.children, [])

    def test_add_note_on_note_creates_child_note(self) -> None:
        doc = build_new_daily_document(self.paths, date(2026, 4, 1))
        parent_task = Item(kind="task", text="任務", status=TASK_OPEN)
        parent_note = Item(kind="note", text="第一層筆記")
        parent_task.children.append(parent_note)
        doc.sections[SECTION_TEMPORARY] = [parent_task]
        app = DayLogApp(doc, self.paths.daily_file(date(2026, 4, 1)))
        app._prompt = lambda label, initial="": "第二層筆記"
        visible = [
            VisibleRow(row_type="section", section=SECTION_TEMPORARY),
            VisibleRow(row_type="item", section=SECTION_TEMPORARY, item=parent_task, parent_list=doc.sections[SECTION_TEMPORARY], parent_item=None, depth=0),
            VisibleRow(row_type="item", section=SECTION_TEMPORARY, item=parent_note, parent_list=parent_task.children, parent_item=parent_task, depth=1),
        ]
        app.selected_index = 2
        app._add_note(visible)
        self.assertEqual([child.text for child in parent_note.children], ["第二層筆記"])

    def test_expand_note_macro_time_with_suffix(self) -> None:
        result = expand_note_macro("/time 開始會議", now=datetime(2026, 4, 1, 9, 30))
        self.assertEqual(result, "09:30 開始會議")

    def test_expand_note_macro_time_without_space_before_suffix(self) -> None:
        result = expand_note_macro("/time時間測試", now=datetime(2026, 4, 1, 9, 30))
        self.assertEqual(result, "09:30 時間測試")

    def test_move_current_reorders_within_same_level(self) -> None:
        doc = build_new_daily_document(self.paths, date(2026, 4, 1))
        first = Item(kind="task", text="第一項", status=TASK_OPEN)
        second = Item(kind="task", text="第二項", status=TASK_OPEN)
        third = Item(kind="task", text="第三項", status=TASK_OPEN)
        doc.sections[SECTION_TEMPORARY] = [first, second, third]
        app = DayLogApp(doc, self.paths.daily_file(date(2026, 4, 1)))
        visible = [
            VisibleRow(row_type="section", section=SECTION_TEMPORARY),
            VisibleRow(row_type="item", section=SECTION_TEMPORARY, item=first, parent_list=doc.sections[SECTION_TEMPORARY], parent_item=None, depth=0),
            VisibleRow(row_type="item", section=SECTION_TEMPORARY, item=second, parent_list=doc.sections[SECTION_TEMPORARY], parent_item=None, depth=0),
            VisibleRow(row_type="item", section=SECTION_TEMPORARY, item=third, parent_list=doc.sections[SECTION_TEMPORARY], parent_item=None, depth=0),
        ]
        app.selected_index = 2
        app._move_current(visible, -1)
        self.assertEqual([item.text for item in doc.sections[SECTION_TEMPORARY]], ["第二項", "第一項", "第三項"])

    def test_handle_key_lowercase_j_moves_up_within_same_level(self) -> None:
        doc = build_new_daily_document(self.paths, date(2026, 4, 1))
        first = Item(kind="task", text="第一項", status=TASK_OPEN)
        second = Item(kind="task", text="第二項", status=TASK_OPEN)
        doc.sections[SECTION_TEMPORARY] = [first, second]
        app = DayLogApp(doc, self.paths.daily_file(date(2026, 4, 1)))
        visible = [
            VisibleRow(row_type="section", section=SECTION_TEMPORARY),
            VisibleRow(row_type="item", section=SECTION_TEMPORARY, item=first, parent_list=doc.sections[SECTION_TEMPORARY], parent_item=None, depth=0),
            VisibleRow(row_type="item", section=SECTION_TEMPORARY, item=second, parent_list=doc.sections[SECTION_TEMPORARY], parent_item=None, depth=0),
        ]
        app.selected_index = 2
        app._handle_key("j", visible)
        self.assertEqual([item.text for item in doc.sections[SECTION_TEMPORARY]], ["第二項", "第一項"])

    def test_handle_key_z_jumps_to_top(self) -> None:
        app = DayLogApp(build_new_daily_document(self.paths, date(2026, 4, 1)), self.paths.daily_file(date(2026, 4, 1)))
        visible = app._visible_rows()
        app.selected_index = min(3, len(visible) - 1)
        app._handle_key("z", visible)
        self.assertEqual(app.selected_index, 0)

    def test_handle_key_x_jumps_to_bottom(self) -> None:
        app = DayLogApp(build_new_daily_document(self.paths, date(2026, 4, 1)), self.paths.daily_file(date(2026, 4, 1)))
        visible = app._visible_rows()
        app.selected_index = 0
        app._handle_key("x", visible)
        self.assertEqual(app.selected_index, len(visible) - 1)

    def test_find_previous_daily_file_uses_latest_existing_day(self) -> None:
        self.paths.daily_file(date(2026, 3, 28)).write_text("# 2026-03-28\n", encoding="utf-8")
        self.paths.daily_file(date(2026, 3, 31)).write_text("# 2026-03-31\n", encoding="utf-8")
        previous = find_previous_daily_file(self.paths, date(2026, 4, 1))
        self.assertEqual(previous, self.paths.daily_file(date(2026, 3, 31)))

    def test_virtual_key_mapping_keeps_c_hotkey_stable(self) -> None:
        app = DayLogApp(build_new_daily_document(self.paths, date(2026, 4, 1)), self.paths.daily_file(date(2026, 4, 1)))
        key = KEY_EVENT_RECORD(1, 1, ord("C"), 0, CHAR_UNION(UnicodeChar="c"), SHIFT_PRESSED - SHIFT_PRESSED)
        self.assertEqual(app._map_virtual_key(key), "c")

    def test_virtual_key_mapping_preserves_shift_for_uppercase_shortcuts(self) -> None:
        app = DayLogApp(build_new_daily_document(self.paths, date(2026, 4, 1)), self.paths.daily_file(date(2026, 4, 1)))
        key = KEY_EVENT_RECORD(1, 1, ord("A"), 0, CHAR_UNION(UnicodeChar="A"), SHIFT_PRESSED)
        self.assertEqual(app._map_virtual_key(key), "A")

    def test_hide_completed_mode_shows_only_open_task_branches(self) -> None:
        doc = build_new_daily_document(self.paths, date(2026, 4, 1))
        open_parent = Item(kind="task", text="未完成母任務", status=TASK_OPEN)
        open_child = Item(kind="task", text="未完成子任務", status=TASK_OPEN)
        done_child = Item(kind="task", text="已完成子任務", status="x")
        open_parent.children.extend([open_child, done_child])
        done_parent = Item(kind="task", text="已完成母任務", status="x")
        done_parent.children.append(Item(kind="task", text="不應顯示的子任務", status=TASK_OPEN))
        doc.sections[SECTION_TEMPORARY] = [open_parent, done_parent]
        app = DayLogApp(doc, self.paths.daily_file(date(2026, 4, 1)))
        app.hide_completed = True
        visible_texts = [row.item.text for row in app._visible_rows() if row.item is not None]
        self.assertIn("未完成母任務", visible_texts)
        self.assertIn("未完成子任務", visible_texts)
        self.assertNotIn("已完成子任務", visible_texts)
        self.assertNotIn("已完成母任務", visible_texts)
        self.assertNotIn("不應顯示的子任務", visible_texts)

    def test_hide_completed_mode_hides_note_parents_without_visible_children(self) -> None:
        doc = build_new_daily_document(self.paths, date(2026, 4, 1))
        note_parent = Item(kind="note", text="標題")
        note_parent.children.append(Item(kind="task", text="已完成子任務", status="x"))
        doc.sections[SECTION_ROUTINE] = [note_parent]
        app = DayLogApp(doc, self.paths.daily_file(date(2026, 4, 1)))
        app.hide_completed = True
        visible_texts = [row.item.text for row in app._visible_rows() if row.item is not None]
        self.assertNotIn("標題", visible_texts)

    def test_toggle_hide_completed_switches_mode(self) -> None:
        app = DayLogApp(build_new_daily_document(self.paths, date(2026, 4, 1)), self.paths.daily_file(date(2026, 4, 1)))
        self.assertFalse(app.hide_completed)
        app._toggle_hide_completed()
        self.assertTrue(app.hide_completed)
        app._toggle_hide_completed()
        self.assertFalse(app.hide_completed)

    def test_add_quick_note_appends_to_top_level_bottom(self) -> None:
        doc = build_new_daily_document(self.paths, date(2026, 4, 1))
        doc.sections[SECTION_TEMPORARY] = [Item(kind="task", text="任務", status=TASK_OPEN)]
        app = DayLogApp(doc, self.paths.daily_file(date(2026, 4, 1)))
        app._prompt = lambda label, initial="": "快速記錄"
        app._add_quick_note()
        self.assertEqual(doc.sections[SECTION_TEMPORARY][-1].kind, "note")
        self.assertEqual(doc.sections[SECTION_TEMPORARY][-1].text, "快速記錄")
        visible = app._visible_rows()
        self.assertEqual(visible[app.selected_index].item.text, "快速記錄")

    def test_line_editor_does_not_fallback_when_dialog_cancelled(self) -> None:
        app = DayLogApp(build_new_daily_document(self.paths, date(2026, 4, 1)), self.paths.daily_file(date(2026, 4, 1)))
        app._dialog_prompt = lambda label, initial="": None
        app._inline_line_editor = lambda label, initial="": "不應進入"
        self.assertIsNone(app._line_editor("任務內容", ""))

    def test_line_editor_falls_back_only_when_dialog_unavailable(self) -> None:
        app = DayLogApp(build_new_daily_document(self.paths, date(2026, 4, 1)), self.paths.daily_file(date(2026, 4, 1)))
        app._dialog_prompt = lambda label, initial="": DIALOG_UNAVAILABLE
        app._inline_line_editor = lambda label, initial="": "fallback"
        self.assertEqual(app._line_editor("任務內容", ""), "fallback")


if __name__ == "__main__":
    unittest.main()
