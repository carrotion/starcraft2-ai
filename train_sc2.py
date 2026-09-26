"""StarCraft II Autonomous Self-Learning & Parallel Multi-Worker Training Runner."""

import os
import sys
import time
import random
import argparse
import subprocess
import shutil
from dataclasses import asdict
from concurrent.futures import ProcessPoolExecutor, as_completed

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

sc2_p = os.environ.get("SC2PATH")
if not sc2_p or not os.path.exists(sc2_p):
    for cand in [r"F:\Game\StarCraft II", r"C:\Games\StarCraft II", r"D:\Games\StarCraft II"]:
        if os.path.exists(cand):
            sc2_p = cand
            break
os.environ["SC2PATH"] = sc2_p or r"F:\Game\StarCraft II"

from sc2 import maps
from sc2.data import Difficulty, Race, Result
from sc2.main import run_game
from sc2.player import Bot, Computer

from src.sc2_bot.coached_bot import CoachedTerranBot
from src.sc2_bot.strategy_guide import CURRENT_STRATEGY, StrategyConfig
from src.sc2_learning.evaluator import AutonomousEvaluator


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

# Official competitive standard ladder map pool + clean large test maps
LADDER_MAP_POOL = [
    "Simple128",        # 128x128 spacious high-ground map (zero choke stuck)
    "AcropolisLE",     # Official Ladder 1v1 standard
    "CatalystLE",      # Official Ladder 1v1 standard
    "AcidPlantLE",     # Official Ladder 1v1 standard
    "ThunderbirdLE",   # Official Ladder 1v1 standard
    "TritonLE",        # Official Ladder 1v1 standard
]


def resolve_game_map(requested_map: str | None, mode: str) -> str:
    """Selects the map for the match. If random/pool is requested, samples from LADDER_MAP_POOL."""
    if mode == "1v2":
        return "CactusValleyLE"
    if not requested_map or requested_map.lower() in ("random", "pool", "ladder", "rotation"):
        return random.choice(LADDER_MAP_POOL)
    return requested_map


def cleanup_zombies():
    try:
        subprocess.run(
            "taskkill /f /im SC2_x64.exe /im BlizzardError.exe >nul 2>&1",
            shell=True,
            timeout=5,
        )
    except Exception:
        pass


REPLAYS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "replays"))
VICTORY_REPLAYS_DIR = os.path.join(REPLAYS_DIR, "victories")
os.makedirs(REPLAYS_DIR, exist_ok=True)
os.makedirs(VICTORY_REPLAYS_DIR, exist_ok=True)


def find_sc2_user_replay_dir() -> str | None:
    """Finds the user's active StarCraft II Accounts replay folder if it exists."""
    candidates = [
        os.path.join(os.environ.get("USERPROFILE", ""), "OneDrive", "문서", "StarCraft II", "Accounts"),
        os.path.join(os.environ.get("USERPROFILE", ""), "Documents", "StarCraft II", "Accounts"),
    ]
    for base in candidates:
        if os.path.exists(base):
            for acc in os.listdir(base):
                acc_path = os.path.join(base, acc)
                if os.path.isdir(acc_path):
                    for prof in os.listdir(acc_path):
                        replays_dir = os.path.join(acc_path, prof, "Replays", "Multiplayer", "AI_Training")
                        try:
                            os.makedirs(replays_dir, exist_ok=True)
                            return replays_dir
                        except Exception:
                            continue
    return None


