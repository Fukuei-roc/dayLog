from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


SECTION_ROUTINE = "每日例行任務"
SECTION_CARRY = "延續的臨時任務"
SECTION_TODAY = "今日臨時任務"
SECTION_ORDER = [SECTION_ROUTINE, SECTION_CARRY, SECTION_TODAY]
TASK_OPEN = " "
TASK_DONE = "x"
TASK_CANCELED = "-"


@dataclass
class Item:
    kind: str
    text: str
    status: Optional[str] = None
    children: List["Item"] = field(default_factory=list)
    collapsed: bool = False
    raw: Optional[str] = None

    def is_task(self) -> bool:
        return self.kind == "task"

    def is_note(self) -> bool:
        return self.kind == "note"

    def clone(self) -> "Item":
        return Item(
            kind=self.kind,
            text=self.text,
            status=self.status,
            children=[child.clone() for child in self.children],
            collapsed=self.collapsed,
            raw=self.raw,
        )


@dataclass
class Document:
    date_text: str
    sections: dict = field(default_factory=dict)
    preamble_lines: List[str] = field(default_factory=list)
    extra_sections: List[tuple] = field(default_factory=list)

    def __post_init__(self) -> None:
        for name in SECTION_ORDER:
            self.sections.setdefault(name, [])
