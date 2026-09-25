"""StarCraft II Multi-Objective Composite Fitness & Resource Efficiency Evaluation Engine.

Rationally evaluates bot performance beyond simple binary Win/Defeat:
1. Economic Resource Efficiency (Spending Ratio & Unspent Floating Bank Penalty)
2. Combat Trade Efficiency (Killed Army Value vs Lost Army Value Ratio)
3. Micro Tactical Efficiency (Damage Dealt vs Damage Taken Ratio + Healing)
4. Game Outcome (Victory / Defeat / Tie baseline)
"""

import math
from dataclasses import dataclass, field, asdict
from typing import Dict, Any, List, Optional


@dataclass
class MatchMetrics:
    """Raw match metrics extracted from SC2 ScoreDetails and runtime samples."""
    game_num: int = 0
    result: str = "Unknown"             # Victory, Defeat, Tie
    duration_sec: float = 0.0
    enemy_race: str = "Unknown"
    difficulty: str = "veryhard"
    mode: str = "1v1"
    map_name: str = ""

    # Economic metrics (ScoreDetails + sampling)
    collected_minerals: int = 0
    collected_vespene: int = 0
    spent_minerals: int = 0
    spent_vespene: int = 0
    avg_unspent_minerals: float = 0.0
    avg_unspent_vespene: float = 0.0
    idle_production_time: float = 0.0
    idle_worker_time: float = 0.0

    # Combat trade metrics (ScoreDetails)
    killed_minerals_army: int = 0
    killed_vespene_army: int = 0
    lost_minerals_army: int = 0
    lost_vespene_army: int = 0
    killed_value_units: int = 0
    killed_value_structures: int = 0
    total_damage_dealt: float = 0.0
    total_damage_taken: float = 0.0
    total_healed: float = 0.0

    # Composition
    units_produced: Dict[str, int] = field(default_factory=dict)


@dataclass
class FitnessBreakdown:
    """Detailed breakdown of multi-objective composite fitness score."""
    composite_score: float = 0.0       # Final composite fitness
    result_score: float = 0.0          # Outcome base (+100 / -35 / 0)
    trade_score: float = 0.0           # Combat cost-exchange score (-50 ~ +100)
    econ_score: float = 0.0            # Economic spending efficiency score (-40 ~ +40)
    micro_score: float = 0.0           # Tactical combat & damage ratio score (-20 ~ +30)

    # Detailed diagnostic ratios
    trade_ratio: float = 1.0           # killed_value / lost_value
    spending_ratio: float = 0.0        # total_spent / total_collected
    damage_ratio: float = 1.0          # damage_dealt / damage_taken
    float_penalty: float = 0.0         # Penalty for sitting on unspent bank
    idle_penalty: float = 0.0          # Penalty for idle production/workers

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def calculate_fitness(m: MatchMetrics) -> FitnessBreakdown:
    """Calculates a rational multi-objective fitness score for the match.
    
    Principles:
    - StarCraft is an economy and trade game:
      1. High spending efficiency (SQ): Resources collected must be converted into army/tech without floating.
      2. High combat exchange rate: Killing 2,000 resources while losing 1,000 is profitable, even if the match ended in defeat.
      3. Focus-fire / micro efficiency: High damage dealt vs taken indicates effective tactical execution.
      4. Victory reward: Winning is the ultimate objective, but bad wins are penalized and heroic losses are rewarded.
    """
    res = m.result.capitalize() if m.result else "Unknown"

    # 1. Base Outcome Score
    if res == "Victory":
        result_score = 100.0
    elif res == "Defeat":
        result_score = -35.0
    elif res == "Tie":
        result_score = 0.0
    else:
        result_score = -10.0

    # 2. Combat Trade Efficiency (가성비 / 교전 교환비)
    # Gas is weighted 1.25x because vespene is harder to gather and crucial for high-tier tech/units.
    killed_val = float(m.killed_minerals_army) + 1.25 * float(m.killed_vespene_army)
    if killed_val == 0 and m.killed_value_units > 0:
        killed_val = float(m.killed_value_units)

    lost_val = float(m.lost_minerals_army) + 1.25 * float(m.lost_vespene_army)
    # Floor denominator to avoid division by zero or inflated ratios in very short games
    effective_lost = max(150.0, lost_val)
    trade_ratio = round(killed_val / effective_lost, 3)

    if trade_ratio >= 1.0:
        # Profitable exchange: +50 points per 1.0x ratio above break-even, capped at +100
        trade_score = min(100.0, 50.0 * (trade_ratio - 1.0))
    else:
        # Unfavorable exchange: negative score proportional to deficit
        trade_score = max(-50.0, -50.0 * (1.0 - trade_ratio))
    trade_score = round(trade_score, 2)

    # 3. Economic Spending Efficiency (자원 소모율 / Spending Quotient)
    total_collected = max(0, m.collected_minerals + m.collected_vespene)
    total_spent = max(0, m.spent_minerals + m.spent_vespene)
    spending_ratio = round(total_spent / max(1, total_collected), 3)

    # Ideal spending ratio is 85% ~ 98% (reserving minor buffer for sudden production cycles)
    base_econ = 40.0 * min(1.0, spending_ratio / 0.85)

    # Floating Resource Penalty: Sitting on > 600 average unspent minerals is severely penalized
    float_penalty = 0.0
    if m.avg_unspent_minerals > 600.0:
        excess = m.avg_unspent_minerals - 600.0
        float_penalty = min(35.0, excess / 40.0)
    if m.avg_unspent_vespene > 400.0:
        excess_gas = m.avg_unspent_vespene - 400.0
        float_penalty = min(40.0, float_penalty + excess_gas / 30.0)
    float_penalty = round(float_penalty, 2)

    # Idle Production & Worker Penalty
    idle_penalty = min(15.0, (m.idle_production_time + m.idle_worker_time) / 45.0)
    idle_penalty = round(idle_penalty, 2)

    econ_score = round(base_econ - float_penalty - idle_penalty, 2)

    # 4. Tactical / Combat Micro Efficiency (피해량 교환비 및 마이크로 보존력)
    dmg_dealt = max(0.0, m.total_damage_dealt)
    dmg_taken = max(100.0, m.total_damage_taken)
    damage_ratio = round(dmg_dealt / dmg_taken, 3)

    if damage_ratio >= 1.0:
        micro_score = min(25.0, 20.0 * (damage_ratio - 1.0))
    else:
        micro_score = max(-20.0, -20.0 * (1.0 - damage_ratio))

    # Medivac / repair support bonus
    if m.total_healed > 0:
        heal_bonus = min(10.0, m.total_healed / 250.0)
        micro_score += heal_bonus
    micro_score = round(micro_score, 2)

    # 5. Composite Multi-Objective Fitness
    composite = round(result_score + trade_score + econ_score + micro_score, 2)

    return FitnessBreakdown(
        composite_score=composite,
        result_score=result_score,
        trade_score=trade_score,
        econ_score=econ_score,
        micro_score=micro_score,
        trade_ratio=trade_ratio,
        spending_ratio=spending_ratio,
        damage_ratio=damage_ratio,
        float_penalty=float_penalty,
        idle_penalty=idle_penalty,
    )


