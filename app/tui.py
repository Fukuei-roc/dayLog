from __future__ import annotations

import ctypes
import msvcrt
import sys
from dataclasses import dataclass
from pathlib import Path
from shutil import get_terminal_size
from typing import List, Optional

from app.commands import apply_command, expand_note_macro
from app.models import Document, Item, SECTION_ORDER, TASK_CANCELED, TASK_DONE, TASK_OPEN
from app.storage import save_document


class COORD(ctypes.Structure):
    _fields_ = [("X", ctypes.c_short), ("Y", ctypes.c_short)]


class CONSOLE_CURSOR_INFO(ctypes.Structure):
    _fields_ = [("dwSize", ctypes.c_uint), ("bVisible", ctypes.c_int)]


class DWORD(ctypes.c_ulong):
    pass


GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
FILE_SHARE_READ = 0x00000001
FILE_SHARE_WRITE = 0x00000002
OPEN_EXISTING = 3
CONSOLE_TEXTMODE_BUFFER = 1
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value


@dataclass
class VisibleRow:
    row_type: str
    section: str
    item: Optional[Item] = None
    parent_list: Optional[List[Item]] = None
    parent_item: Optional[Item] = None
    depth: int = 0


@dataclass
class EditorState:
    text: str
    cursor: int


class DayLogApp:
    def __init__(self, document: Document, path: Path) -> None:
        self.document = document
        self.path = path
        self.selected_index = 0
        self.message = "DayLog 已載入，按 / 輸入指令，按 q 離開。"
        self.running = True
        self._last_frame_line_count = 0
        self._stdout_handle = None
        self._original_stdout_handle = None
        self._owns_console_handle = False
        self._enable_virtual_terminal()

    def run(self) -> int:
        self._hide_cursor()
        try:
            while self.running:
                visible = self._visible_rows()
                if not visible:
                    self.selected_index = 0
                    visible = self._visible_rows()
                self.selected_index = max(0, min(self.selected_index, len(visible) - 1))
                self._render(visible)
                key = self._read_key()
                self._handle_key(key, visible)
            return 0
        finally:
            self._move_cursor_to(0, self._last_frame_line_count)
            self._show_cursor()
            if not self._owns_console_handle:
                self._write("\x1b[0m\n")
            self._close_console_handle()

    def _visible_rows(self) -> List[VisibleRow]:
        rows: List[VisibleRow] = []
        for section in SECTION_ORDER:
            section_items = self.document.sections.get(section, [])
            rows.append(VisibleRow(row_type="section", section=section))
            self._append_items(rows, section_items, section, section_items, None, 0)
        return rows

    def _append_items(
        self,
        rows: List[VisibleRow],
        items: List[Item],
        section: str,
        parent_list: List[Item],
        parent_item: Optional[Item],
        depth: int,
    ) -> None:
        for item in items:
            rows.append(VisibleRow("item", section, item, parent_list, parent_item, depth))
            if item.children and not item.collapsed:
                self._append_items(rows, item.children, section, item.children, item, depth + 1)

    def _render(self, visible: List[VisibleRow]) -> None:
        width, height = get_terminal_size((100, 32))
        usable_width = max(20, width - 1)
        body_height = max(8, height - 5)
        start = max(0, self.selected_index - body_height + 3)
        end = min(len(visible), start + body_height)
        separator = "-" * min(usable_width, 100)
        frame_lines = [f"DayLog  {self.document.date_text}"[:usable_width].ljust(usable_width), separator.ljust(usable_width)]
        for offset, row in enumerate(visible[start:end], start=start):
            pointer = ">" if offset == self.selected_index else " "
            line = f"{pointer} {self._format_row(row, usable_width - 2)}"
            frame_lines.append(line[:usable_width].ljust(usable_width))
        frame_lines.append(separator.ljust(usable_width))
        frame_lines.append(self._shortcuts_line(usable_width)[:usable_width].ljust(usable_width))
        frame_lines.append(self.message[:usable_width].ljust(usable_width))

        while len(frame_lines) < self._last_frame_line_count:
            frame_lines.append(" " * usable_width)

        self._draw_frame_lines(frame_lines, usable_width)
        self._last_frame_line_count = len(frame_lines)

    def _format_row(self, row: VisibleRow, width: int) -> str:
        if row.row_type == "section":
            return f"[{row.section}]"[:width]

        assert row.item is not None
        indent = "  " * row.depth
        branch = ">" if row.item.children and row.item.collapsed else "v" if row.item.children else " "
        if row.item.kind == "task":
            text = f"{indent}{branch} [{row.item.status or TASK_OPEN}] {row.item.text}"
        elif row.item.kind == "note":
            text = f"{indent}{branch} - {row.item.text}"
        else:
            text = f"{indent}{branch} {row.item.raw or row.item.text}"
        return text[:width]

    def _handle_key(self, key: str, visible: List[VisibleRow]) -> None:
        if key == "UP":
            self.selected_index = max(0, self.selected_index - 1)
        elif key == "DOWN":
            self.selected_index = min(len(visible) - 1, self.selected_index + 1)
        elif key in {"J", "j"}:
            self._move_current(visible, -1)
        elif key in {"K", "k"}:
            self._move_current(visible, 1)
        elif key == "LEFT":
            self._set_collapsed(visible, True)
        elif key == "RIGHT":
            self._set_collapsed(visible, False)
        elif key == "TAB":
            self._indent_current(visible)
        elif key in {"SHIFT_TAB", "b"}:
            self._outdent_current(visible)
        elif key == "SPACE":
            self._toggle_done(visible)
        elif key == "c":
            self._toggle_cancel(visible)
        elif key == "a":
            self._add_task(visible, child=False)
        elif key == "A":
            self._add_task(visible, child=True)
        elif key == "n":
            self._add_note(visible)
        elif key == "e":
            self._edit_current_text(visible)
        elif key == "d":
            self._delete_current(visible)
        elif key == "/":
            self._run_command_prompt(visible)
        elif key.lower() == "q":
            self.running = False

    def _set_collapsed(self, visible: List[VisibleRow], collapsed: bool) -> None:
        row = visible[self.selected_index]
        if row.item and row.item.children:
            row.item.collapsed = collapsed
            self._persist("已收合" if collapsed else "已展開")

    def _toggle_done(self, visible: List[VisibleRow]) -> None:
        row = visible[self.selected_index]
        if not row.item or not row.item.is_task():
            return
        row.item.status = TASK_DONE if row.item.status != TASK_DONE else TASK_OPEN
        self._persist("已切換完成狀態")

    def _toggle_cancel(self, visible: List[VisibleRow]) -> None:
        row = visible[self.selected_index]
        if not row.item or not row.item.is_task():
            return
        row.item.status = TASK_CANCELED if row.item.status != TASK_CANCELED else TASK_OPEN
        self._persist("已切換取消狀態")

    def _add_task(self, visible: List[VisibleRow], child: bool) -> None:
        row = visible[self.selected_index]
        text = self._prompt("子任務內容: " if child else "任務內容: ")
        if not text:
            self.message = "已取消新增"
            return
        new_item = Item(kind="task", text=text, status=TASK_OPEN)
        if row.row_type == "section":
            self.document.sections[row.section].append(new_item)
        elif child and row.item is not None:
            row.item.children.append(new_item)
            row.item.collapsed = False
        elif row.parent_list is not None and row.item is not None:
            row.parent_list.insert(row.parent_list.index(row.item) + 1, new_item)
        self._persist("已新增任務")

    def _add_note(self, visible: List[VisibleRow]) -> None:
        row = visible[self.selected_index]
        text = self._prompt("筆記內容: ")
        if not text:
            self.message = "已取消新增"
            return
        note = Item(kind="note", text=expand_note_macro(text))
        if row.row_type == "section":
            self.document.sections[row.section].append(note)
        elif row.item is not None and row.item.is_task():
            row.item.children.append(note)
            row.item.collapsed = False
        elif row.item is not None and row.item.is_note():
            row.item.children.append(note)
            row.item.collapsed = False
        elif row.parent_list is not None and row.item is not None:
            row.parent_list.insert(row.parent_list.index(row.item) + 1, note)
        self._persist("已新增筆記")

    def _delete_current(self, visible: List[VisibleRow]) -> None:
        row = visible[self.selected_index]
        if row.row_type == "section" or row.parent_list is None or row.item is None:
            self.message = "區塊標題不能刪除"
            return
        row.parent_list.remove(row.item)
        self.selected_index = max(0, self.selected_index - 1)
        self._persist("已刪除")

    def _move_current(self, visible: List[VisibleRow], direction: int) -> None:
        row = visible[self.selected_index]
        if row.row_type == "section" or row.parent_list is None or row.item is None:
            self.message = "此列不能搬移"
            return
        siblings = row.parent_list
        index = siblings.index(row.item)
        target_index = index + direction
        if target_index < 0 or target_index >= len(siblings):
            self.message = "已到同層邊界"
            return
        siblings[index], siblings[target_index] = siblings[target_index], siblings[index]
        self._persist("已調整順序")
        refreshed = self._visible_rows()
        for new_index, candidate in enumerate(refreshed):
            if candidate.item is row.item and candidate.section == row.section:
                self.selected_index = new_index
                break

    def _edit_current_text(self, visible: List[VisibleRow]) -> None:
        row = visible[self.selected_index]
        if row.row_type == "section" or row.item is None or row.item.kind not in {"task", "note"}:
            self.message = "請先選取任務或筆記再編輯"
            return
        edited = self._line_editor("編輯", row.item.text)
        if edited is None:
            self.message = "已取消編輯"
            return
        row.item.text = edited
        self._persist("已更新文字")

    def _indent_current(self, visible: List[VisibleRow]) -> None:
        row = visible[self.selected_index]
        if row.row_type == "section" or row.parent_list is None or row.item is None:
            return
        index = row.parent_list.index(row.item)
        if index == 0:
            self.message = "第一個項目不能再縮排"
            return
        previous = row.parent_list[index - 1]
        row.parent_list.pop(index)
        previous.children.append(row.item)
        previous.collapsed = False
        self._persist("已增加縮排")

    def _outdent_current(self, visible: List[VisibleRow]) -> None:
        row = visible[self.selected_index]
        if row.row_type == "section" or row.parent_list is None or row.item is None or row.parent_item is None:
            self.message = "已在最外層"
            return
        container = self._find_container_for(row.parent_item, row.section)
        if container is None:
            self.message = "無法減少縮排"
            return
        row.parent_list.remove(row.item)
        container.insert(container.index(row.parent_item) + 1, row.item)
        self._persist("已減少縮排")

    def _find_container_for(self, target: Item, section: str) -> Optional[List[Item]]:
        def walk(items: List[Item]) -> Optional[List[Item]]:
            for item in items:
                if item is target:
                    return items
                found = walk(item.children)
                if found is not None:
                    return found
            return None

        return walk(self.document.sections[section])

    def _run_command_prompt(self, visible: List[VisibleRow]) -> None:
        row = visible[self.selected_index]
        command = self._prompt("指令: /", initial="/")
        if not command:
            self.message = "已取消指令"
            return
        try:
            self.message = apply_command(self.document, command, row.section, target_item=row.item)
            self._persist(self.message)
        except ValueError as exc:
            self.message = str(exc)

    def _prompt(self, label: str, initial: str = "") -> str:
        result = self._line_editor(label.rstrip(": "), initial)
        return "" if result is None else result.strip()

    def _line_editor(self, label: str, initial: str = "") -> Optional[str]:
        state = EditorState(text=initial, cursor=len(initial))
        while True:
            self.message = self._render_editor_message(label, state)
            self._render(self._visible_rows())
            key = self._read_key()
            if key == "ENTER":
                return state.text
            if key == "ESC":
                return None
            state = apply_editor_key(state, key)
            if state is None:
                continue

    def _render_editor_message(self, label: str, state: EditorState) -> str:
        cursor = max(0, min(state.cursor, len(state.text)))
        preview = state.text[:cursor] + "|" + state.text[cursor:]
        return f"{label}: {preview}  Enter 儲存 Esc 取消"

    def _persist(self, message: str) -> None:
        save_document(self.path, self.document)
        self.message = message

    def _shortcuts_line(self, width: int) -> str:
        text = "Up/Down 移動  J 上移/K 下移  Tab 縮排  b/Shift+Tab 取消縮排  a/A 任務  n 筆記  e 編輯  d 刪除  Space 完成  c 取消  <-/-> 收合  / 指令  q 離開"
        return text[:width]

    def _read_key(self, raw: bool = False) -> str:
        ch = msvcrt.getwch()
        if raw:
            return ch
        if ch == "\x1b":
            escape_key = self._read_escape_sequence()
            if escape_key is not None:
                return escape_key
            return "ESC"
        if ch in ("\x00", "\xe0"):
            code = msvcrt.getwch()
            return {
                "H": "UP",
                "P": "DOWN",
                "K": "LEFT",
                "M": "RIGHT",
                "S": "DELETE",
                "G": "HOME",
                "O": "END",
                "\x0f": "SHIFT_TAB",
            }.get(code, code)
        if ch == "\t":
            return "TAB"
        if ch == " ":
            return "SPACE"
        if ch in ("\r", "\n"):
            return "ENTER"
        if ch in ("\b", "\x7f"):
            return "BACKSPACE"
        return ch

    def _read_escape_sequence(self) -> Optional[str]:
        if not msvcrt.kbhit():
            return None
        second = msvcrt.getwch()
        if second != "[":
            return None
        third = self._read_escape_char()
        if third is None:
            return None
        if third == "Z":
            return "SHIFT_TAB"
        if third == "A":
            return "UP"
        if third == "B":
            return "DOWN"
        if third == "C":
            return "RIGHT"
        if third == "D":
            return "LEFT"
        if third == "H":
            return "HOME"
        if third == "F":
            return "END"
        if third == "1":
            fourth = self._read_escape_char()
            fifth = self._read_escape_char()
            sixth = self._read_escape_char()
            if fourth == ";" and fifth == "3":
                if sixth == "A":
                    return "ALT_UP"
                if sixth == "B":
                    return "ALT_DOWN"
        return None

    def _read_escape_char(self) -> Optional[str]:
        if not msvcrt.kbhit():
            return None
        return msvcrt.getwch()

    def _enable_virtual_terminal(self) -> None:
        try:
            self._original_stdout_handle = ctypes.windll.kernel32.GetStdHandle(-11)
            handle = ctypes.windll.kernel32.CreateConsoleScreenBuffer(
                GENERIC_READ | GENERIC_WRITE,
                FILE_SHARE_READ | FILE_SHARE_WRITE,
                None,
                CONSOLE_TEXTMODE_BUFFER,
                None,
            )
            if handle == INVALID_HANDLE_VALUE:
                handle = ctypes.windll.kernel32.CreateFileW(
                    "CONOUT$",
                    GENERIC_READ | GENERIC_WRITE,
                    FILE_SHARE_READ | FILE_SHARE_WRITE,
                    None,
                    OPEN_EXISTING,
                    0,
                    None,
                )
            else:
                ctypes.windll.kernel32.SetConsoleActiveScreenBuffer(handle)
                self._owns_console_handle = True
            if handle == INVALID_HANDLE_VALUE:
                handle = ctypes.windll.kernel32.CreateFileW(
                    "CONOUT$",
                    GENERIC_READ | GENERIC_WRITE,
                    FILE_SHARE_READ | FILE_SHARE_WRITE,
                    None,
                    OPEN_EXISTING,
                    0,
                    None,
                )
            if handle == INVALID_HANDLE_VALUE:
                handle = self._original_stdout_handle
            elif not self._owns_console_handle:
                self._owns_console_handle = True
            self._stdout_handle = handle
            mode = ctypes.c_uint()
            if ctypes.windll.kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
                ctypes.windll.kernel32.SetConsoleMode(handle, mode.value | 0x0004)
                self._clear_console()
        except OSError:
            pass

    def _write(self, text: str) -> None:
        sys.stdout.write(text)
        sys.stdout.flush()

    def _move_cursor_home(self) -> None:
        self._move_cursor_to(0, 0)

    def _move_cursor_to(self, x: int, y: int) -> None:
        if self._stdout_handle is not None:
            ctypes.windll.kernel32.SetConsoleCursorPosition(self._stdout_handle, COORD(x, y))
            return
        self._write(f"\x1b[{y + 1};{x + 1}H")

    def _draw_frame_lines(self, frame_lines: List[str], width: int) -> None:
        if self._stdout_handle is not None:
            for index, line in enumerate(frame_lines):
                self._write_line_at(index, line[:width].ljust(width))
            return
        self._move_cursor_home()
        self._write("\n".join(frame_lines))

    def _write_line_at(self, y: int, text: str) -> None:
        self._move_cursor_to(0, y)
        written = DWORD(0)
        ctypes.windll.kernel32.WriteConsoleW(
            self._stdout_handle,
            ctypes.c_wchar_p(text),
            len(text),
            ctypes.byref(written),
            None,
        )

    def _show_cursor(self) -> None:
        if self._stdout_handle is None:
            self._write("\x1b[?25h")
            return
        info = CONSOLE_CURSOR_INFO()
        if ctypes.windll.kernel32.GetConsoleCursorInfo(self._stdout_handle, ctypes.byref(info)):
            info.bVisible = 1
            ctypes.windll.kernel32.SetConsoleCursorInfo(self._stdout_handle, ctypes.byref(info))

    def _hide_cursor(self) -> None:
        if self._stdout_handle is None:
            self._write("\x1b[?25l")
            return
        info = CONSOLE_CURSOR_INFO()
        if ctypes.windll.kernel32.GetConsoleCursorInfo(self._stdout_handle, ctypes.byref(info)):
            info.bVisible = 0
            ctypes.windll.kernel32.SetConsoleCursorInfo(self._stdout_handle, ctypes.byref(info))

    def _clear_console(self) -> None:
        if self._stdout_handle is None:
            return
        width, height = get_terminal_size((100, 32))
        blank = " " * max(1, width - 1)
        for row in range(height):
            self._write_line_at(row, blank)
        self._move_cursor_home()

    def _close_console_handle(self) -> None:
        if self._owns_console_handle and self._original_stdout_handle not in {None, INVALID_HANDLE_VALUE}:
            ctypes.windll.kernel32.SetConsoleActiveScreenBuffer(self._original_stdout_handle)
        if self._owns_console_handle and self._stdout_handle not in {None, INVALID_HANDLE_VALUE, self._original_stdout_handle}:
            ctypes.windll.kernel32.CloseHandle(self._stdout_handle)
        self._stdout_handle = None
        self._original_stdout_handle = None
        self._owns_console_handle = False


def apply_editor_key(state: EditorState, key: str) -> EditorState:
    if key == "LEFT":
        state.cursor = max(0, state.cursor - 1)
        return state
    if key == "RIGHT":
        state.cursor = min(len(state.text), state.cursor + 1)
        return state
    if key == "HOME":
        state.cursor = 0
        return state
    if key == "END":
        state.cursor = len(state.text)
        return state
    if key == "BACKSPACE":
        if state.cursor > 0:
            state.text = state.text[: state.cursor - 1] + state.text[state.cursor :]
            state.cursor -= 1
        return state
    if key == "DELETE":
        if state.cursor < len(state.text):
            state.text = state.text[: state.cursor] + state.text[state.cursor + 1 :]
        return state
    if len(key) == 1 and key.isprintable() and key != "\t":
        state.text = state.text[: state.cursor] + key + state.text[state.cursor :]
        state.cursor += 1
    return state
