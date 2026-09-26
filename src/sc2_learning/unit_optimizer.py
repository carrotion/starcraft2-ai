"""Autonomous Hybrid Unit Composition Optimizer & Reinforcement Learning Engine for SC2.

Combines:
1. Meta-Learning (RL / Genetic Weight Optimization across matches per enemy race)
2. In-Game Real-Time Reactive Counter Adaptation (Enemy army observation -> Dynamic weight shift)
"""

import os
import json
import random
from typing import Dict, Any

WEIGHTS_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "learning_stats",
    "unit_weights.json",
)

ALL_16_UNITS = [
    # Barracks
    "marine", "reaper", "marauder", "ghost",
    # Factory
    "hellion", "hellbat", "widowmine", "cyclone", "siegetank", "thor",
    # Starport
    "viking", "medivac", "liberator", "raven", "banshee", "battlecruiser",
]

DEFAULT_BASE_WEIGHTS: Dict[str, Dict[str, float]] = {
    "TERRAN": {
        "marine": 1.2, "reaper": 0.3, "marauder": 0.9, "ghost": 0.5,
        "hellion": 0.4, "hellbat": 0.6, "widowmine": 0.5, "cyclone": 0.7, "siegetank": 1.4, "thor": 0.8,
        "viking": 1.1, "medivac": 0.9, "liberator": 0.6, "raven": 0.6, "banshee": 0.5, "battlecruiser": 0.8,
    },
    "PROTOSS": {
        "marine": 1.1, "reaper": 0.3, "marauder": 1.4, "ghost": 1.0,
        "hellion": 0.3, "hellbat": 0.5, "widowmine": 0.7, "cyclone": 0.8, "siegetank": 1.0, "thor": 0.9,
        "viking": 1.2, "medivac": 0.9, "liberator": 0.7, "raven": 0.7, "banshee": 0.4, "battlecruiser": 0.7,
    },
    "ZERG": {
        "marine": 1.2, "reaper": 0.4, "marauder": 0.7, "ghost": 0.7,
        "hellion": 0.8, "hellbat": 1.3, "widowmine": 0.9, "cyclone": 0.6, "siegetank": 1.3, "thor": 1.1,
        "viking": 0.7, "medivac": 0.9, "liberator": 0.8, "raven": 0.6, "banshee": 0.7, "battlecruiser": 0.7,
    },
    "DEFAULT": {
        "marine": 1.2, "reaper": 0.3, "marauder": 1.0, "ghost": 0.6,
        "hellion": 0.5, "hellbat": 0.8, "widowmine": 0.6, "cyclone": 0.7, "siegetank": 1.2, "thor": 0.9,
        "viking": 1.0, "medivac": 0.9, "liberator": 0.6, "raven": 0.5, "banshee": 0.5, "battlecruiser": 0.8,
    },
}


