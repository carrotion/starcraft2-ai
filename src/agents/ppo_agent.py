"""PPO Agent module for StarCraft reinforcement learning."""

import os
from typing import Optional
from stable_baselines3 import PPO
from stable_baselines3.common.callbacks import CheckpointCallback
import gymnasium as gym


class StarCraftAgent:
    def __init__(
        self,
        env: gym.Env,
        learning_rate: float = 3e-4,
        n_steps: int = 2048,
        batch_size: int = 64,
        gamma: float = 0.99,
        log_dir: str = "./logs",
        model_path: Optional[str] = None,
    ):
        self.env = env
        self.log_dir = log_dir
        os.makedirs(log_dir, exist_ok=True)

        if model_path and os.path.exists(model_path):
            print(f"Loading existing model from: {model_path}")
            self.model = PPO.load(model_path, env=env)
        else:
            print("Initializing new PPO CnnPolicy model...")
            self.model = PPO(
                policy="CnnPolicy",
                env=env,
                learning_rate=learning_rate,
                n_steps=n_steps,
                batch_size=batch_size,
                gamma=gamma,
                verbose=1,
                tensorboard_log=log_dir,
            )

    def train(self, total_timesteps: int = 500000, checkpoint_dir: str = "./checkpoints"):
        os.makedirs(checkpoint_dir, exist_ok=True)
        checkpoint_callback = CheckpointCallback(
            save_freq=10000,
            save_path=checkpoint_dir,
            name_prefix="sc1_ppo",
            save_replay_buffer=False,
            save_vecnormalize=True,
        )

        print(f"Starting training for {total_timesteps} timesteps...")
        self.model.learn(
            total_timesteps=total_timesteps,
            callback=checkpoint_callback,
            progress_bar=True,
        )
        final_model_path = os.path.join(checkpoint_dir, "sc1_ppo_final")
        self.model.save(final_model_path)
        print(f"Training completed. Final model saved to {final_model_path}")

    def predict(self, observation, deterministic: bool = True):
        action, _ = self.model.predict(observation, deterministic=deterministic)
        return action
