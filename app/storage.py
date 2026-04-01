from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

from app.markdown_codec import clone_carried_tasks, create_empty_document, parse_markdown, serialize_document
from app.models import Document, Item, SECTION_ORDER, SECTION_ROUTINE, SECTION_TEMPORARY


@dataclass
class ProjectPaths:
    root: Path

    @property
    def data_daily(self) -> Path:
        return self.root / "data" / "daily"

    @property
    def template(self) -> Path:
        return self.root / "templates" / "dailyRoutine.md"

    def daily_file(self, day: date) -> Path:
        return self.data_daily / f"{day.isoformat()}.md"


def ensure_project_layout(root: Path) -> ProjectPaths:
    paths = ProjectPaths(root=root)
    paths.data_daily.mkdir(parents=True, exist_ok=True)
    paths.template.parent.mkdir(parents=True, exist_ok=True)
    if not paths.template.exists():
        paths.template.write_text("- [ ] 檢查今天的例行工作\n- [ ] 整理工作紀錄\n", encoding="utf-8")
    return paths


def load_or_create_today(root: Path, today: date) -> tuple[Document, Path]:
    paths = ensure_project_layout(root)
    target = paths.daily_file(today)
    if not target.exists():
        doc = build_new_daily_document(paths, today)
        save_document(target, doc)
        return doc, target

    doc = load_document(target, today)
    repaired = repair_document(doc, paths, today)
    save_document(target, repaired)
    return repaired, target


def load_document(path: Path, today: date | None = None) -> Document:
    fallback = today or date.today()
    try:
        content = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return create_empty_document(fallback)
    return parse_markdown(content, fallback)


def save_document(path: Path, doc: Document) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(serialize_document(doc), encoding="utf-8")


def repair_document(doc: Document, paths: ProjectPaths, today: date) -> Document:
    doc.date_text = today.isoformat()
    for section in SECTION_ORDER:
        doc.sections.setdefault(section, [])
    template_doc = parse_template(paths.template)
    if not doc.sections[SECTION_ROUTINE]:
        doc.sections[SECTION_ROUTINE] = [item.clone() for item in template_doc]
    return doc


def build_new_daily_document(paths: ProjectPaths, today: date) -> Document:
    doc = create_empty_document(today)
    doc.sections[SECTION_ROUTINE] = [item.clone() for item in parse_template(paths.template)]
    doc.sections[SECTION_TEMPORARY] = collect_carry_over(paths, today)
    return repair_document(doc, paths, today)


def collect_carry_over(paths: ProjectPaths, today: date) -> list[Item]:
    previous_path = find_previous_daily_file(paths, today)
    if previous_path is None:
        return []
    previous = load_document(previous_path)
    return clone_carried_tasks(previous.sections.get(SECTION_TEMPORARY, []))


def find_previous_daily_file(paths: ProjectPaths, today: date) -> Path | None:
    candidates = []
    for path in paths.data_daily.glob("*.md"):
        try:
            day = date.fromisoformat(path.stem)
        except ValueError:
            continue
        if day < today:
            candidates.append((day, path))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def parse_template(template_path: Path) -> list[Item]:
    try:
        template_text = template_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    fake_doc = parse_markdown(f"# 1970-01-01\n\n## {SECTION_ROUTINE}\n{template_text}\n", fallback_date=date(1970, 1, 1))
    return fake_doc.sections[SECTION_ROUTINE]
