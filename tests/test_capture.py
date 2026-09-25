"""Diagnostic tests for environment, window detection, and pipeline."""

import unittest
import numpy as np
from src.envs.sc1_vision_env import StarCraftVisionEnv
from src.utils.window_finder import find_starcraft_window, get_window_rect


class TestStarCraftEnv(unittest.TestCase):
    def test_mock_environment(self):
        env = StarCraftVisionEnv(mock_mode=True)
        obs, info = env.reset()
        self.assertEqual(obs.shape, (128, 128, 1))

        # Test discrete actions 0 to 7
        for action in range(8):
            next_obs, reward, terminated, truncated, step_info = env.step(action)
            self.assertEqual(next_obs.shape, (128, 128, 1))
            self.assertIsInstance(reward, float)
            self.assertFalse(terminated)

        env.close()

    def test_window_finder(self):
        hwnd = find_starcraft_window()
        # Non-fatal: game might not be running right now
        print(f"\n[Diagnostic] StarCraft Window HWND found: {hwnd}")
        if hwnd:
            rect = get_window_rect(hwnd)
            print(f"[Diagnostic] Window Rect: {rect}")


if __name__ == "__main__":
    unittest.main()
