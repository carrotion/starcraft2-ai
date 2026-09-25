"""Reward functions for StarCraft Reinforcement Learning."""

from typing import Dict, Any


class RewardCalculator:
    def __init__(self, weights: Dict[str, float] = None):
        self.weights = weights or {
            "win": 10.0,
            "loss": -10.0,
            "survival_bonus": 0.01,
            "step_penalty": -0.001,
        }

    def compute_step_reward(self, info: Dict[str, Any]) -> float:
        """Compute scalar reward for current step."""
        reward = self.weights.get("step_penalty", -0.001)

        # Survival incentive
        reward += self.weights.get("survival_bonus", 0.01)

        if info.get("is_victory"):
            reward += self.weights.get("win", 10.0)
        elif info.get("is_defeat"):
            reward += self.weights.get("loss", -10.0)

        return float(reward)
