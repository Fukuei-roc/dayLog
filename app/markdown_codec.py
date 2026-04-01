from __future__ import annotations

import re
from datetime import date
from typing import List, Sequence, Tuple

from app.models import Document, Item, SECTION_ORDER, TASK_CANCELED, TASK_DONE, TASK_OPEN


TASK_PATTERN = re.compile(r"^(?P<indent>\s*)- \[(?P<status>[ x-])\] (?P<text>.*)$")
NOTE_PATTERN = re.compile(r"^(?P<indent>\s*)- (?P<text>.*)$")
HEADER_PATTERN = re.compile(r"^# (?P<date>\d{4}-\d{2}-\d{2})\s*$")
SECTION_PATTERN = re.compile(r"^## (?P<section>.+?)\s*$")
INDENT_WIDTH = 2


def create_empty_document(day: date) -> Document:
    return Document(date_text=day.isoformat())


def normalize_document(doc: Document, fallback_date: date | None = None) -> Document:
    if not HEADER_PATTERN.match(f"# {doc.date_text}") and fallback_date is not None:
        doc.date_text = fallback_date.isoformat()
    for section in SECTION_ORDER:
        doc.sections.setdefault(section, [])
    return doc


def parse_markdown(content: str, fallback_date: date | None = None) -> Document:
    fallback = fallback_date.isoformat() if fallback_date else "1970-01-01"
    doc = Document(date_text=fallback)
    current_section = None
    extras: List[Tuple[str, List[str]]] = []
    extra_name = None
    extra_lines: List[str] = []

    for raw_line in content.splitlines():
        header_match = HEADER_PATTERN.match(raw_line)
        if header_match:
            doc.date_text = header_match.group("date")
            continue

        section_match = SECTION_PATTERN.match(raw_line)
        if section_match:
            if extra_name is not None:
                extras.append((extra_name, extra_lines))
                extra_name, extra_lines = None, []

            section_name = section_match.group("section")
            if section_name in SECTION_ORDER:
                current_section = section_name
            else:
                current_section = None
                extra_name = section_name
            continue

        if extra_name is not None:
            extra_lines.append(raw_line)
            continue

        if current_section is None:
            doc.preamble_lines.append(raw_line)
            continue

        if raw_line == "":
            continue

        doc.sections[current_section].append(_parse_line_to_item(raw_line))

    if extra_name is not None:
        extras.append((extra_name, extra_lines))

    for section_name, lines in list(doc.sections.items()):
        doc.sections[section_name] = _build_tree(lines)

    doc.extra_sections = extras
    return normalize_document(doc, fallback_date)


def serialize_document(doc: Document) -> str:
    lines = [f"# {doc.date_text}"]
    if doc.preamble_lines:
        lines.extend(doc.preamble_lines)

    for section in SECTION_ORDER:
        lines.append("")
        lines.append(f"## {section}")
        lines.extend(_serialize_items(doc.sections.get(section, []), 0))

    for title, extra_lines in doc.extra_sections:
        lines.append("")
        lines.append(f"## {title}")
        lines.extend(extra_lines)

    return "\n".join(lines).rstrip() + "\n"


def clone_unfinished_tasks(items: Sequence[Item]) -> List[Item]:
    carried: List[Item] = []
    for item in items:
        if not item.is_task() or item.status != TASK_OPEN:
            continue
        carried_item = item.clone()
        carried_item.children = _filter_children_for_carry(item.children)
        carried.append(carried_item)
    return carried


def _filter_children_for_carry(items: Sequence[Item]) -> List[Item]:
    result: List[Item] = []
    for item in items:
        if item.is_task():
            if item.status == TASK_OPEN:
                clone = item.clone()
                clone.children = _filter_children_for_carry(item.children)
                result.append(clone)
        else:
            clone = item.clone()
            clone.children = _filter_children_for_carry(item.children)
            result.append(clone)
    return result


def _parse_line_to_item(raw_line: str) -> Item:
    task_match = TASK_PATTERN.match(raw_line)
    if task_match:
        return Item(kind="task", text=task_match.group("text"), status=task_match.group("status"), raw=task_match.group("indent"))

    note_match = NOTE_PATTERN.match(raw_line)
    if note_match:
        return Item(kind="note", text=note_match.group("text"), raw=note_match.group("indent"))

    if raw_line.strip():
        return Item(kind="raw", text=raw_line.strip(), raw=raw_line)
    return Item(kind="raw", text="", raw=raw_line)


def _build_tree(flat_items: Sequence[Item]) -> List[Item]:
    root: List[Item] = []
    stack: List[Tuple[int, List[Item]]] = [(-1, root)]
    for item in flat_items:
        indent = _indent_for_item(item)
        while len(stack) > 1 and indent <= stack[-1][0]:
            stack.pop()
        stack[-1][1].append(item)
        stack.append((indent, item.children))
    return root


def _serialize_items(items: Sequence[Item], level: int) -> List[str]:
    lines: List[str] = []
    indent = " " * (level * INDENT_WIDTH)
    for item in items:
        if item.kind == "task":
            status = item.status or TASK_OPEN
            if status not in {TASK_OPEN, TASK_DONE, TASK_CANCELED}:
                status = TASK_OPEN
            lines.append(f"{indent}- [{status}] {item.text}".rstrip())
        elif item.kind == "note":
            lines.append(f"{indent}- {item.text}".rstrip())
        elif item.raw is not None:
            lines.append(item.raw)
        else:
            lines.append(item.text)
        lines.extend(_serialize_items(item.children, level + 1))
    return lines


def _indent_for_item(item: Item) -> int:
    if item.kind == "raw" and item.raw is not None:
        return len(item.raw) - len(item.raw.lstrip(" "))
    raw = item.raw or ""
    return len(raw.replace("\t", "  "))
