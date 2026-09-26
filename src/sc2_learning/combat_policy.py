"""Autonomous Combat Micro Policy & Tactical Skill Reinforcement Engine.

Learns and optimizes tactical execution parameters:
- Focus Fire accuracy (프로게이머 수준의 1점사 집결도)
- Stutter-step / Kiting distance (카이팅 무빙샷 거리)
- Damaged unit retreat (체력 빠진 유닛 뒤로 빼기 컨트롤)
- Skill trigger thresholds (스팀팩, 야마토포, EMP, 천공발톱 시전 타이밍)
- Siege Tank distance triggers (공성 모드 전환 전술 거리)
"""

import os
import json
import random
from typing import Dict, Any

COMBAT_POLICY_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "learning_stats",
    "combat_policy.json",
)

DEFAULT_COMBAT_POLICY: Dict[str, Dict[str, float]] = {
    "TERRAN": {
        "focus_fire_rate": 0.85,         # 1점사 집중 확률 (0.5 ~ 1.0)
        "kiting_distance": 3.2,          # 근접 유닛 상대 무빙샷 후퇴 거리 (1.5 ~ 4.5)
        "stim_health_threshold": 22.0,   # 스팀팩 사용 최소 체력 (15 ~ 35)
        "retreat_hp_pct": 0.28,          # 빈사 유닛 일시 후방 빼기 체력 비율 (0.1 ~ 0.4)
        "yamato_min_hp": 180.0,          # 야마토포 저격 대상 최소 체력/실드 (120 ~ 300)
        "emp_energy_shield": 40.0,       # EMP 시전 적 실드/마나 임계값 (25 ~ 70)
        "tank_siege_range": 12.5,        # 공성전차 시즈모드 전환 거리 (9.0 ~ 14.0)
        "snipe_hp_threshold": 120.0,     # 유령 저격 대상 최소 생체 체력 (80 ~ 200)
    },
    "PROTOSS": {
        "focus_fire_rate": 0.90,
        "kiting_distance": 3.4,
        "stim_health_threshold": 20.0,
        "retreat_hp_pct": 0.30,
        "yamato_min_hp": 200.0,
        "emp_energy_shield": 35.0,       # 프로토스전 EMP 민감도 대폭 증가
        "tank_siege_range": 13.0,
        "snipe_hp_threshold": 100.0,
    },
    "ZERG": {
        "focus_fire_rate": 0.80,         # 저그 떼거지 상대 분산 및 광역 대응
        "kiting_distance": 3.6,          # 맹독충/저글링 상대 카이팅 거리 확대
        "stim_health_threshold": 24.0,
        "retreat_hp_pct": 0.25,
        "yamato_min_hp": 220.0,          # 울트라리스크/무리군주 등 거대 저격
        "emp_energy_shield": 45.0,
        "tank_siege_range": 12.0,
        "snipe_hp_threshold": 150.0,     # 울트라리스크 저격 집중
    },
    "DEFAULT": {
        "focus_fire_rate": 0.85,
        "kiting_distance": 3.3,
        "stim_health_threshold": 22.0,
        "retreat_hp_pct": 0.28,
        "yamato_min_hp": 180.0,
        "emp_energy_shield": 40.0,
        "tank_siege_range": 12.5,
        "snipe_hp_threshold": 120.0,
    },
}


