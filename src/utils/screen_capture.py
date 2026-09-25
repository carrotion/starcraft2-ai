"""High performance screen capture for StarCraft RL environment."""

from typing import Optional, Tuple
import cv2
import mss
import numpy as np


class ScreenCapture:
    def __init__(self, target_size: Tuple[int, int] = (128, 128)):
        self.sct = mss.mss()
        self.target_size = target_size

    def grab_region(
        self,
        region: Optional[Tuple[int, int, int, int]] = None,
        grayscale: bool = False,
    ) -> np.ndarray:
        """Capture specified region (left, top, width, height) or entire monitor.

        Returns uint8 numpy array normalized to target_size.
        """
        if region:
            left, top, width, height = region
            monitor = {"left": left, "top": top, "width": width, "height": height}
        else:
            monitor = self.sct.monitors[1]

        raw = self.sct.grab(monitor)
        # Convert BGRA to RGB or Grayscale
        frame = np.array(raw, dtype=np.uint8)[:, :, :3]

        if grayscale:
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            resized = cv2.resize(frame, self.target_size, interpolation=cv2.INTER_AREA)
            # Shape: (H, W, 1)
            return np.expand_dims(resized, axis=-1)
        else:
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            resized = cv2.resize(frame, self.target_size, interpolation=cv2.INTER_AREA)
            return resized

    def close(self):
        self.sct.close()
