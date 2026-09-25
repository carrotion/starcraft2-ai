"""StarCraft II Coached AI Runner with Auto Zombie Cleanup, Safe Exception Handling, and Pause-on-Exit."""

import os
import sys
import subprocess
import argparse

# Enable line-buffered console printing
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True)

os.environ["SC2PATH"] = os.environ.get("SC2PATH", r"C:\Games\StarCraft II")

from sc2 import maps
from sc2.data import Difficulty, Race
from sc2.main import run_game
from sc2.player import Bot, Computer

from src.sc2_bot.coached_bot import CoachedTerranBot
from src.sc2_bot.strategy_guide import CURRENT_STRATEGY
from src.sc2_utils.window_snapper import start_window_snapper_thread


DIFFICULTY_MAP = {
    "easy": Difficulty.Easy,
    "medium": Difficulty.Medium,
    "hard": Difficulty.Hard,
    "veryhard": Difficulty.VeryHard,
    "insane": Difficulty.CheatInsane,
}

RACE_MAP = {
    "terran": Race.Terran,
    "protoss": Race.Protoss,
    "zerg": Race.Zerg,
    "random": Race.Random,
}


def cleanup_zombie_processes():
    """Kill lingering SC2 and BlizzardError processes to avoid port lock or crash on startup."""
    try:
        subprocess.run(
            "taskkill /f /im SC2_x64.exe /im BlizzardError.exe >nul 2>&1",
            shell=True,
            timeout=5,
        )
    except Exception:
        pass


def main():
    parser = argparse.ArgumentParser(description="Run StarCraft II Coached Bot")
    parser.add_argument("--mode", type=str, default="1v1", choices=["1v1", "1v2"], help="Game mode (1v1 or 1v2, default: 1v1)")
    parser.add_argument("--map", type=str, default=None, help="Map name (default: Simple64 for 1v1, CactusValleyLE for 1v2)")
    parser.add_argument("--difficulty", type=str, default="veryhard", choices=DIFFICULTY_MAP.keys(), help="AI Difficulty (default: veryhard)")
    parser.add_argument("--enemy", type=str, default="zerg", choices=RACE_MAP.keys(), help="Enemy Race (for 1v1)")
    parser.add_argument("--realtime", action="store_true", default=True, help="Run in real-time (default: True)")
    args = parser.parse_args()

    # 1. Clean up any zombie SC2 processes from previous crashes or interruptions
    cleanup_zombie_processes()

    selected_diff = DIFFICULTY_MAP[args.difficulty]

    # 2. Determine Map & Opponents
    if args.mode == "1v2":
        map_name = args.map or "CactusValleyLE"
        opponents = [
            Computer(Race.Zerg, selected_diff),
            Computer(Race.Protoss, selected_diff),
        ]
        mode_desc = f"1 vs 2 (나: 테란 vs 적 1: 저그, 적 2: 프로토스)"
    else:
        map_name = args.map or "Simple64"
        opponents = [
            Computer(RACE_MAP[args.enemy], selected_diff),
        ]
        mode_desc = f"1 vs 1 (나: 테란 vs 적: {args.enemy.upper()})"

    my_bot = Bot(Race.Terran, CoachedTerranBot(CURRENT_STRATEGY))
    players = [my_bot] + opponents

    print("=" * 70)
    print("  StarCraft II - 인간-AI 협업 코칭 봇 (안정화 강화 버전)")
    print("=" * 70)
    print(f"  - 대전 모드 : {mode_desc}")
    print(f"  - 난 이 도  : [{args.difficulty.upper()}] (스타크래프트2 정석 빌드 및 공격적 확장 AI)")
    print(f"  - 대전 맵   : {map_name}")
    print("  - 방어 체제 : 언덕 입구 심시티(벙커 + 스마트 개폐 보급고) + SCV 자동 수리")
    print("  - 공격 체제 : 앞마당 멀티 2베이스 + 스팀팩/공방업 + 복합 대군 총공격")
    print("  - 화면 배치 : 모니터 좌측 (마우스/키보드 관여율 0%)")
    print("=" * 70)
    print("게임 엔진 시작 중... 잠시만 기다려주세요.\n", flush=True)

    # Start window snapper thread
    start_window_snapper_thread(x=0, y=0, width=960, height=1040)

    try:
        map_settings = maps.get(map_name)
    except Exception as e:
        print(f"[맵 로딩 에러] '{map_name}' 맵을 찾을 수 없어 기본 맵(Simple64)으로 전환합니다: {e}")
        map_settings = maps.get("Simple64")
        players = [my_bot, Computer(Race.Zerg, selected_diff)]

    try:
        result = run_game(
            map_settings=map_settings,
            players=players,
            realtime=args.realtime,
        )
        print(f"\n" + "=" * 50)
        print(f"  [게임 종료] 최종 결과: {result}")
        print("=" * 50)
    except KeyboardInterrupt:
        print("\n[사용자 중단] 게임을 정상적으로 종료했습니다.")
    except Exception as e:
        import traceback
        print(f"\n[오류 발생으로 게임 중단됨]: {e}")
        traceback.print_exc()
    finally:
        cleanup_zombie_processes()
        print("\n게임을 종료했습니다.")


if __name__ == "__main__":
    main()
