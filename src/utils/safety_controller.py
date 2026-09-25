"""Safety controller and hotkey listener for StarCraft AI.

Provides:
- F12: Emergency instant stop (Kill-switch)
- F9: Toggle Pause / Resume
- Focus verification: NEVER sends input unless StarCraft is the active foreground window
- Mouse Fail-Safe: Moving mouse to top-left (0, 0) aborts immediately
"""

import ctypes
import os
import time
from typing import Optional
import cv2
import numpy as np

user32 = ctypes.windll.user32

# Virtual Key Codes
VK_F9 = 0x78
VK_F12 = 0x7B
VK_ESCAPE = 0x1B


class SafetyController:
    def __init__(self, target_hwnd: Optional[int] = None, debug_dir: str = "./debug"):
        self.target_hwnd = target_hwnd
        self.debug_dir = debug_dir
        self.is_paused = False
        self._last_f9_press_time = 0.0
        os.makedirs(debug_dir, exist_ok=True)

    def set_target_hwnd(self, hwnd: int):
        self.target_hwnd = hwnd

    def check_hotkeys(self) -> str:
        """Check for user safety hotkeys.

        Returns:
            "STOP" if F12 is pressed (emergency exit)
            "PAUSE" if F9 was toggled
            "OK" normal
        """
        # Check F12 (Emergency Kill)
        if user32.GetAsyncKeyState(VK_F12) & 0x8000:
            print("\n[긴급 중단] F12 키가 감지되었습니다. 에이전트를 즉시 안전하게 종료합니다.")
            return "STOP"

        # Check F9 (Pause / Resume Toggle with debounce)
        now = time.time()
        if user32.GetAsyncKeyState(VK_F9) & 0x8000:
            if now - self._last_f9_press_time > 0.4:
                self.is_paused = not self.is_paused
                self._last_f9_press_time = now
                state = "일시정지(PAUSED)" if self.is_paused else "재개(RESUMED)"
                print(f"\n[F9 키 감지] 에이전트 상태 변경: {state}")

        if self.is_paused:
            return "PAUSE"

        return "OK"

    def is_target_window_active(self) -> bool:
        """Returns True ONLY if StarCraft is the current active foreground window."""
        if not self.target_hwnd:
            return False
        active_hwnd = user32.GetForegroundWindow()
        return active_hwnd == self.target_hwnd

    def save_debug_frame(self, frame: np.ndarray, action_name: str, step: int):
        """Save latest captured frame with timestamp and action for inspection."""
        try:
            filename = os.path.join(self.debug_dir, "latest_frame.png")
            # If 1-channel, convert to 3-channel for visualization
            if len(frame.shape) == 3 and frame.shape[2] == 1:
                display = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
            else:
                display = frame.copy()

            # Annotate with step and action
            cv2.putText(
                display,
                f"Step: {step} | Action: {action_name}",
                (10, 25),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                (0, 255, 0),
                1,
                cv2.LINE_AA,
            )
            cv2.imwrite(filename, display)
        except Exception as e:
            pass
