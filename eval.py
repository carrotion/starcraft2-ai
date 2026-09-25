"""Evaluation and inference script for trained StarCraft RL Agent."""

import argparse
import time
import yaml
from src.envs.sc1_vision_env import StarCraftVisionEnv
from src.agents.ppo_agent import StarCraftAgent


def load_config(config_path: str = "config.yaml"):
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def main():
    parser = argparse.ArgumentParser(description="Evaluate StarCraft RL Agent")
    parser.add_argument("--model", type=str, required=True, help="Path to trained model zip file")
    parser.add_argument("--episodes", type=int, default=3, help="Number of episodes to evaluate")
    parser.add_argument("--mock", action="store_true", help="Run in mock mode")
    parser.add_argument("--config", type=str, default="config.yaml", help="Path to config file")
    args = parser.parse_args()

    config = load_config(args.config)
    env = StarCraftVisionEnv(config=config["environment"], mock_mode=args.mock)

    agent = StarCraftAgent(env=env, model_path=args.model)

    print(f"Running evaluation for {args.episodes} episodes...")
    for ep in range(1, args.episodes + 1):
        obs, _ = env.reset()
        done = False
        total_reward = 0.0
        step_count = 0

        while not done:
            action = agent.predict(obs, deterministic=True)
            obs, reward, terminated, truncated, info = env.step(action)
            total_reward += reward
            step_count += 1
            done = terminated or truncated

        print(f"Episode {ep}: Total Reward = {total_reward:.2f}, Steps = {step_count}")

    env.close()


if __name__ == "__main__":
    main()
