from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.models import Item, SECTION_TODAY, TASK_OPEN


@dataclass
class CommandResult:
    kind: str
    payload: str


def run_command(command: str, now: datetime | None = None) -> CommandResult:
    current = now or datetime.now()
    text = command.strip()
    if text.startswith("/todo "):
        content = text[6:].strip()
        if not content:
            raise ValueError("/todo 需要內容")
        return CommandResult(kind="todo", payload=content)
    if text == "/date":
        return CommandResult(kind="note", payload=current.strftime("%Y-%m-%d"))
    if text == "/time":
        return CommandResult(kind="note", payload=current.strftime("%H:%M"))
    raise ValueError(f"未知指令: {command}")


def apply_command(doc, command: str, selected_section: str, now: datetime | None = None) -> str:
    result = run_command(command, now=now)
    if result.kind == "todo":
        doc.sections[SECTION_TODAY].append(Item(kind="task", text=result.payload, status=TASK_OPEN))
        return "已新增待辦到今日臨時任務"
    doc.sections[selected_section].append(Item(kind="note", text=result.payload))
    return f"已插入 {result.payload}"
