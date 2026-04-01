from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.models import Item, SECTION_TEMPORARY, TASK_OPEN


@dataclass
class CommandResult:
    kind: str
    payload: str


def run_command(command: str, now: datetime | None = None) -> CommandResult:
    text = _normalize_command(command)
    if text.startswith("/todo "):
        content = text[6:].strip()
        if not content:
            raise ValueError("/todo 需要內容")
        return CommandResult(kind="todo", payload=content)
    raise ValueError(f"未知指令: {command}")


def apply_command(doc, command: str, selected_section: str, target_item: Item | None = None, now: datetime | None = None) -> str:
    result = run_command(command, now=now)
    if result.kind == "todo":
        doc.sections[SECTION_TEMPORARY].append(Item(kind="task", text=result.payload, status=TASK_OPEN))
        return "已新增待辦到臨時任務"
    note = Item(kind="note", text=result.payload)
    if target_item is not None and target_item.kind in {"task", "note"}:
        target_item.children.append(note)
        target_item.collapsed = False
    else:
        doc.sections[selected_section].append(note)
    return f"已插入 {result.payload}"


def _normalize_command(command: str) -> str:
    text = command.strip()
    if not text:
        return text
    stripped = text.lstrip("/")
    if stripped.startswith("todo "):
        return f"/{stripped}"
    return text


def expand_note_macro(text: str, now: datetime | None = None) -> str:
    current = now or datetime.now()
    stripped = text.strip()
    for macro, rendered in {
        "/date": current.strftime("%Y-%m-%d"),
        "/time": current.strftime("%H:%M"),
    }.items():
        if stripped == macro:
            return rendered
        if stripped.startswith(macro):
            suffix = stripped[len(macro) :].strip()
            return f"{rendered} {suffix}" if suffix else rendered
    return text
