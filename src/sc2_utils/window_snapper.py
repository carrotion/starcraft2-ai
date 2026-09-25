"""Utility to automatically snap the StarCraft II window to the left half of the screen."""

import ctypes
from ctypes import wintypes
import threading
import time

user32 = ctypes.windll.user32


def snap_sc2_window(x: int = 0, y: int = 0, width: int = 960, height: int = 1040):
    """Finds StarCraft II window and moves it to (x, y, width, height) without stealing focus."""
    hwnd = user32.FindWindowW(None, "StarCraft II")
    if hwnd:
        user32.MoveWindow(hwnd, x, y, width, height, True)
        return True
    return False


def start_window_snapper_thread(x: int = 0, y: int = 0, width: int = 960, height: int = 1040):
    """Starts a daemon thread that waits for the SC2 window to appear and snaps it to the left side."""

    def worker():
        for _ in range(60):  # Try for up to 60 seconds
            if snap_sc2_window(x, y, width, height):
                print(f"[화면 배치 완료] 스타크래프트 2 창을 화면 좌측 ({width}x{height})에 배치했습니다.")
                return
            time.sleep(1.0)

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    return t
