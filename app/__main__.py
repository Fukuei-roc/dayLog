from __future__ import annotations

from datetime import date
from pathlib import Path

from app.storage import load_or_create_today
from app.tui import DayLogApp


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    doc, path = load_or_create_today(root, date.today())
    app = DayLogApp(doc, path)
    return app.run()


if __name__ == "__main__":
    raise SystemExit(main())