def extract_metrics_from_bot(bot: Any, game_result: Any, duration_sec: float) -> MatchMetrics:
    """Safely extracts comprehensive MatchMetrics from a live python-sc2 bot instance."""
    metrics = MatchMetrics(
        duration_sec=round(duration_sec, 1),
        enemy_race=getattr(bot, "actual_enemy_race", "Unknown"),
    )

    if hasattr(game_result, "name"):
        metrics.result = game_result.name.capitalize()
    else:
        metrics.result = str(game_result)

    # Strategy / Mode metadata
    strat = getattr(bot, "strategy", None)
    if strat:
        metrics.difficulty = getattr(strat, "difficulty", "veryhard")
    metrics.units_produced = dict(getattr(bot, "units_produced_tracker", {}))

    # Average unspent bank from bot sampling
    unspent_m = getattr(bot, "unspent_minerals_samples", [])
    if unspent_m:
        metrics.avg_unspent_minerals = round(sum(unspent_m) / len(unspent_m), 1)
    else:
        metrics.avg_unspent_minerals = float(getattr(bot, "minerals", 0))

    unspent_v = getattr(bot, "unspent_vespene_samples", [])
    if unspent_v:
        metrics.avg_unspent_vespene = round(sum(unspent_v) / len(unspent_v), 1)
    else:
        metrics.avg_unspent_vespene = float(getattr(bot, "vespene", 0))

    # Extract official SC2 engine ScoreDetails
    state = getattr(bot, "state", None)
    score = getattr(state, "score", None) if state else None

    if score is not None:
        try:
            metrics.collected_minerals = int(getattr(score, "collected_minerals", 0))
            metrics.collected_vespene = int(getattr(score, "collected_vespene", 0))
            metrics.spent_minerals = int(getattr(score, "spent_minerals", 0))
            metrics.spent_vespene = int(getattr(score, "spent_vespene", 0))

            metrics.killed_minerals_army = int(getattr(score, "killed_minerals_army", 0))
            metrics.killed_vespene_army = int(getattr(score, "killed_vespene_army", 0))
            metrics.lost_minerals_army = int(getattr(score, "lost_minerals_army", 0))
            metrics.lost_vespene_army = int(getattr(score, "lost_vespene_army", 0))

            metrics.killed_value_units = int(getattr(score, "killed_value_units", 0))
            metrics.killed_value_structures = int(getattr(score, "killed_value_structures", 0))

            dealt_life = float(getattr(score, "total_damage_dealt_life", 0.0))
            dealt_shields = float(getattr(score, "total_damage_dealt_shields", 0.0))
            metrics.total_damage_dealt = dealt_life + dealt_shields

            taken_life = float(getattr(score, "total_damage_taken_life", 0.0))
            taken_shields = float(getattr(score, "total_damage_taken_shields", 0.0))
            metrics.total_damage_taken = taken_life + taken_shields

            metrics.total_healed = float(getattr(score, "total_healed_life", 0.0))
            metrics.idle_production_time = float(getattr(score, "idle_production_time", 0.0))
            metrics.idle_worker_time = float(getattr(score, "idle_worker_time", 0.0))
        except Exception:
            pass

    return metrics
