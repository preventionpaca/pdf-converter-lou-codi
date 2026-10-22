from __future__ import annotations

import re
import subprocess
import sys
import tkinter as tk


def _monitor_bounds(window: tk.Misc) -> tuple[int, int, int, int]:
    """Return the monitor containing the pointer instead of the virtual desktop."""
    pointer_x, pointer_y = window.winfo_pointerxy()
    if sys.platform.startswith("linux"):
        try:
            output = subprocess.run(
                ["xrandr", "--current", "--query"],
                check=False,
                capture_output=True,
                text=True,
                timeout=2,
            ).stdout
            monitors = [
                tuple(map(int, match.groups()))
                for match in re.finditer(r"\b(\d+)x(\d+)\+(-?\d+)\+(-?\d+)\b", output)
            ]
            for width, height, x, y in monitors:
                if x <= pointer_x < x + width and y <= pointer_y < y + height:
                    return x, y, width, height
            if monitors:
                width, height, x, y = monitors[0]
                return x, y, width, height
        except (OSError, subprocess.SubprocessError):
            pass
    return 0, 0, window.winfo_screenwidth(), window.winfo_screenheight()


def maximize_window(window: tk.Tk | tk.Toplevel) -> None:
    """Use the largest practical window supported by the current desktop."""

    def apply() -> None:
        x, y, monitor_width, monitor_height = _monitor_bounds(window)
        # Place the window on one monitor before asking the window manager to
        # maximize it. On X11, ``winfo_screenwidth`` is the full multi-monitor
        # desktop and previously produced a window spanning every display.
        width = max(850, monitor_width - 24)
        height = max(600, monitor_height - 72)
        window.geometry(f"{width}x{height}+{x}+{y}")
        if sys.platform != "linux":
            try:
                window.state("zoomed")
            except tk.TclError:
                pass

    apply()


def center_window(window: tk.Tk | tk.Toplevel, width: int, height: int) -> None:
    """Center a non-workspace window at a comfortable fixed size."""

    if isinstance(window, tk.Toplevel):
        window.bind("<Escape>", lambda _event: window.destroy() or "break", add="+")

    def apply() -> None:
        monitor_x, monitor_y, screen_width, screen_height = _monitor_bounds(window)
        actual_width = min(width, max(420, screen_width - 40))
        actual_height = min(height, max(260, screen_height - 80))
        x = monitor_x + max(0, (screen_width - actual_width) // 2)
        y = monitor_y + max(0, (screen_height - actual_height) // 2)
        window.geometry(f"{actual_width}x{actual_height}+{x}+{y}")

    window.after_idle(apply)


def fit_dialog(
    window: tk.Toplevel,
    *,
    minimum_width: int = 720,
    minimum_height: int = 340,
) -> None:
    """Size a dialog from its content while keeping it inside one monitor."""
    window.update_idletasks()
    monitor_x, monitor_y, screen_width, screen_height = _monitor_bounds(window)
    width = min(max(minimum_width, window.winfo_reqwidth() + 24), screen_width - 40)
    height = min(max(minimum_height, window.winfo_reqheight() + 24), screen_height - 80)
    x = monitor_x + max(0, (screen_width - width) // 2)
    y = monitor_y + max(0, (screen_height - height) // 2)
    window.minsize(min(minimum_width, width), min(minimum_height, height))
    window.geometry(f"{width}x{height}+{x}+{y}")


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
