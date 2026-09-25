"""Gymnasium environment for StarCraft: Brood War via Vision & DirectInput."""

import time
from typing import Any, Dict, Optional, Tuple
import gymnasium as gym
from gymnasium import spaces
import numpy as np

from src.utils.screen_capture import ScreenCapture
from src.utils.input_controller import InputController
from src.utils.window_finder import find_starcraft_window, get_window_rect, focus_window
from src.utils.safety_controller import SafetyController
from src.envs.rewards import RewardCalculator


ACTION_NAMES = {
    0: "대기 (No-op)",
    1: "본진 기지 선택 (단축키 1)",
    2: "일꾼 생산 (단축키 S)",
    3: "병력 부대(2번) 선택 및 공격 이동 (Key A)",
    4: "인구수 건물 건설 시도 (단축키 B -> S)",
    5: "생산 건물 건설 시도 (단축키 B -> B)",
    6: "일꾼 드래그 후 미네랄 채취 유도 (우클릭)",
    7: "병력 부대 본진으로 후퇴",
}


class StarCraftVisionEnv(gym.Env):
    """Gymnasium Environment with Safety Hotkeys and Window Focus Protection.

    Safety:
        - F12: Instant Emergency Stop
        - F9: Pause / Resume Toggle
        - Auto-Suspend: Does NOT send input if StarCraft is not the active window
    """

    metadata = {"render_modes": ["rgb_array", "human"], "render_fps": 10}

    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        mock_mode: bool = False,
    ):
        super().__init__()
        self.config = config or {}
        self.mock_mode = mock_mode

        img_shape = self.config.get("model_input_size", (128, 128))
        self.img_height, self.img_width = img_shape

        self.observation_space = spaces.Box(
            low=0,
            high=255,
            shape=(self.img_height, self.img_width, 1),
            dtype=np.uint8,
        )

        self.action_space = spaces.Discrete(8)

        self.reward_calculator = RewardCalculator(
            self.config.get("reward_weights", None)
        )
        self.max_steps = self.config.get("max_episode_steps", 1000)
        self.action_delay = self.config.get("action_delay", 0.1)

        self.current_step = 0
        self.screen_capture = None
        self.input_controller = None
        self.hwnd = None
        self.window_rect = None
        self.safety = SafetyController()

        if not self.mock_mode:
            self._init_window()

    def _init_window(self):
        self.hwnd = find_starcraft_window()
        if self.hwnd:
            self.safety.set_target_hwnd(self.hwnd)
            self.window_rect = get_window_rect(self.hwnd)
            if self.window_rect:
                left, top, w, h = self.window_rect
                self.input_controller = InputController((left, top))
                print(f"[스타크래프트 창 감지됨] HWND: {self.hwnd}, 영역: {self.window_rect}")
        else:
            print("[안내] 스타크래프트 창을 찾지 못했습니다. 게임을 먼저 실행해주세요.")
            self.input_controller = InputController((0, 0))
            self.window_rect = None

        self.screen_capture = ScreenCapture(
            target_size=(self.img_width, self.img_height)
        )

    def reset(
        self,
        *,
        seed: Optional[int] = None,
        options: Optional[Dict[str, Any]] = None,
    ) -> Tuple[np.ndarray, Dict[str, Any]]:
        super().reset(seed=seed)
        self.current_step = 0

        if self.mock_mode or not self.hwnd:
            obs = np.zeros(
                (self.img_height, self.img_width, 1), dtype=np.uint8
            )
            return obs, {"mock": True}

        # Check safety hotkeys before reset
        status = self.safety.check_hotkeys()
        if status == "STOP":
            raise KeyboardInterrupt("F12 긴급 정지")

        obs = self._get_observation()
        return obs, {}

    def step(
        self, action: int
    ) -> Tuple[np.ndarray, float, bool, bool, Dict[str, Any]]:
        self.current_step += 1
        action_name = ACTION_NAMES.get(action, f"Action {action}")

        # 1. Check Safety Hotkeys (F12: Kill, F9: Pause)
        status = self.safety.check_hotkeys()
        while status == "PAUSE":
            time.sleep(0.2)
            status = self.safety.check_hotkeys()

        if status == "STOP":
            raise KeyboardInterrupt("F12 긴급 정지 키가 눌렸습니다.")

        # 2. Focus Check: Only send inputs if StarCraft is the active foreground window
        if not self.mock_mode and self.hwnd:
            if self.safety.is_target_window_active():
                print(f"[Step {self.current_step:04d}] AI 행동: {action_name}")
                self._execute_action(action)
            else:
                print(
                    f"[Step {self.current_step:04d}] [대기 중] 스타크래프트 창이 비활성 상태입니다 (입력 건너뜀)",
                    end="\r",
                )

            time.sleep(self.action_delay)
            obs = self._get_observation()
            # Save latest frame for inspection
            self.safety.save_debug_frame(obs, action_name, self.current_step)
        else:
            obs = np.random.randint(
                0, 256, (self.img_height, self.img_width, 1), dtype=np.uint8
            )

        info = {
            "step": self.current_step,
            "action": action,
            "action_name": action_name,
            "is_victory": False,
            "is_defeat": False,
        }

        reward = self.reward_calculator.compute_step_reward(info)
        terminated = False
        truncated = self.current_step >= self.max_steps

        return obs, reward, terminated, truncated, info

    def _execute_action(self, action: int):
        if not self.input_controller or not self.window_rect:
            return

        w, h = self.window_rect[2], self.window_rect[3]
        cx, cy = w // 2, h // 2

        if action == 0:
            pass
        elif action == 1:
            self.input_controller.press_key("1")
        elif action == 2:
            self.input_controller.press_key("s")
        elif action == 3:
            self.input_controller.press_key("2")
            time.sleep(0.02)
            self.input_controller.press_key("a")
            self.input_controller.click(cx + 80, cy)
        elif action == 4:
            self.input_controller.press_key("b")
            time.sleep(0.02)
            self.input_controller.press_key("s")
            self.input_controller.click(cx - 80, cy + 80)
        elif action == 5:
            self.input_controller.press_key("b")
            time.sleep(0.02)
            self.input_controller.press_key("b")
            self.input_controller.click(cx + 60, cy + 80)
        elif action == 6:
            self.input_controller.select_box(cx - 50, cy - 50, cx + 50, cy + 50)
            time.sleep(0.02)
            self.input_controller.right_click(cx + 120, cy - 80)
        elif action == 7:
            self.input_controller.press_key("2")
            time.sleep(0.02)
            self.input_controller.right_click(cx, cy)

    def _get_observation(self) -> np.ndarray:
        if self.screen_capture and self.window_rect:
            return self.screen_capture.grab_region(
                self.window_rect, grayscale=True
            )
        return np.zeros((self.img_height, self.img_width, 1), dtype=np.uint8)

    def close(self):
        if self.screen_capture:
            self.screen_capture.close()
