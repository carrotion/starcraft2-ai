"""Window management utility for StarCraft on Windows."""

import ctypes
from ctypes import wintypes
import time
from typing import Optional, Tuple

user32 = ctypes.windll.user32


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    ]


def find_starcraft_window(title_keywords=("StarCraft", "Brood War")) -> Optional[int]:
    """Find the HWND of a window matching StarCraft titles."""
    found_hwnd = None

    def enum_windows_proc(hwnd, lParam):
        nonlocal found_hwnd
        if user32.IsWindowVisible(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            if length > 0:
                buff = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buff, length + 1)
                title = buff.value
                for kw in title_keywords:
                    if kw.lower() in title.lower():
                        found_hwnd = hwnd
                        return False
        return True

    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows(WNDENUMPROC(enum_windows_proc), 0)
    return found_hwnd


def get_window_rect(hwnd: int) -> Optional[Tuple[int, int, int, int]]:
    """Return (left, top, width, height) of the window client or frame area."""
    if not hwnd:
        return None
    rect = RECT()
    if user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        width = rect.right - rect.left
        height = rect.bottom - rect.top
        return (rect.left, rect.top, width, height)
    return None


def focus_window(hwnd: int) -> bool:
    """Bring the window to the foreground."""
    if not hwnd:
        return False
    user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.1)
    return True