class UnitOptimizer:
    """Manages persistent unit production weights and real-time observation modifiers."""

    def __init__(self):
        self.weights_file = WEIGHTS_FILE
        os.makedirs(os.path.dirname(self.weights_file), exist_ok=True)
        self.race_weights = self._load_weights()

    def _load_weights(self) -> Dict[str, Dict[str, float]]:
        """Loads weights from persistent JSON or initializes defaults."""
        if os.path.exists(self.weights_file):
            try:
                with open(self.weights_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    # Validate all units exist
                    for race in ["TERRAN", "PROTOSS", "ZERG", "DEFAULT"]:
                        if race not in data:
                            data[race] = dict(DEFAULT_BASE_WEIGHTS.get(race, DEFAULT_BASE_WEIGHTS["DEFAULT"]))
                        for u in ALL_16_UNITS:
                            if u not in data[race]:
                                data[race][u] = DEFAULT_BASE_WEIGHTS["DEFAULT"].get(u, 0.5)
                    return data
            except Exception:
                pass
        
        # Deep copy defaults
        init_data = {r: dict(w) for r, w in DEFAULT_BASE_WEIGHTS.items()}
        self._save_weights(init_data)
        return init_data

    def _save_weights(self, data: Dict[str, Dict[str, float]]):
        """Atomically saves weights to disk."""
        tmp = self.weights_file + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            os.replace(tmp, self.weights_file)
        except Exception:
            pass

    def get_effective_weights(
        self,
        enemy_race: str,
        enemy_units: Any,
        game_time: float,
        minerals: int,
        vespene: int,
    ) -> Dict[str, float]:
        """Calculates real-time effective unit utility weights: Base learned weight + real-time counter deltas."""
        norm_race = enemy_race.upper() if enemy_race else "DEFAULT"
        if norm_race not in self.race_weights:
            norm_race = "DEFAULT"

        weights = dict(self.race_weights[norm_race])

        # Real-time counter adjustments based on observed enemy units
        if enemy_units:
            flying = [e for e in enemy_units if getattr(e, "is_flying", False) or getattr(e, "type_id", None) and e.type_id.name == "COLOSSUS"]
            light = [e for e in enemy_units if getattr(e, "is_light", False)]
            armored = [e for e in enemy_units if getattr(e, "is_armored", False)]
            massive = [e for e in enemy_units if getattr(e, "is_massive", False)]
            cloaked = [e for e in enemy_units if getattr(e, "is_cloaked", False) or getattr(e, "is_burrowed", False)]
            psionic = [e for e in enemy_units if getattr(e, "energy_max", 0) > 50 or getattr(e, "shield_max", 0) > 80]

            # 1. Anti-Air & Colossus urgency
            if len(flying) >= 2:
                weights["viking"] += 0.6
                weights["thor"] += 0.5
                weights["cyclone"] += 0.3

            # 2. Anti-Light / Swarm urgency (Zerglings, Zealots, Marines, Banelings)
            if len(light) >= 4:
                weights["hellbat"] += 0.7
                weights["siegetank"] += 0.5
                weights["widowmine"] += 0.5

            # 3. Anti-Armor urgency (Roaches, Stalkers, Immortals, Tanks)
            if len(armored) >= 3:
                weights["marauder"] += 0.5
                weights["cyclone"] += 0.4
                weights["liberator"] += 0.4
                weights["thor"] += 0.4

            # 4. Anti-Massive urgency (Ultralisk, Colossus, Carrier, Broodlord, Thor)
            if len(massive) >= 1:
                weights["thor"] += 0.6
                weights["battlecruiser"] += 0.5
                weights["ghost"] += 0.5
                weights["viking"] += 0.4

            # 5. Detection urgency (Dark Templar, Banshees, Lurkers, Burrowed units)
            if cloaked:
                weights["raven"] += 0.8

            # 6. EMP / Anti-Psionic urgency (High Templar, Archons, Sentry, Vipers, Infestors)
            if len(psionic) >= 2:
                weights["ghost"] += 0.8

        # 7. Macro Resource State Awareness (Wallet Balancing):
        if vespene > 350 and minerals < 250:
            # Gas surplus & mineral bottleneck -> Heavily prioritize gas tech units and suppress mineral drains!
            weights["siegetank"] += 0.9
            weights["medivac"] += 0.8
            weights["cyclone"] += 0.6
            weights["thor"] += 0.6
            weights["viking"] += 0.5
            weights["banshee"] += 0.4
            weights["marine"] = max(0.4, weights["marine"] * 0.6)
        elif minerals > 650 and vespene < 150:
            # Mineral surplus & gas shortage -> Dump minerals into marines & hellions
            weights["marine"] += 0.6
            weights["hellion"] += 0.5
        elif minerals > 750 and vespene > 400 and game_time > 480:
            weights["battlecruiser"] += 0.6
            weights["thor"] += 0.5

        # 8. Early-game scout / harassment
        if game_time < 240 and weights["reaper"] > 0.4:
            weights["reaper"] += 0.3

        # Clamp weights to minimum 0.1
        for u in weights:
            weights[u] = round(max(0.1, weights[u]), 3)

        return weights

    def update_after_match(
        self,
        enemy_race: str,
        result: str,
        duration: float,
        units_built: Dict[str, int],
        fitness_breakdown: Any = None,
    ):
        """Reinforcement Learning update for unit weights based on composite fitness, resource trade ratio, and spending efficiency."""
        norm_race = enemy_race.upper() if enemy_race else "DEFAULT"
        if norm_race not in self.race_weights:
            norm_race = "DEFAULT"

        current = self.race_weights[norm_race]
        total_built = max(1, sum(units_built.values()))

        # Calculate unit production proportions
        proportions = {u: units_built.get(u, 0) / total_combat_units if (total_combat_units := total_built) else 0.0 for u in ALL_16_UNITS}

        # Parse fitness metrics if provided
        if fitness_breakdown is not None:
            if hasattr(fitness_breakdown, "to_dict"):
                fb = fitness_breakdown.to_dict()
            elif isinstance(fitness_breakdown, dict):
                fb = fitness_breakdown
            else:
                fb = {}
        else:
            fb = {}

        composite_score = fb.get("composite_score", 100.0 if result == "Victory" else -35.0)
        trade_ratio = fb.get("trade_ratio", 1.5 if result == "Victory" else 0.7)
        spending_ratio = fb.get("spending_ratio", 0.85)
        vespene_spending_ratio = fb.get("vespene_spending_ratio", 0.70)
        synergy_score = fb.get("synergy_score", 0.0)
        diversity_score = fb.get("diversity_score", 0.0)

        # 1. Balanced Trade & Synergy Reinforcement:
        # Avoid the "Matthew Effect" (rich-get-richer) where 95% marine spam hogs 100% of the reward!
        if trade_ratio >= 1.05 or composite_score > 15.0:
            trade_multiplier = min(2.5, max(1.0, trade_ratio))
            for u in ALL_16_UNITS:
                if proportions[u] > 0.02:
                    # Capped presence bonus so mono-units cannot monopolize the gradient
                    bonus = 0.08 * min(0.35, proportions[u] + 0.1) * trade_multiplier
                    current[u] = min(3.0, current[u] + bonus)
                # Exploration Reward: If team had good synergy/trade, encourage tech units
                elif u in ("siegetank", "medivac", "thor", "viking", "cyclone", "banshee") and composite_score > 20.0:
                    current[u] = min(2.5, current[u] + 0.06)

            # Long game capital tech reinforcement
            if duration > 600 and composite_score > 30.0:
                current["battlecruiser"] = min(2.5, current["battlecruiser"] + 0.15)
                current["thor"] = min(2.5, current["thor"] + 0.15)

        # 2. Deficit Trade & Mono-Spam Penalty:
        # If we suffered losses or had poor diversity / negative synergy, penalize over-used mono units
        if (trade_ratio < 0.85 and composite_score < 0) or diversity_score < -5.0:
            for u in ALL_16_UNITS:
                if proportions[u] > 0.25:  # Over-relied unit in a losing game
                    current[u] = max(0.3, current[u] - 0.15)
                elif u in ("siegetank", "medivac", "thor", "viking", "cyclone", "marauder"):
                    current[u] = min(2.5, current[u] + 0.15)

        # 3. Gas-Utilization Balancing:
        # If gas was wasted (vespene_spending_ratio < 0.65 or high gas float), boost gas-heavy units!
        if vespene_spending_ratio < 0.65 or fb.get("float_penalty", 0) > 10.0:
            for gas_unit in ("siegetank", "medivac", "thor", "cyclone", "viking", "raven", "banshee"):
                current[gas_unit] = min(2.5, current[gas_unit] + 0.14)
            current["marine"] = max(0.4, current["marine"] - 0.12)

        # 4. Intrinsic Curiosity & Anti-Extinction Floor (Quality-Diversity):
        # Guarantee that under-represented key tech units never extinguish
        for u in ("siegetank", "medivac", "thor", "viking", "cyclone", "widowmine", "hellbat"):
            if current[u] < 0.65:
                current[u] = 0.65

        # 5. Exploration Noise: 15% chance to perturb weights slightly (prevents local optima)
        if random.random() < 0.15:
            random_unit = random.choice(ALL_16_UNITS)
            delta = random.choice([-0.1, 0.12, 0.18])
            current[random_unit] = round(max(0.2, min(2.8, current[random_unit] + delta)), 3)

        # 6. Normalize so average weight remains around 1.0
        avg_w = sum(current.values()) / len(current)
        if avg_w > 0:
            for u in current:
                current[u] = round(current[u] / avg_w, 3)

        self.race_weights[norm_race] = current
        self._save_weights(self.race_weights)

