from __future__ import annotations

import signal
import subprocess
import sys
import threading

from .capture_bridge import CaptureBridge


def launch_workshop(_space_id: str = "") -> None:
    subprocess.Popen(
        [sys.executable, "-m", "lou_codi_pdf_converter.app"],
        close_fds=True,
        start_new_session=True,
    )


def main() -> int:
    stopped = threading.Event()
    bridge = CaptureBridge(on_open=launch_workshop)

    def stop(_signum: int, _frame: object) -> None:
        stopped.set()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        while not stopped.is_set() and not bridge.start():
            stopped.wait(2)
        if stopped.is_set():
            return 0
        stopped.wait()
    finally:
        bridge.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
