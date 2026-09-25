"""Autonomous Learning Evaluator and Strategy Auto-Tuner for SC2 Coached Bot."""

import json
import os
import time
from dataclasses import asdict
from typing import Dict, Any, List, Optional
from src.sc2_bot.strategy_guide import StrategyConfig
from src.sc2_learning.fitness import FitnessBreakdown, MatchMetrics


STATS_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "learning_stats", "history.jsonl")
BEST_STRATEGY_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "learning_stats", "best_strategy.json")


class AutonomousEvaluator:
    """Tracks match history and autonomously tunes strategy parameters based on multi-objective fitness & win/loss patterns."""

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
        fitness: Optional[FitnessBreakdown] = None,
        metrics: Optional[MatchMetrics] = None,
    ) -> Dict[str, Any]:
        """Saves match outcome with full economic/trade fitness metrics and returns updated statistics."""
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
            "fitness": fitness.to_dict() if fitness else None,
            "metrics": asdict(metrics) if metrics else None,
        }
        self.history.append(record)

        with open(STATS_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

        # Save best strategy if victory or new high fitness score
        is_best = False
        if result == "Victory":
            is_best = True
        elif fitness and fitness.composite_score > 60.0:
            is_best = True

        if is_best:
            try:
                with open(BEST_STRATEGY_FILE, "w", encoding="utf-8") as f:
                    json.dump(asdict(strategy), f, indent=2, ensure_ascii=False)
            except Exception:
                pass

        return self.get_summary()

    def get_summary(self) -> Dict[str, Any]:
        total = len(self.history)
        if total == 0:
            return {
                "total_games": 0, "wins": 0, "losses": 0, "win_rate": 0.0,
                "avg_fitness": 0.0, "avg_trade_ratio": 1.0, "avg_spending_ratio": 0.0,
            }

        wins = sum(1 for r in self.history if r["result"] == "Victory")
        losses = sum(1 for r in self.history if r["result"] == "Defeat")
        ties = total - wins - losses
        win_rate = round((wins / total) * 100, 1)

        recent_10 = self.history[-10:]
        recent_wins = sum(1 for r in recent_10 if r["result"] == "Victory")
        recent_win_rate = round((recent_wins / len(recent_10)) * 100, 1)

        # Fitness aggregations
        fitness_scores = [r["fitness"]["composite_score"] for r in recent_10 if r.get("fitness")]
        trade_ratios = [r["fitness"]["trade_ratio"] for r in recent_10 if r.get("fitness")]
        spending_ratios = [r["fitness"]["spending_ratio"] for r in recent_10 if r.get("fitness")]

        avg_fitness = round(sum(fitness_scores) / len(fitness_scores), 1) if fitness_scores else 0.0
        avg_trade = round(sum(trade_ratios) / len(trade_ratios), 2) if trade_ratios else 1.0
        avg_spending = round(sum(spending_ratios) / len(spending_ratios) * 100, 1) if spending_ratios else 0.0

        return {
            "total_games": total,
            "wins": wins,
            "losses": losses,
            "ties": ties,
            "win_rate": win_rate,
            "recent_10_win_rate": recent_win_rate,
            "avg_fitness": avg_fitness,
            "avg_trade_ratio": avg_trade,
            "avg_spending_ratio": avg_spending,
        }

    def evolve_strategy(
        self,
        current_strategy: StrategyConfig,
        last_result: str,
        game_duration: float,
        enemy_race: str = "Unknown",
        fitness: Optional[FitnessBreakdown] = None,
    ) -> StrategyConfig:
        """Autonomously adapts parameters based on composite fitness, resource spending, and trade ratios."""
        import random
        evolved = StrategyConfig(**asdict(current_strategy))
        norm_race = enemy_race.upper()

        spending_ratio = fitness.spending_ratio if fitness else 0.85
        trade_ratio = fitness.trade_ratio if fitness else (1.5 if last_result == "Victory" else 0.7)
        float_penalty = fitness.float_penalty if fitness else 0.0

        # 1. Economic Spending Optimization (Macro conversion capacity):
        # If the bot is floating resources (spending_ratio < 0.75 or high float penalty),
        # expand production capacity (more Barracks/Factories) so minerals don't sit idle.
        if spending_ratio < 0.75 or float_penalty > 10.0:
            evolved.target_barracks = min(8, evolved.target_barracks + 1)
            evolved.target_factories = min(4, evolved.target_factories + 1)
            if game_duration > 400:
                evolved.max_bases = min(4, evolved.max_bases + 1)

        # 2. Defeat Analysis & Counter-Composition Adaptation
        if last_result == "Defeat":
            if game_duration < 300:  # Early game loss (< 5 mins) -> Prioritize early bunker defense & bio
                evolved.target_barracks = max(4, evolved.target_barracks)
                evolved.mule_energy_threshold = 100
                evolved.train_marines = True
                evolved.attack_army_threshold = max(24, evolved.attack_army_threshold - 2)
            elif game_duration < 600 or trade_ratio < 0.85:  # Mid game loss or poor cost-trade
                evolved.attack_army_threshold = min(36, evolved.attack_army_threshold + 2)
                evolved.target_factories = min(3, evolved.target_factories + 1)
                evolved.build_armory = True

                if "ZERG" in norm_race:
                    # Counter Zerglings/Banelings with Hellbats, Mutas/Ultras with Thors
                    evolved.train_hellbats = True
                    evolved.train_thors = True
                    evolved.train_siege_tanks = True
                elif "PROTOSS" in norm_race:
                    # Counter Stalkers with Marauders, Colossi/Carriers with Vikings & Thors
                    evolved.train_marauders = True
                    evolved.train_vikings = True
                    evolved.train_thors = True
                elif "TERRAN" in norm_race:
                    # Counter Siege Tanks and gain air superiority
                    evolved.train_siege_tanks = True
                    evolved.train_vikings = True
            else:  # Late game loss (> 10 mins) -> Macro expansion & Ultimate Tech (Battlecruisers & Thors)
                evolved.max_bases = min(4, max(3, evolved.max_bases + 1))
                evolved.max_workers = min(75, max(55, evolved.max_workers + 6))
                evolved.target_factories = 3
                evolved.target_starports = 2
                evolved.build_armory = True
                evolved.build_fusion_core = True
                evolved.train_thors = True
                evolved.train_battlecruisers = True
                evolved.attack_army_threshold = min(40, evolved.attack_army_threshold + 4)

        # 3. Victory Reinforcement & Exploration
        elif last_result == "Victory":
            if game_duration > 600:
                evolved.attack_army_threshold = min(34, evolved.attack_army_threshold + 1)
                evolved.max_bases = max(3, min(4, evolved.max_bases))
                evolved.max_workers = max(60, min(75, evolved.max_workers))
                evolved.build_armory = True
                evolved.build_fusion_core = True
                evolved.train_thors = True
                evolved.train_battlecruisers = True

            # 15% chance to explore alternative composition flavor (Reinforcement Learning exploration)
            if random.random() < 0.15:
                archetype = random.choice(["adaptive", "mech_heavy", "sky_terran"])
                evolved.composition_focus = archetype
                if archetype == "mech_heavy":
                    evolved.target_factories = 3
                    evolved.train_thors = True
                    evolved.train_hellbats = True
                elif archetype == "sky_terran":
                    evolved.target_starports = 2
                    evolved.build_fusion_core = True
                    evolved.train_vikings = True
                    evolved.train_battlecruisers = True

        return evolved

