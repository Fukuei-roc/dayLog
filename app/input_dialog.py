from __future__ import annotations

import json
import sys
import tkinter as tk


def show_dialog(label: str, initial: str) -> str | None:
    result = {"value": None}
    bg_main = "#333333"
    bg_input = "#454545"
    border = "#5b5b5b"
    fg_main = "#f5f5f5"
    fg_muted = "#d0d0d0"

    root = tk.Tk()
    root.title(label)
    root.configure(bg=bg_main)
    root.attributes("-topmost", True)
    root.resizable(False, False)
    root.overrideredirect(True)

    screen_width = root.winfo_screenwidth()
    screen_height = root.winfo_screenheight()
    width = max(520, int(screen_width * 0.34))
    height = max(180, int(screen_height * 0.22))
    left = max(0, (screen_width - width) // 2)
    top = max(0, (screen_height - height) // 2)
    root.geometry(f"{width}x{height}+{left}+{top}")

    outer = tk.Frame(root, bg=bg_main, padx=24, pady=20, highlightbackground=border, highlightthickness=1)
    outer.pack(fill="both", expand=True)

    titlebar = tk.Frame(outer, bg=border, height=34)
    titlebar.pack(fill="x", pady=(0, 16))

    title_label = tk.Label(
        titlebar,
        text=label,
        bg=border,
        fg=fg_main,
        font=("Consolas", 11, "bold"),
        anchor="w",
    )
    title_label.pack(side="left", padx=(10, 0), pady=6)

    def cancel(event=None):
        result["value"] = None
        root.destroy()

    close_button = tk.Button(
        titlebar,
        text="×",
        command=cancel,
        bg=border,
        fg=fg_main,
        activebackground="#707070",
        activeforeground="#ffffff",
        relief="flat",
        bd=0,
        padx=10,
        pady=2,
        font=("Consolas", 12, "bold"),
    )
    close_button.pack(side="right", padx=(0, 6), pady=2)

    drag_state = {"x": 0, "y": 0}

    def start_drag(event):
        drag_state["x"] = event.x_root - root.winfo_x()
        drag_state["y"] = event.y_root - root.winfo_y()

    def on_drag(event):
        x = event.x_root - drag_state["x"]
        y = event.y_root - drag_state["y"]
        root.geometry(f"{width}x{height}+{x}+{y}")

    titlebar.bind("<ButtonPress-1>", start_drag)
    titlebar.bind("<B1-Motion>", on_drag)
    title_label.bind("<ButtonPress-1>", start_drag)
    title_label.bind("<B1-Motion>", on_drag)

    entry = tk.Entry(
        outer,
        bg=bg_input,
        fg=fg_main,
        insertbackground=fg_main,
        relief="flat",
        font=("Consolas", 14),
        bd=0,
    )
    entry.pack(fill="x", ipady=10)
    entry.insert(0, initial)
    entry.selection_range(0, "end")

    hint = tk.Label(
        outer,
        text="Enter 儲存   Esc 取消",
        bg=bg_main,
        fg=fg_muted,
        font=("Consolas", 11),
        anchor="w",
    )
    hint.pack(fill="x", pady=(12, 0))

    buttons = tk.Frame(outer, bg=bg_main)
    buttons.pack(fill="x", pady=(16, 0))

    def submit(event=None):
        result["value"] = entry.get()
        root.destroy()

    cancel_button = tk.Button(
        buttons,
        text="取消",
        command=cancel,
        bg="#4a4a4a",
        fg=fg_main,
        activebackground="#5a5a5a",
        activeforeground="#ffffff",
        relief="flat",
        padx=16,
        pady=6,
    )
    cancel_button.pack(side="right")

    submit_button = tk.Button(
        buttons,
        text="確定",
        command=submit,
        bg="#d9d9d9",
        fg="#202020",
        activebackground="#ededed",
        activeforeground="#101010",
        relief="flat",
        padx=16,
        pady=6,
    )
    submit_button.pack(side="right", padx=(0, 10))

    root.bind("<Return>", submit)
    root.bind("<Escape>", cancel)
    root.protocol("WM_DELETE_WINDOW", cancel)
    root.after(0, lambda: (root.lift(), root.focus_force(), entry.focus_force()))
    root.mainloop()
    return result["value"]


def main() -> int:
    label = sys.argv[1] if len(sys.argv) > 1 else "輸入"
    initial = sys.argv[2] if len(sys.argv) > 2 else ""
    value = show_dialog(label, initial)
    sys.stdout.write(json.dumps({"value": value}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
