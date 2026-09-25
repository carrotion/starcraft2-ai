"""Autonomous Learning Evaluator and Strategy Auto-Tuner for SC2 Coached Bot."""

import json
import os
import time
from dataclasses import asdict
from typing import Dict, Any, List
from src.sc2_bot.strategy_guide import StrategyConfig


STATS_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "learning_stats", "history.jsonl")
BEST_STRATEGY_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "learning_stats", "best_strategy.json")


class AutonomousEvaluator:
    """Tracks match history and autonomously tunes strategy parameters based on win/loss patterns."""

    def __init__(self):
        os.makedirs(os.path.dirname(STATS_FILE), exist_ok=True)
        self.history: List[Dict[str, Any]] = self._load_history()

    def _load_history(self) -> List[Dict[str, Any]]:
        records = []
        if os.path.exists(STATS_FILE):
            with open(STATS_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            records.append(json.loads(line))
                        except Exception:
                            pass
        return records

    def record_match(
        self,
        game_num: int,
        result: str,
        game_duration_sec: float,
        enemy_race: str,
        difficulty: str,
        mode: str,
        strategy: StrategyConfig,
        notes: str = "",
        replay_file: str = "",
        map_name: str = "",
    ) -> Dict[str, Any]:
        """Saves match outcome and returns updated statistics."""
        record = {
            "game_num": game_num,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "result": result,
            "duration_sec": round(game_duration_sec, 1),
            "enemy_race": enemy_race,
            "difficulty": difficulty,
            "mode": mode,
            "map_name": map_name,
            "strategy": asdict(strategy),
            "notes": notes,
            "replay_file": replay_file,
        }
        self.history.append(record)


        with open(STATS_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

        # Save best strategy if victory
        if result == "Victory":
            with open(BEST_STRATEGY_FILE, "w", encoding="utf-8") as f:
                json.dump(asdict(strategy), f, indent=2, ensure_ascii=False)

        return self.get_summary()

    def get_summary(self) -> Dict[str, Any]:
        total = len(self.history)
        if total == 0:
            return {"total_games": 0, "wins": 0, "losses": 0, "win_rate": 0.0}

        wins = sum(1 for r in self.history if r["result"] == "Victory")
        losses = sum(1 for r in self.history if r["result"] == "Defeat")
        ties = total - wins - losses
        win_rate = round((wins / total) * 100, 1)

        recent_10 = self.history[-10:]
        recent_wins = sum(1 for r in recent_10 if r["result"] == "Victory")
        recent_win_rate = round((recent_wins / len(recent_10)) * 100, 1)

        return {
            "total_games": total,
            "wins": wins,
            "losses": losses,
            "ties": ties,
            "win_rate": win_rate,
            "recent_10_win_rate": recent_win_rate,
        }

    def evolve_strategy(self, current_strategy: StrategyConfig, last_result: str, game_duration: float) -> StrategyConfig:
        """Autonomously adapts parameters to overcome observed challenges."""
        evolved = StrategyConfig(**asdict(current_strategy))

        # Adaptation rules
        if last_result == "Defeat":
            if game_duration < 300:  # Early game loss (< 5 mins) -> Prioritize earlier defense
                evolved.target_barracks = max(4, evolved.target_barracks)
                evolved.mule_energy_threshold = 100
                evolved.attack_army_threshold = max(24, evolved.attack_army_threshold - 2)
            else:  # Mid/Late game loss (> 5 mins) -> Build a larger deathball & expand economy
                evolved.attack_army_threshold = min(36, evolved.attack_army_threshold + 2)
                evolved.target_factories = min(3, evolved.target_factories + 1)
                evolved.max_bases = min(4, max(2, evolved.max_bases + 1))
                evolved.max_workers = min(75, max(48, evolved.max_workers + 6))
        elif last_result == "Victory":
            # On victory, reinforce winning configuration or slightly explore aggressive timings
            if game_duration > 600:
                evolved.attack_army_threshold = min(32, evolved.attack_army_threshold + 1)
                evolved.max_bases = max(3, min(4, evolved.max_bases))
                evolved.max_workers = max(60, min(75, evolved.max_workers))

        return evolved