class TrackedBot(CoachedTerranBot):
    """Subclass of CoachedTerranBot to capture game result and actual enemy race."""

    def __init__(self, strategy: StrategyConfig, worker_id: int = 1):
        super().__init__(strategy, worker_id=worker_id)
        self.final_result = "Unknown"
        self.final_game_time = 0.0
        self.actual_enemy_race = "Unknown"

    async def on_step(self, iteration: int):
        self.final_game_time = self.time

        # Resolve actual enemy race if initially Random or Unknown
        if self.actual_enemy_race in ("Unknown", "Random", "random"):
            # 1. Direct enemy_race from python-sc2
            if self.enemy_race and self.enemy_race != Race.Random:
                self.actual_enemy_race = self.enemy_race.name
            # 2. Check game_info players
            elif hasattr(self, "game_info") and self.game_info.players:
                opponents = [p for p in self.game_info.players if p.id != self.player_id]
                if opponents:
                    valid_races = [p.actual_race.name for p in opponents if p.actual_race and p.actual_race != Race.Random]
                    if valid_races:
                        self.actual_enemy_race = "+".join(valid_races)
            # 3. Check observed enemy units or structures
            if self.actual_enemy_race in ("Unknown", "Random", "random"):
                if self.all_enemy_units:
                    self.actual_enemy_race = self.all_enemy_units.first.race.name
                elif self.enemy_structures:
                    self.actual_enemy_race = self.enemy_structures.first.race.name

        await super().on_step(iteration)

    async def on_end(self, game_result: Result):
        # Final resolution check at match conclusion
        if self.actual_enemy_race in ("Unknown", "Random", "random"):
            if hasattr(self, "game_info") and self.game_info.players:
                opponents = [p for p in self.game_info.players if p.id != self.player_id]
                if opponents:
                    valid_races = [p.actual_race.name for p in opponents if p.actual_race and p.actual_race != Race.Random]
                    if valid_races:
                        self.actual_enemy_race = "+".join(valid_races)
            if self.actual_enemy_race in ("Unknown", "Random", "random") and self.all_enemy_units:
                self.actual_enemy_race = self.all_enemy_units.first.race.name

        if game_result == Result.Victory:
            self.final_result = "Victory"
        elif game_result == Result.Defeat:
            self.final_result = "Defeat"
        elif game_result == Result.Tie:
            self.final_result = "Tie"
        else:
            self.final_result = str(game_result)

        await super().on_end(game_result)


def run_worker_game(
    game_num: int,
    worker_id: int,
    strategy_dict: dict,
    mode: str,
    map_name: str,
    difficulty_str: str,
    enemy_race: str,
    realtime: bool,
) -> tuple[int, int, str, float, float, str, str, str]:
    """Runs a single SC2 match in an isolated worker process and saves the full .SC2Replay."""
    wall_start = time.time()
    strategy = StrategyConfig(**strategy_dict)
    selected_diff = DIFFICULTY_MAP[difficulty_str]

    replay_file = f"game_{game_num:04d}_w{worker_id}_{enemy_race}_{map_name}_{difficulty_str}.SC2Replay"
    replay_path = os.path.join(REPLAYS_DIR, replay_file)

    if mode == "1v2":
        opponents = [
            Computer(Race.Zerg, selected_diff),
            Computer(Race.Protoss, selected_diff),
        ]
    else:
        opponents = [
            Computer(RACE_MAP[enemy_race], selected_diff),
        ]

    bot_instance = TrackedBot(strategy, worker_id=worker_id)
    players = [Bot(Race.Terran, bot_instance)] + opponents

    try:
        map_settings = maps.get(map_name)
        result = run_game(
            map_settings,
            players,
            realtime=realtime,
            save_replay_as=replay_path,
        )
        if isinstance(result, Result):
            result_str = result.name.capitalize()
        else:
            result_str = bot_instance.final_result

        wall_elapsed = time.time() - wall_start
        saved_file = ""
        if os.path.exists(replay_path):
            saved_file = replay_file
            if result_str == "Victory":
                try:
                    shutil.copy2(replay_path, os.path.join(VICTORY_REPLAYS_DIR, replay_file))
                except Exception:
                    pass
            try:
                sc2_folder = find_sc2_user_replay_dir()
                if sc2_folder:
                    shutil.copy2(replay_path, os.path.join(sc2_folder, replay_file))
            except Exception:
                pass
        return (
            game_num,
            worker_id,
            result_str,
            bot_instance.final_game_time,
            wall_elapsed,
            saved_file,
            map_name,
            bot_instance.actual_enemy_race,
            bot_instance.last_fitness,
            bot_instance.last_metrics,
        )
    except Exception as e:
        wall_elapsed = time.time() - wall_start
        res = bot_instance.final_result if bot_instance.final_result != "Unknown" else "Error"
        saved_file = ""
        if os.path.exists(replay_path):
            saved_file = replay_file
            if res == "Victory":
                try:
                    shutil.copy2(replay_path, os.path.join(VICTORY_REPLAYS_DIR, replay_file))
                except Exception:
                    pass
            try:
                sc2_folder = find_sc2_user_replay_dir()
                if sc2_folder:
                    shutil.copy2(replay_path, os.path.join(sc2_folder, replay_file))
            except Exception:
                pass
        return (
            game_num,
            worker_id,
            res,
            bot_instance.final_game_time,
            wall_elapsed,
            saved_file,
            map_name,
            bot_instance.actual_enemy_race,
            getattr(bot_instance, "last_fitness", None),
            getattr(bot_instance, "last_metrics", None),
        )




