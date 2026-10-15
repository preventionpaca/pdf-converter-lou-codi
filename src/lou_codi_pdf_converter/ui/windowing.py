from __future__ import annotations

import tkinter as tk


def maximize_window(window: tk.Tk | tk.Toplevel) -> None:
    """Use the largest practical window supported by the current desktop."""

    def apply() -> None:
        try:
            window.state("zoomed")
            return
        except tk.TclError:
            pass
        width = max(850, window.winfo_screenwidth() - 32)
        height = max(600, window.winfo_screenheight() - 80)
        window.geometry(f"{width}x{height}+0+0")

    window.after_idle(apply)