class CombatPolicyOptimizer:
    """Manages persistent tactical micro parameters and tunes them via Reinforcement Learning."""

    def __init__(self):
        self.file_path = COMBAT_POLICY_FILE
        os.makedirs(os.path.dirname(self.file_path), exist_ok=True)
        self.policies = self._load_policies()

    def _load_policies(self) -> Dict[str, Dict[str, float]]:
        """Loads combat policies from disk or seeds defaults."""
        if os.path.exists(self.file_path):
            try:
                with open(self.file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for race in ["TERRAN", "PROTOSS", "ZERG", "DEFAULT"]:
                        if race not in data:
                            data[race] = dict(DEFAULT_COMBAT_POLICY.get(race, DEFAULT_COMBAT_POLICY["DEFAULT"]))
                    return data
            except Exception:
                pass

        init_data = {r: dict(p) for r, p in DEFAULT_COMBAT_POLICY.items()}
        self._save_policies(init_data)
        return init_data

    def _save_policies(self, data: Dict[str, Dict[str, float]]):
        """Safely saves policies to JSON."""
        tmp = self.file_path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            os.replace(tmp, self.file_path)
        except Exception:
            pass

    def get_policy(self, enemy_race: str) -> Dict[str, float]:
        """Retrieves active micro policy parameters for the target match."""
        norm_race = enemy_race.upper() if enemy_race else "DEFAULT"
        if norm_race not in self.policies:
            norm_race = "DEFAULT"
        return dict(self.policies[norm_race])

    def update_after_match(
        self,
        enemy_race: str,
        result: str,
        duration: float,
        fitness_breakdown: Any = None,
    ):
        """Reinforces successful micro traits, mutates ineffective parameters based on combat trade & damage ratio."""
        norm_race = enemy_race.upper() if enemy_race else "DEFAULT"
        if norm_race not in self.policies:
            norm_race = "DEFAULT"

        policy = self.policies[norm_race]

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

        damage_ratio = fb.get("damage_ratio", 1.3 if result == "Victory" else 0.75)
        trade_ratio = fb.get("trade_ratio", 1.4 if result == "Victory" else 0.7)
        micro_score = fb.get("micro_score", 10.0 if result == "Victory" else -5.0)
        critical_hp_penalty = fb.get("critical_hp_penalty", 0.0)

        # 1. Effective Tactical Combat (Good damage exchange & unit preservation)
        if damage_ratio >= 1.05 or trade_ratio >= 1.05 or micro_score > 5.0:
            # Consolidate high-skill focus fire and sharp kiting
            policy["focus_fire_rate"] = round(min(0.98, policy["focus_fire_rate"] + 0.02), 3)
            # Slight random fine-tuning for continuous refinement
            policy["kiting_distance"] = round(max(2.0, min(4.5, policy["kiting_distance"] + random.uniform(-0.08, 0.08))), 2)
            policy["retreat_hp_pct"] = round(max(0.18, min(0.38, policy["retreat_hp_pct"] + random.uniform(-0.015, 0.015))), 2)

        # 2. Ineffective Tactical Combat (Heavy damage taken or poor cost trade)
        else:
            # Defeat / poor trade: explore different tactical micro trade-offs
            # 1. Adjust focus fire (prevent over-focus overkill or lack of focus)
            policy["focus_fire_rate"] = round(max(0.60, min(0.95, policy["focus_fire_rate"] + random.choice([-0.05, 0.04]))), 3)
            # 2. Adjust kiting spacing to keep safer distance
            policy["kiting_distance"] = round(max(2.2, min(4.4, policy["kiting_distance"] + random.choice([-0.15, 0.25]))), 2)
            # 3. Adjust stim health margin
            policy["stim_health_threshold"] = round(max(18.0, min(32.0, policy["stim_health_threshold"] + random.choice([-2.0, 2.0]))), 1)
            # 4. Adjust skill sensitivity
            policy["yamato_min_hp"] = round(max(130.0, min(260.0, policy["yamato_min_hp"] + random.choice([-15.0, 15.0]))), 1)
            policy["emp_energy_shield"] = round(max(25.0, min(65.0, policy["emp_energy_shield"] + random.choice([-5.0, 5.0]))), 1)

        # 3. Critical HP Penalty Adaptation (유닛 빈사 감점 발생 시 피 관리 강화)
        if critical_hp_penalty >= 4.5:
            # 빈사 유닛이 너무 많이 발생함 -> 유닛 후방 빼기(살리기) 기준 체력을 높이고 안전 거리 확보!
            policy["retreat_hp_pct"] = round(min(0.40, policy["retreat_hp_pct"] + 0.03), 2)
            policy["kiting_distance"] = round(min(4.5, policy["kiting_distance"] + 0.15), 2)
            policy["stim_health_threshold"] = round(min(32.0, policy["stim_health_threshold"] + 2.0), 1)

        self.policies[norm_race] = policy
        self._save_policies(self.policies)