def main():
    parser = argparse.ArgumentParser(description="SC2 Autonomous Self-Training Loop")
    parser.add_argument("--games", type=int, default=10, help="Total games to run (0 for infinite loop, default: 10)")
    parser.add_argument("--workers", type=int, default=1, help="Number of parallel SC2 instances (e.g. 4, 5, default: 1)")
    parser.add_argument("--mode", type=str, default="1v1", choices=["1v1", "1v2"], help="Game mode (default: 1v1)")
    parser.add_argument("--map", type=str, default=None, help="Map name (default: Simple64 for 1v1, CactusValleyLE for 1v2)")
    parser.add_argument("--difficulty", type=str, default="veryhard", choices=DIFFICULTY_MAP.keys(), help="Enemy AI Difficulty (default: veryhard)")
    parser.add_argument("--enemy", type=str, default="zerg", choices=RACE_MAP.keys(), help="Enemy Race (default: zerg)")
    parser.add_argument("--realtime", action="store_true", default=False, help="Run in visual real-time (default: False for fast simulation)")
    args = parser.parse_args()

    evaluator = AutonomousEvaluator()
    current_strat = CURRENT_STRATEGY

    map_arg = args.map or ("CactusValleyLE" if args.mode == "1v2" else "random")
    target_games = args.games if args.games > 0 else float("inf")

    mode_str = f"1 vs 2 (저그 & 프로토스)" if args.mode == "1v2" else f"1 vs 1 (테란 vs {args.enemy.upper()})"
    speed_str = "초고속 비실시간 (Fast Simulation)" if not args.realtime else "실시간 관전 (Real-Time)"
    map_display = "🎲 래더 맵 랜덤 로테이션 (Pool)" if map_arg.lower() in ("random", "pool", "ladder") else map_arg

    print("=" * 75)
    print("  🚀 StarCraft II - 자율 학습 및 병렬 멀티워커 훈련 시스템 (Auto-Trainer)")
    print("=" * 75)
    print(f"  - 대전 모드   : {mode_str}")
    print(f"  - 난 이 도    : [{args.difficulty.upper()}] (최상위 정석 빌드)")
    print(f"  - 병렬 워커수 : {args.workers}개 동시 실행 (Multi-Processing)")
    print(f"  - 시뮬레이션  : {speed_str}")
    print(f"  - 대전 맵     : {map_display}")
    print(f"  - 목표 경기수 : {'무한 반복 (Infinite Loop)' if target_games == float('inf') else f'{args.games}경기'}")
    print("=" * 75)

    summary = evaluator.get_summary()
    print(f"  📊 누적 전적: {summary['wins']}승 {summary['losses']}패 (승률: {summary['win_rate']}%)")
    print(f"  총 {args.workers}개의 병렬 워커 프로세스를 시작합니다...\n")

    cleanup_zombies()
    start_session = time.time()
    game_idx = len(evaluator.history) + 1
    completed_games = 0

    try:
        if args.workers <= 1:
            # Single-worker sequential execution
            while completed_games < target_games:
                completed_games += 1
                chosen_map = resolve_game_map(map_arg, args.mode)
                print(f"\n▶ [경기 #{game_idx}] 시작... (맵: {chosen_map}, 공격 임계치: {current_strat.attack_army_threshold})")
                
                g_num, w_id, result_str, game_time, wall_elapsed, rep_file, played_map, resolved_race, fitness, metrics = run_worker_game(
                    game_num=game_idx,
                    worker_id=1,
                    strategy_dict=asdict(current_strat),
                    mode=args.mode,
                    map_name=chosen_map,
                    difficulty_str=args.difficulty,
                    enemy_race=args.enemy,
                    realtime=args.realtime,
                )

                mins, secs = divmod(int(game_time), 60)
                actual_enemy = (
                    resolved_race
                    if (resolved_race and resolved_race not in ("Unknown", "Random", "random"))
                    else (args.enemy if args.mode == "1v1" else "zerg_protoss")
                )
                stats = evaluator.record_match(
                    game_num=g_num,
                    result=result_str,
                    game_duration_sec=game_time,
                    enemy_race=actual_enemy,
                    difficulty=args.difficulty,
                    mode=args.mode,
                    strategy=current_strat,
                    notes=f"Wall time: {wall_elapsed:.1f}s",
                    replay_file=rep_file,
                    map_name=played_map,
                    fitness=fitness,
                    metrics=metrics,
                )

                current_strat = evaluator.evolve_strategy(
                    current_strat, result_str, game_time, enemy_race=actual_enemy, fitness=fitness
                )

                print("=" * 75)
                print(f"  🏁 [경기 #{g_num} 종료] (상대: {actual_enemy.upper()}, 맵: {played_map})")
                print(f"  - 경기 결과   : [ {result_str.upper()} ] (게임 시간: {mins:02d}분 {secs:02d}초 / 실제: {wall_elapsed:.1f}초)")
                if fitness:
                    print(
                        f"  - 복합 피트니스 : {fitness.composite_score:+.1f}점 "
                        f"(가성비 교환 {fitness.trade_ratio:.2f}:1, 소모율 {fitness.spending_ratio*100:.1f}%, 잉여감점 -{fitness.float_penalty:.1f}점)"
                    )
                print(
                    f"  - 누적 전적   : {stats['wins']}승 {stats['losses']}패 (승률: {stats['win_rate']}%, 최근10전: {stats['recent_10_win_rate']}%) | "
                    f"최근 평균가성비: {stats['avg_trade_ratio']:.2f}:1, 자원소모: {stats['avg_spending_ratio']:.1f}%"
                )
                if rep_file:
                    print(f"  - 리플레이    : replays/{rep_file}")
                print("=" * 75)
                game_idx += 1
                time.sleep(1)

        else:
            # Multi-worker parallel execution
            with ProcessPoolExecutor(max_workers=args.workers) as executor:
                submitted_games = 0
                futures = {}

                # Initially submit up to args.workers jobs
                initial_batch = min(args.workers, target_games) if target_games != float("inf") else args.workers
                for w_idx in range(1, initial_batch + 1):
                    submitted_games += 1
                    chosen_map = resolve_game_map(map_arg, args.mode)
                    fut = executor.submit(
                        run_worker_game,
                        game_idx,
                        w_idx,
                        asdict(current_strat),
                        args.mode,
                        chosen_map,
                        args.difficulty,
                        args.enemy,
                        args.realtime,
                    )
                    futures[fut] = (game_idx, w_idx)
                    print(f"  [워커 #{w_idx}] 경기 #{game_idx} 출격 완료 (맵: {chosen_map}, 동시 진행 중: {len(futures)}개)")
                    game_idx += 1
                    time.sleep(1.5)  # Stagger SC2 process launches to avoid port binding conflicts

                # Harvest results as they complete and dispatch next
                while futures:
                    for fut in as_completed(list(futures.keys())):
                        g_num, w_id, result_str, game_time, wall_elapsed, rep_file, played_map, resolved_race, fitness, metrics = fut.result()
                        del futures[fut]
                        completed_games += 1

                        mins, secs = divmod(int(game_time), 60)
                        actual_enemy = (
                            resolved_race
                            if (resolved_race and resolved_race not in ("Unknown", "Random", "random"))
                            else (args.enemy if args.mode == "1v1" else "zerg_protoss")
                        )
                        stats = evaluator.record_match(
                            game_num=g_num,
                            result=result_str,
                            game_duration_sec=game_time,
                            enemy_race=actual_enemy,
                            difficulty=args.difficulty,
                            mode=args.mode,
                            strategy=current_strat,
                            notes=f"Worker #{w_id}, Wall time: {wall_elapsed:.1f}s",
                            replay_file=rep_file,
                            map_name=played_map,
                            fitness=fitness,
                            metrics=metrics,
                        )

                        # Auto-evolve strategy
                        current_strat = evaluator.evolve_strategy(
                            current_strat, result_str, game_time, enemy_race=actual_enemy, fitness=fitness
                        )

                        print("=" * 75)
                        print(f"  🏁 [워커 #{w_id}] 경기 #{g_num} 완료! [ {result_str.upper()} ] (상대: {actual_enemy.upper()}, 맵: {played_map})")
                        print(f"  - 소요 시간   : 게임 내 {mins:02d}분 {secs:02d}초 (실제 소요: {wall_elapsed:.1f}초)")
                        if fitness:
                            print(
                                f"  - 복합 피트니스 : {fitness.composite_score:+.1f}점 "
                                f"(가성비 교환 {fitness.trade_ratio:.2f}:1, 소모율 {fitness.spending_ratio*100:.1f}%, 잉여감점 -{fitness.float_penalty:.1f}점)"
                            )
                        print(f"  - 진행 상황   : {completed_games}/{args.games if target_games != float('inf') else '무한'} 완료")
                        print(
                            f"  - 누적 전적   : {stats['wins']}승 {stats['losses']}패 (승률: {stats['win_rate']}%, 최근10전: {stats['recent_10_win_rate']}%) | "
                            f"최근 평균가성비: {stats['avg_trade_ratio']:.2f}:1, 자원소모: {stats['avg_spending_ratio']:.1f}%"
                        )
                        if rep_file:
                            print(f"  - 리플레이    : replays/{rep_file}")
                        print("=" * 75)



                        # Dispatch next match if remaining
                        if submitted_games < target_games:
                            submitted_games += 1
                            next_map = resolve_game_map(map_arg, args.mode)
                            new_fut = executor.submit(
                                run_worker_game,
                                game_idx,
                                w_id,
                                asdict(current_strat),
                                args.mode,
                                next_map,
                                args.difficulty,
                                args.enemy,
                                args.realtime,
                            )
                            futures[new_fut] = (game_idx, w_id)
                            print(f"  ➔ [워커 #{w_id}] 경기 #{game_idx} 즉시 출격! (맵: {next_map}, 진행 중: {len(futures)}개)")
                            game_idx += 1

                        break

    except KeyboardInterrupt:
        print("\n\n[사용자 중단] 자율 훈련이 일시 정지되었습니다.")
    finally:
        cleanup_zombies()
        session_elapsed = time.time() - start_session
        final_summary = evaluator.get_summary()
        mins, secs = divmod(int(session_elapsed), 60)
        print("\n" + "=" * 75)
        print("  🏆 자율 학습 세션 요약 보고서")
        print(f"  - 총 소요 시간 : {mins:02d}분 {secs:02d}초")
        print(f"  - 총 완료 경기 : {completed_games}게임")
        print(f"  - 최종 승률    : {final_summary['win_rate']}% ({final_summary['wins']}승 {final_summary['losses']}패)")
        print(f"  - 기록 저장소  : learning_stats/history.jsonl")
        print("=" * 75)


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    main()
