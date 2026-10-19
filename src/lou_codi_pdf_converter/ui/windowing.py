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


def center_window(window: tk.Tk | tk.Toplevel, width: int, height: int) -> None:
    """Center a non-workspace window at a comfortable fixed size."""

    if isinstance(window, tk.Toplevel):
        window.bind("<Escape>", lambda _event: window.destroy() or "break", add="+")

    def apply() -> None:
        screen_width = window.winfo_screenwidth()
        screen_height = window.winfo_screenheight()
        x = max(0, (screen_width - width) // 2)
        y = max(0, (screen_height - height) // 2)
        window.geometry(f"{width}x{height}+{x}+{y}")

    window.after_idle(apply)


def make_modal(window: tk.Toplevel, parent: tk.Misc) -> None:
    """Attach a visible workspace to its parent and block the parent reliably."""
    window.bind("<Escape>", lambda _event: window.destroy() or "break", add="+")
    window.transient(parent)
    try:
        window.wm_group(parent)
    except tk.TclError:
        pass
    window.update_idletasks()
    try:
        window.wait_visibility()
    except tk.TclError:
        return
    window.lift(parent)
    window.grab_set()
    window.focus_force()
