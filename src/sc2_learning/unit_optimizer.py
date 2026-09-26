"""Autonomous Hybrid Unit Composition Optimizer & Reinforcement Learning Engine for SC2.

Combines:
1. Meta-Learning (RL / Genetic Weight Optimization across matches per enemy race)
2. In-Game Real-Time Reactive Counter Adaptation (Enemy army observation & Scouted Tech -> Dynamic weight shift)
"""

import os
import json
import random
from typing import Dict, Any, Optional

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
    "ZERG+PROTOSS": {
        "marine": 1.1, "reaper": 0.3, "marauder": 1.3, "ghost": 0.9,
        "hellion": 0.5, "hellbat": 0.9, "widowmine": 0.7, "cyclone": 0.8, "siegetank": 1.3, "thor": 1.1,
        "viking": 1.2, "medivac": 1.0, "liberator": 0.7, "raven": 0.7, "banshee": 0.5, "battlecruiser": 0.8,
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

    def _normalize_race_key(self, enemy_race: str) -> str:
        """Standardizes race names into dictionary keys."""
        if not enemy_race:
            return "DEFAULT"
        norm = enemy_race.upper()
        if "ZERG" in norm and "PROTOSS" in norm:
            return "ZERG+PROTOSS"
        if "PROTOSS" in norm:
            return "PROTOSS"
        if "ZERG" in norm:
            return "ZERG"
        if "TERRAN" in norm:
            return "TERRAN"
        return "DEFAULT"

    def _load_weights(self) -> Dict[str, Dict[str, float]]:
        """Loads weights from persistent JSON or initializes defaults."""
        if os.path.exists(self.weights_file):
            try:
                with open(self.weights_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    # Validate all expected races and units exist
                    for race in ["TERRAN", "PROTOSS", "ZERG", "ZERG+PROTOSS", "DEFAULT"]:
                        if race not in data:
                            data[race] = dict(DEFAULT_BASE_WEIGHTS.get(race, DEFAULT_BASE_WEIGHTS["DEFAULT"]))
                        for u in ALL_16_UNITS:
                            if u not in data[race]:
                                data[race][u] = DEFAULT_BASE_WEIGHTS.get(race, DEFAULT_BASE_WEIGHTS["DEFAULT"]).get(u, 0.5)
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
        seen_enemy_structures: Optional[Any] = None,
    ) -> Dict[str, float]:
        """Calculates real-time effective unit utility weights: Base learned weight + scouted tech & observation deltas."""
        norm_race = self._normalize_race_key(enemy_race)
        weights = dict(self.race_weights.get(norm_race, self.race_weights["DEFAULT"]))

        # =====================================================================
        # 1. Predictive Tech-Counter Adjustments based on Scouted Enemy Structures
        # (Fog of War 관통: 정찰 및 스캔으로 파악한 적 핵심 생산/테크 건물 사전 카운터)
        # =====================================================================
        if seen_enemy_structures:
            struct_names = {getattr(s, "name", str(s)).upper() for s in seen_enemy_structures}

            # [Zerg Tech Counters]
            if "SPIRE" in struct_names or "GREATERSPIRE" in struct_names:
                # 뮤탈리스크/무리군주 등 공중 위협 확정 -> 바이킹/토르 긴급 증산!
                weights["viking"] += 0.85
                weights["thor"] += 0.80
            if "ROACHWARREN" in struct_names or "BANELINGNEST" in struct_names:
                # 바퀴/맹독충 러시 -> 공성전차 및 화염기갑병/불곰 즉각 보강
                weights["siegetank"] += 0.75
                weights["hellbat"] += 0.65
                weights["marauder"] += 0.50
            if "HYDRALISKDEN" in struct_names or "LURKERDEN" in struct_names or "LURKERDENMP" in struct_names:
                # 히드라/잠복 가시지옥 -> 밤까마귀(탐지) 및 공성전차/해방선 필수
                weights["siegetank"] += 0.70
                weights["raven"] += 0.85
                weights["liberator"] += 0.60
            if "ULTRALISKCAVERN" in struct_names or "HIVE" in struct_names:
                # 울트라리스크 등 거대괴수 -> 토르/유령/해방선 준비
                weights["thor"] += 0.75
                weights["ghost"] += 0.75
                weights["liberator"] += 0.60

            # [Protoss Tech Counters]
            if "STARGATE" in struct_names or "FLEETBEACON" in struct_names:
                # 우주관문 (공허포격기, 예언자, 우주모함) -> 바이킹/사이클론/토르 대공망 가동!
                weights["viking"] += 0.90
                weights["cyclone"] += 0.60
                weights["thor"] += 0.55
            if "ROBOTICSFACILITY" in struct_names or "ROBOTICSBAY" in struct_names:
                # 로봇공학시설 (거신, 불멸자) -> 거신 저격용 바이킹 + 추적자/불멸자 파쇄 불곰
                weights["marauder"] += 0.75
                weights["viking"] += 0.80
                weights["siegetank"] += 0.50
            if "TWILIGHTCOUNCIL" in struct_names or "DARKSHRINE" in struct_names or "TEMPLARARCHIVE" in struct_names:
                # 암흑기사(은폐) 및 고위기사(사이오닉 폭풍) -> EMP 유령 및 탐지용 밤까마귀
                weights["ghost"] += 1.00
                weights["raven"] += 0.85

            # [Terran Tech Counters]
            if "STARPORT" in struct_names or "STARPORTTECHLAB" in struct_names:
                # 밴시(은폐) 및 공중 전력 -> 바이킹 및 탐지용 밤까마귀
                weights["viking"] += 0.70
                weights["raven"] += 0.85
            if "FACTORY" in struct_names or "FACTORYTECHLAB" in struct_names:
                # 테테전 공성전차 라인 배틀 -> 맞공성전차 및 시야용 바이킹/방해매트릭스 밤까마귀
                weights["siegetank"] += 0.85
                weights["viking"] += 0.65
                weights["raven"] += 0.75
            if "FUSIONCORE" in struct_names:
                # 전투순양함(야마토포) -> 방해매트릭스 밤까마귀 + 대공 바이킹 집중
                weights["viking"] += 0.90
                weights["raven"] += 0.90
                weights["cyclone"] += 0.50

        # =====================================================================
        # 2. Real-time Counter Adjustments based on Visible Enemy Army Units
        # =====================================================================
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

        # =====================================================================
        # 3. Macro Resource State Awareness (Wallet Balancing)
        # =====================================================================
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

        # 4. Early-game scout / harassment
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
        norm_race = self._normalize_race_key(enemy_race)
        current = self.race_weights.get(norm_race, self.race_weights["DEFAULT"])
        total_built = max(1, sum(units_built.values()))

        # Calculate unit production proportions
        proportions = {u: units_built.get(u, 0) / total_built for u in ALL_16_UNITS}

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
        diversity_score = fb.get("diversity_score", 0.0)

        # 1. Balanced Trade & Synergy Reinforcement:
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
        if (trade_ratio < 0.85 and composite_score < 0) or diversity_score < -5.0:
            for u in ALL_16_UNITS:
                if proportions[u] > 0.25:  # Over-relied unit in a losing game
                    current[u] = max(0.3, current[u] - 0.15)
                elif u in ("siegetank", "medivac", "thor", "viking", "cyclone", "marauder"):
                    current[u] = min(2.5, current[u] + 0.15)

        # 3. Gas-Utilization Balancing:
        if vespene_spending_ratio < 0.65 or fb.get("float_penalty", 0) > 10.0:
            for gas_unit in ("siegetank", "medivac", "thor", "cyclone", "viking", "raven", "banshee"):
                current[gas_unit] = min(2.5, current[gas_unit] + 0.14)
            current["marine"] = max(0.4, current["marine"] - 0.12)

        # 4. Unit Health Preservation & Durability Reinforcement:
        hp_penalty = fb.get("hp_preservation_penalty", 0.0)
        hp_recovery = fb.get("hp_recovery_bonus", 0.0)
        if hp_penalty >= 8.0:
            # High red-line casualties -> prioritize Medivacs for triage healing and Marauders for durable frontline buffer
            current["medivac"] = min(2.5, current["medivac"] + 0.15)
            current["marauder"] = min(2.5, current["marauder"] + 0.12)
        elif hp_recovery >= 5.0:
            # Effective field triage & rescue observed -> reward and maintain medivac support
            current["medivac"] = min(2.5, current["medivac"] + 0.08)

        # 5. Intrinsic Curiosity & Anti-Extinction Floor:
        for u in ("siegetank", "medivac", "thor", "viking", "cyclone", "widowmine", "hellbat"):
            if current[u] < 0.65:
                current[u] = 0.65

        # 6. Exploration Noise: 15% chance to perturb weights slightly (prevents local optima)
        if random.random() < 0.15:
            random_unit = random.choice(ALL_16_UNITS)
            delta = random.choice([-0.1, 0.12, 0.18])
            current[random_unit] = round(max(0.2, min(2.8, current[random_unit] + delta)), 3)

        # 7. Normalize so average weight remains around 1.0
        avg_w = sum(current.values()) / len(current)
        if avg_w > 0:
            for u in current:
                current[u] = round(current[u] / avg_w, 3)

        self.race_weights[norm_race] = current
        self._save_weights(self.race_weights)
