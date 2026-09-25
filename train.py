"""Training script for StarCraft Reinforcement Learning with Safety Controls."""

import argparse
import yaml
import pydirectinput
from src.envs.sc1_vision_env import StarCraftVisionEnv
from src.agents.ppo_agent import StarCraftAgent


def load_config(config_path: str = "config.yaml"):
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def main():
    parser = argparse.ArgumentParser(description="Train StarCraft RL Agent")
    parser.add_argument("--mock", action="store_true", help="Run with mock environment (without game running)")
    parser.add_argument("--timesteps", type=int, default=None, help="Override total timesteps")
    parser.add_argument("--delay", type=float, default=None, help="Override action delay in seconds (e.g. 0.5 or 1.0 for slow observation)")
    parser.add_argument("--config", type=str, default="config.yaml", help="Path to config file")
    args = parser.parse_args()

    config = load_config(args.config)

    if args.delay is not None:
        config["environment"]["action_delay"] = args.delay

    print("=" * 65)
    print("  StarCraft AI - 강화학습 에이전트 실행기")
    print("=" * 65)
    print("  [단축키 안내]")
    print("  - [F12] : 즉시 긴급 정지 (프로그램 안전 종료 및 마우스 해제)")
    print("  - [F9]  : 일시정지 / 다시시작 토글")
    print("  - [포커스 보호] : 스타크래프트 창 밖을 클릭하면 자동으로 동작 대기")
    print("  - [진단 이미지] : ./debug/latest_frame.png 에 실시간 저장됨")
    print(f"  - 동작 딜레이 : {config['environment']['action_delay']}초 (천천히 보려면 --delay 1.0)")
    print("=" * 65)

    env = StarCraftVisionEnv(config=config["environment"], mock_mode=args.mock)

    timesteps = args.timesteps or config["rl"]["total_timesteps"]

    agent = StarCraftAgent(
        env=env,
        learning_rate=config["rl"]["learning_rate"],
        n_steps=config["rl"]["n_steps"],
        batch_size=config["rl"]["batch_size"],
        gamma=config["rl"]["gamma"],
        log_dir=config["rl"]["log_dir"],
    )

    try:
        agent.train(
            total_timesteps=timesteps,
            checkpoint_dir=config["rl"]["checkpoint_dir"],
        )
    except (KeyboardInterrupt, SystemExit):
        print("\n[안전 종료] 실행이 중단되었습니다. 마우스 및 키보드 입력을 해제합니다.")
        pydirectinput.mouseUp(button="left")
        pydirectinput.mouseUp(button="right")
        save_path = f"{config['rl']['checkpoint_dir']}/sc1_ppo_interrupted"
        agent.model.save(save_path)
        print(f"현재까지의 모델이 저장되었습니다: {save_path}")
    finally:
        pydirectinput.mouseUp(button="left")
        pydirectinput.mouseUp(button="right")
        env.close()


if __name__ == "__main__":
    main()
