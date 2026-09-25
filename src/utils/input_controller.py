"""Game input controller utilizing DirectInput for keyboard and mouse events."""

import time
from typing import Tuple
import pydirectinput

# Disable pydirectinput pause overhead for real-time responsiveness
pydirectinput.PAUSE = 0.01


class InputController:
    def __init__(self, window_offset: Tuple[int, int] = (0, 0)):
        self.offset_x, self.offset_y = window_offset

    def set_offset(self, offset: Tuple[int, int]):
        self.offset_x, self.offset_y = offset

    def click(self, x: int, y: int, button: str = "left"):
        target_x = self.offset_x + x
        target_y = self.offset_y + y
        pydirectinput.click(x=target_x, y=target_y, button=button)

    def right_click(self, x: int, y: int):
        self.click(x, y, button="right")

    def press_key(self, key: str, duration: float = 0.05):
        pydirectinput.keyDown(key)
        time.sleep(duration)
        pydirectinput.keyUp(key)

    def select_box(self, x1: int, y1: int, x2: int, y2: int):
        """Perform click-and-drag selection box."""
        tx1, ty1 = self.offset_x + x1, self.offset_y + y1
        tx2, ty2 = self.offset_x + x2, self.offset_y + y2
        pydirectinput.moveTo(tx1, ty1)
        pydirectinput.mouseDown(button="left")
        time.sleep(0.02)
        pydirectinput.moveTo(tx2, ty2)
        time.sleep(0.02)
        pydirectinput.mouseUp(button="left")
