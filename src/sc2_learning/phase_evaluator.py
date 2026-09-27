"""Phase Evaluation & Opponent Benchmarking Engine for StarCraft II Bot.

Divides game performance into 9 strategic categories:
  3 Enemy Races (Terran, Protoss, Zerg) x 3 Game Phases (Early: 0-4m, Mid: 4-9m, Late: 9m+)
Provides comprehensive side-by-side benchmarking against the opponent and actionable AI coaching.
"""

import os
import json
import time
from dataclasses import dataclass, field, asdict
from typing import Dict, Any, List, Optional

MATRIX_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "learning_stats",
    "phase_matrix.json",
)

EARLY_PHASE_END = 240.0  # 4:00 in seconds
MID_PHASE_END = 540.0    # 9:00 in seconds

VALID_RACES = ["TERRAN", "PROTOSS", "ZERG"]
PHASE_KEYS = ["early", "mid", "late"]
PHASE_NAMES = {
    "early": "초반 (0~4분)",
    "mid": "중반 (4~9분)",
    "late": "종반 (9분+)",
}


def compute_grade(score: float) -> str:
    """Returns a letter grade based on a 0-100 score."""
    if score >= 90.0:
        return "S"
    elif score >= 80.0:
        return "A"
    elif score >= 70.0:
        return "B"
    elif score >= 60.0:
        return "C"
    return "D"


def normalize_race_name(race: str) -> str:
    """Normalizes race string to TERRAN, PROTOSS, or ZERG."""
    if not race:
        return "ZERG"
    r = str(race).upper()
    if "TERRAN" in r:
        return "TERRAN"
    if "PROTOSS" in r:
        return "PROTOSS"
    if "ZERG" in r:
        return "ZERG"
    return "ZERG"


@dataclass
class MatchPhaseScores:
    """Detailed score evaluation of a single match across its played phases."""
    enemy_race: str = "ZERG"
    duration_sec: float = 0.0
    result: str = "Unknown"

    early_score: Optional[float] = None
    early_grade: Optional[str] = None
    early_summary: str = ""

    mid_score: Optional[float] = None
    mid_grade: Optional[str] = None
    mid_summary: str = ""

    late_score: Optional[float] = None
    late_grade: Optional[str] = None
    late_summary: str = ""

    total_score: float = 0.0
    total_grade: str = "C"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class OpponentBenchmarkReport:
    """Comprehensive side-by-side benchmark comparing our bot against the opponent."""
    match_id: int = 0
    enemy_race: str = "ZERG"
    result: str = "Unknown"
    duration_str: str = "00:00"

    # 1. Combat & Resource Trade
    our_kills_val: int = 0
    enemy_kills_val: int = 0
    trade_diff: int = 0
    trade_ratio: float = 1.0
    trade_verdict: str = ""

    # 2. Damage & Firepower
    damage_dealt: float = 0.0
    damage_taken: float = 0.0
    damage_ratio: float = 1.0
    damage_verdict: str = ""

    # 3. Resource Economy & Spending
    collected_total: int = 0
    spent_total: int = 0
    spending_ratio: float = 0.0
    spending_verdict: str = ""

    # 4. Triage & Unit Preservation
    triage_saved: int = 0
    triage_lost: int = 0
    triage_rate: float = 0.0
    total_healed: float = 0.0
    triage_verdict: str = ""

    # 5. Strategic Structures
    enemy_structures_destroyed: int = 0

    # 6. AI Coach Diagnostic Verdict
    coach_strengths: List[str] = field(default_factory=list)
    coach_weaknesses: List[str] = field(default_factory=list)
    coach_recommendations: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def evaluate_early_phase(metrics: Any, duration_sec: float, result_str: str) -> tuple[float, str, str]:
    """Calculates early game (0-4m) score on a 0-100 scale."""
    dur = min(duration_sec, EARLY_PHASE_END)
    ratio = dur / EARLY_PHASE_END if EARLY_PHASE_END > 0 else 1.0

    score = 50.0  # Base line
    notes = []

    # 1. Economic / Worker baseline
    # Standard early saturation aims for 22-26 workers by 4m
    target_workers = max(12, int(12 + ratio * 13))
    actual_workers = getattr(metrics, "workers_produced", 0)
    if actual_workers == 0:
        # Fallback estimation from spent minerals if workers_produced not recorded
        spent_m = getattr(metrics, "spent_minerals", 0)
        actual_workers = min(26, max(12, 12 + int(spent_m / 200)))

    if actual_workers >= target_workers:
        bonus = min(15.0, (actual_workers - target_workers) * 2.0 + 10.0)
        score += bonus
        notes.append(f"SCV 생산 양호({actual_workers}기)")
    else:
        penalty = min(15.0, (target_workers - actual_workers) * 2.5)
        score -= penalty
        notes.append(f"SCV 증산 다소 지연(-{penalty:.0f})")

    # 2. Resource Float in early game
    avg_unspent_m = getattr(metrics, "avg_unspent_minerals", 0.0)
    if avg_unspent_m <= 250.0:
        score += 15.0
        notes.append("자원 잉여 없음(인프라 즉시전환)")
    elif avg_unspent_m <= 450.0:
        score += 5.0
    else:
        float_pen = min(15.0, (avg_unspent_m - 450.0) / 30.0)
        score -= float_pen
        notes.append(f"초반 미네랄 적체(-{float_pen:.0f})")

    # 3. Early Combat & Survival
    lost_val = getattr(metrics, "lost_minerals_army", 0) + getattr(metrics, "lost_vespene_army", 0)
    if duration_sec <= EARLY_PHASE_END and result_str == "Victory":
        score += 20.0
        notes.append("초반 러시 격퇴 및 즉각 승리")
    elif lost_val <= 300:
        score += 15.0
        notes.append("초반 병력 무결점 보존")
    elif lost_val <= 700:
        score += 5.0
    else:
        score -= min(15.0, (lost_val - 700) / 50.0)
        notes.append("초반 벙커/병력 손실 발생")

    # 4. Critical HP Preservation in early game
    saved = getattr(metrics, "critical_hp_units_saved", 0)
    lost_crit = getattr(metrics, "critical_hp_units_lost", 0)
    if saved > 0:
        score += min(10.0, saved * 3.0)
        notes.append(f"빈사 유닛 {saved}기 구출")
    if lost_crit > 0 and duration_sec <= EARLY_PHASE_END:
        score -= min(10.0, lost_crit * 2.5)

    final_score = round(max(10.0, min(100.0, score)), 1)
    grade = compute_grade(final_score)
    summary_str = ", ".join(notes[:3])
    return final_score, grade, summary_str


def evaluate_mid_phase(metrics: Any, duration_sec: float, result_str: str) -> tuple[Optional[float], Optional[str], str]:
    """Calculates mid game (4-9m) score on a 0-100 scale."""
    if duration_sec < EARLY_PHASE_END:
        return None, None, "미진행 (초반 종료)"

    score = 55.0
    notes = []

    # 1. Combat Cost Trade Ratio (중반 교전 가성비)
    killed_val = float(getattr(metrics, "killed_minerals_army", 0)) + 1.25 * float(getattr(metrics, "killed_vespene_army", 0))
    lost_val = float(getattr(metrics, "lost_minerals_army", 0)) + 1.25 * float(getattr(metrics, "lost_vespene_army", 0))
    trade_ratio = killed_val / max(200.0, lost_val)

    if trade_ratio >= 1.6:
        score += 25.0
        notes.append(f"교전 압도적 이득({trade_ratio:.2f}:1)")
    elif trade_ratio >= 1.1:
        score += 15.0
        notes.append(f"교전 우세 교환({trade_ratio:.2f}:1)")
    elif trade_ratio >= 0.85:
        score += 5.0
        notes.append(f"호각세 교전({trade_ratio:.2f}:1)")
    else:
        loss_pen = min(20.0, (1.0 - trade_ratio) * 35.0)
        score -= loss_pen
        notes.append(f"중반 교전 손실 발생({trade_ratio:.2f}:1)")

    # 2. Spending Efficiency (자원 소모율 & 가스 잉여 방지)
    tot_coll = max(1, getattr(metrics, "collected_minerals", 0) + getattr(metrics, "collected_vespene", 0))
    tot_spent = getattr(metrics, "spent_minerals", 0) + getattr(metrics, "spent_vespene", 0)
    spend_rate = tot_spent / tot_coll

    coll_v = max(1, getattr(metrics, "collected_vespene", 0))
    spent_v = getattr(metrics, "spent_vespene", 0)
    v_spend_rate = spent_v / coll_v

    if spend_rate >= 0.90 and v_spend_rate >= 0.75:
        score += 15.0
        notes.append(f"자원 소모율 극대화({spend_rate*100:.1f}%)")
    elif spend_rate >= 0.80:
        score += 8.0
    else:
        score -= min(15.0, (0.80 - spend_rate) * 50.0)
        notes.append(f"중반 자원 정체(-10)")

    # 3. Triage & Healing
    healed = getattr(metrics, "total_healed", 0.0)
    saved = getattr(metrics, "critical_hp_units_saved", 0)
    if healed > 300.0 or saved >= 3:
        score += 10.0
        notes.append(f"의료선 지원 및 {saved}기 구출")
    elif healed > 0.0:
        score += 5.0

    # 4. Damage Exchange
    dealt = getattr(metrics, "total_damage_dealt", 0.0)
    taken = max(100.0, getattr(metrics, "total_damage_taken", 0.0))
    dmg_ratio = dealt / taken
    if dmg_ratio >= 1.2:
        score += 10.0
    elif dmg_ratio < 0.6:
        score -= 10.0

    if duration_sec <= MID_PHASE_END and result_str == "Victory":
        score += 10.0
        notes.append("중반 타이밍 러시 승리")

    final_score = round(max(10.0, min(100.0, score)), 1)
    grade = compute_grade(final_score)
    summary_str = ", ".join(notes[:3])
    return final_score, grade, summary_str


def evaluate_late_phase(metrics: Any, duration_sec: float, result_str: str) -> tuple[Optional[float], Optional[str], str]:
    """Calculates late game (9m+) score on a 0-100 scale."""
    if duration_sec < MID_PHASE_END:
        return None, None, "미진행 (중반 이전 종료)"

    score = 55.0
    notes = []

    # 1. Victory & Decisive Conclusion
    if result_str == "Victory":
        score += 25.0
        notes.append("후반 승리 달성")
    elif result_str == "Defeat":
        score -= 15.0
        notes.append("후반 패배")

    # 2. Late Game Combat & Structures
    killed_val = float(getattr(metrics, "killed_minerals_army", 0)) + 1.25 * float(getattr(metrics, "killed_vespene_army", 0))
    lost_val = float(getattr(metrics, "lost_minerals_army", 0)) + 1.25 * float(getattr(metrics, "lost_vespene_army", 0))
    trade_ratio = killed_val / max(300.0, lost_val)

    if trade_ratio >= 1.4:
        score += 20.0
        notes.append(f"대회전 가성비 압도({trade_ratio:.2f}:1)")
    elif trade_ratio >= 1.0:
        score += 10.0
    else:
        score -= min(15.0, (1.0 - trade_ratio) * 25.0)

    # 3. Enemy Structure Destruction
    killed_structs = getattr(metrics, "killed_value_structures", 0)
    if killed_structs >= 2000:
        score += 15.0
        notes.append("적 핵심 본진/멀티 궤멸")
    elif killed_structs >= 600:
        score += 8.0

    # 4. Army Health Preservation in Late Game
    hp_ratio = getattr(metrics, "hp_preservation_ratio", 0.5)
    if hp_ratio >= 0.70:
        score += 10.0
        notes.append("잔존 부대 체력 우수(70%+)")
    elif hp_ratio < 0.35:
        score -= 10.0

    final_score = round(max(10.0, min(100.0, score)), 1)
    grade = compute_grade(final_score)
    summary_str = ", ".join(notes[:3])
    return final_score, grade, summary_str


def calculate_match_phase_scores(metrics: Any, duration_sec: float, result_str: str, enemy_race: str) -> MatchPhaseScores:
    """Calculates early, mid, late, and composite match scores."""
    norm_race = normalize_race_name(enemy_race)

    e_score, e_grade, e_sum = evaluate_early_phase(metrics, duration_sec, result_str)
    m_score, m_grade, m_sum = evaluate_mid_phase(metrics, duration_sec, result_str)
    l_score, l_grade, l_sum = evaluate_late_phase(metrics, duration_sec, result_str)

    # Compute overall total match score
    if m_score is None and l_score is None:
        # Early only match (< 240s)
        total = e_score * 0.7 + (30.0 if result_str == "Victory" else 10.0)
    elif l_score is None:
        # Early + Mid match (240s ~ 540s)
        total = (e_score * 0.40) + (m_score * 0.60)
    else:
        # Full late game match (> 540s)
        total = (e_score * 0.25) + (m_score * 0.35) + (l_score * 0.40)

    total = round(max(10.0, min(100.0, total)), 1)
    t_grade = compute_grade(total)

    return MatchPhaseScores(
        enemy_race=norm_race,
        duration_sec=round(duration_sec, 1),
        result=result_str,
        early_score=e_score,
        early_grade=e_grade,
        early_summary=e_sum,
        mid_score=m_score,
        mid_grade=m_grade,
        mid_summary=m_sum,
        late_score=l_score,
        late_grade=l_grade,
        late_summary=l_sum,
        total_score=total,
        total_grade=t_grade,
    )


def generate_opponent_benchmark(
    metrics: Any,
    duration_sec: float,
    result_str: str,
    enemy_race: str,
    phase_scores: MatchPhaseScores,
    game_num: int = 0,
) -> OpponentBenchmarkReport:
    """Produces detailed side-by-side benchmark diagnostics against the opponent."""
    norm_race = normalize_race_name(enemy_race)

    mins, secs = divmod(int(duration_sec), 60)
    dur_str = f"{mins:02d}:{secs:02d}"

    # 1. Combat & Resource Trade
    our_kills = int(getattr(metrics, "killed_minerals_army", 0) + 1.25 * getattr(metrics, "killed_vespene_army", 0))
    enemy_kills = int(getattr(metrics, "lost_minerals_army", 0) + 1.25 * getattr(metrics, "lost_vespene_army", 0))
    trade_diff = our_kills - enemy_kills
    trade_ratio = round(our_kills / max(150.0, float(enemy_kills)), 2)

    if trade_ratio >= 1.3:
        trade_verdict = f"상대 대비 +{trade_diff:,}원 우위 ({trade_ratio:.2f}:1 압도)"
    elif trade_ratio >= 1.0:
        trade_verdict = f"상대 대비 +{trade_diff:,}원 근소 우위 ({trade_ratio:.2f}:1)"
    else:
        trade_verdict = f"상대 대비 {trade_diff:,}원 열세 ({trade_ratio:.2f}:1)"

    # 2. Damage & Firepower
    dealt = float(getattr(metrics, "total_damage_dealt", 0.0))
    taken = float(getattr(metrics, "total_damage_taken", 0.0))
    damage_ratio = round(dealt / max(100.0, taken), 2)
    if damage_ratio >= 1.2:
        damage_verdict = f"화력 타격비 {damage_ratio:.2f}배 우세"
    elif damage_ratio >= 0.9:
        damage_verdict = f"화력 타격비 {damage_ratio:.2f}배 호각세"
    else:
        damage_verdict = f"화력 타격비 {damage_ratio:.2f}배 열세 (집중 사격 필요)"

    # 3. Resource Economy & Spending
    coll = getattr(metrics, "collected_minerals", 0) + getattr(metrics, "collected_vespene", 0)
    spent = getattr(metrics, "spent_minerals", 0) + getattr(metrics, "spent_vespene", 0)
    spending_rate = round(spent / max(1, coll), 3)
    if spending_rate >= 0.92:
        spending_verdict = f"자원 소모율 {spending_rate*100:.1f}% (탁월한 인프라 회전력)"
    elif spending_rate >= 0.82:
        spending_verdict = f"자원 소모율 {spending_rate*100:.1f}% (양호)"
    else:
        spending_verdict = f"자원 소모율 {spending_rate*100:.1f}% (생산 시설 추가 증설 요망)"

    # 4. Triage & Unit Preservation
    saved = int(getattr(metrics, "critical_hp_units_saved", 0))
    lost_crit = int(getattr(metrics, "critical_hp_units_lost", 0))
    total_crit = saved + lost_crit
    triage_rate = round((saved / max(1, total_crit)) * 100, 1)
    healed = float(getattr(metrics, "total_healed", 0.0))
    triage_verdict = f"{saved}기 응급 구출 성공 / {lost_crit}기 위험 손실 (회복 성공률 {triage_rate}%)"

    struct_destroyed = int(getattr(metrics, "killed_value_structures", 0))

    # 5. Dynamic AI Coach Insights
    strengths = []
    weaknesses = []
    recommendations = []

    if trade_ratio >= 1.15:
        strengths.append(f"교전 효율에서 상대를 {int((trade_ratio - 1.0) * 100)}% 압도했습니다.")
    if spending_rate >= 0.88:
        strengths.append(f"수집한 자원의 {spending_rate*100:.1f}%를 병력과 테크로 즉각 전환했습니다.")
    if saved >= 3:
        strengths.append(f"빨간 피(<=35%) 유닛 {saved}기를 의료선/수리로 안전하게 살려냈습니다.")
    if not strengths:
        strengths.append("초반 사령부 확장 및 기초 방어 벙커 라인을 안정적으로 유지했습니다.")

    if trade_ratio < 0.9:
        weaknesses.append("교전 시 무리한 돌격으로 상대 화망에 병력 손실이 발생했습니다.")
    if getattr(metrics, "avg_unspent_minerals", 0) > 400.0:
        weaknesses.append(f"중반 잉여 미네랄(평균 {int(getattr(metrics, 'avg_unspent_minerals', 0))})이 정체되었습니다.")
    if getattr(metrics, "avg_unspent_vespene", 0) > 250.0:
        weaknesses.append(f"가스 잔여량({int(getattr(metrics, 'avg_unspent_vespene', 0))}) 대비 군수공장/우주공항 유닛 생산이 지연되었습니다.")
    if lost_crit > 4:
        weaknesses.append(f"빈사 유닛 {lost_crit}기가 의료선 후퇴를 제때 못하고 전사했습니다.")
    if not weaknesses:
        weaknesses.append("전체적으로 안정적이었으나 대규모 교전 시 분산 진입을 주의해야 합니다.")

    # Race-specific actionable recommendation
    if norm_race == "ZERG":
        recommendations.append("저그전: 맹독충/저글링 쇄도를 막기 위해 화염기갑병과 시즈탱크 거치망을 전진 배치하세요.")
    elif norm_race == "PROTOSS":
        recommendations.append("프로토스전: 추적자/거신 상대 불곰 충격탄 카이팅과 바이킹 제공권 장악이 핵심입니다.")
    else:
        recommendations.append("테란전: 공성전차 라인 싸움 시 밤까마귀 방해매트릭스와 바이킹 시야 확보를 선점하세요.")

    if spending_rate < 0.85:
        recommendations.append("자원 축적 시 병영 2~3개와 군수공장을 즉시 추가 증설하여 병력 회전력을 높이세요.")

    return OpponentBenchmarkReport(
        match_id=game_num,
        enemy_race=norm_race,
        result=result_str,
        duration_str=dur_str,
        our_kills_val=our_kills,
        enemy_kills_val=enemy_kills,
        trade_diff=trade_diff,
        trade_ratio=trade_ratio,
        trade_verdict=trade_verdict,
        damage_dealt=round(dealt, 1),
        damage_taken=round(taken, 1),
        damage_ratio=damage_ratio,
        damage_verdict=damage_verdict,
        collected_total=coll,
        spent_total=spent,
        spending_ratio=spending_rate,
        spending_verdict=spending_verdict,
        triage_saved=saved,
        triage_lost=lost_crit,
        triage_rate=triage_rate,
        total_healed=round(healed, 1),
        triage_verdict=triage_verdict,
        enemy_structures_destroyed=struct_destroyed,
        coach_strengths=strengths,
        coach_weaknesses=weaknesses,
        coach_recommendations=recommendations,
    )


class NineMatrixManager:
    """Maintains and persists the 9-Matrix Evaluation System (3 Enemy Races x 3 Phases) & Race Win Rates."""

    def __init__(self):
        self.matrix_file = MATRIX_FILE
        os.makedirs(os.path.dirname(self.matrix_file), exist_ok=True)
        self.data = self._load()

    def _default_data(self) -> Dict[str, Any]:
        data = {
            "matrix": {
                race: {
                    phase: {"count": 0, "avg_score": 75.0, "last_score": 75.0, "grade": "B", "scores": []}
                    for phase in PHASE_KEYS
                }
                for race in VALID_RACES
            },
            "race_stats": {
                race: {"games": 0, "wins": 0, "losses": 0, "ties": 0, "win_rate": 0.0}
                for race in VALID_RACES
            },
            "overall": {
                "total_games": 0,
                "wins": 0,
                "losses": 0,
                "win_rate": 0.0,
                "avg_score": 75.0,
            },
            "latest_match": None,
            "latest_benchmark": None,
        }
        return data

    def _load(self) -> Dict[str, Any]:
        if os.path.exists(self.matrix_file):
            try:
                with open(self.matrix_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        init_d = self._default_data()
        self._save(init_d)
        return init_d

    def _save(self, data: Optional[Dict[str, Any]] = None):
        if data is None:
            data = self.data
        try:
            tmp = self.matrix_file + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            os.replace(tmp, self.matrix_file)
        except Exception:
            pass

    def update_match(
        self,
        phase_scores: MatchPhaseScores,
        benchmark: OpponentBenchmarkReport,
        result_str: str,
        enemy_race: str,
    ):
        """Updates the 9-matrix scores and win rates with a completed match."""
        race = normalize_race_name(enemy_race)

        # 1. Update Win Rates
        rs = self.data["race_stats"][race]
        rs["games"] += 1
        if result_str == "Victory":
            rs["wins"] += 1
        elif result_str == "Defeat":
            rs["losses"] += 1
        else:
            rs["ties"] += 1
        rs["win_rate"] = round((rs["wins"] / max(1, rs["games"])) * 100, 1)

        # 2. Update Overall
        ov = self.data["overall"]
        ov["total_games"] += 1
        if result_str == "Victory":
            ov["wins"] += 1
        elif result_str == "Defeat":
            ov["losses"] += 1
        ov["win_rate"] = round((ov["wins"] / max(1, ov["total_games"])) * 100, 1)

        # 3. Update Matrix Phase Scores
        phases_to_update = [
            ("early", phase_scores.early_score),
            ("mid", phase_scores.mid_score),
            ("late", phase_scores.late_score),
        ]
        for p_key, p_score in phases_to_update:
            if p_score is not None:
                cell = self.data["matrix"][race][p_key]
                cell["count"] += 1
                cell["last_score"] = p_score
                cell["scores"].append(p_score)
                if len(cell["scores"]) > 20:
                    cell["scores"].pop(0)
                cell["avg_score"] = round(sum(cell["scores"]) / len(cell["scores"]), 1)
                cell["grade"] = compute_grade(cell["avg_score"])

        # Compute race average score across 3 phases
        race_scores = [self.data["matrix"][race][p]["avg_score"] for p in PHASE_KEYS if self.data["matrix"][race][p]["count"] > 0]
        if race_scores:
            self.data["matrix"][race]["avg"] = round(sum(race_scores) / len(race_scores), 1)

        # Update latest objects
        self.data["latest_match"] = phase_scores.to_dict()
        self.data["latest_benchmark"] = benchmark.to_dict()

        self._save()

    def backfill_from_history(self, history_records: List[Dict[str, Any]]):
        """Scans history.jsonl to populate the 9-matrix and race win rates with historical records."""
        # Reset counters
        self.data = self._default_data()

        for rec in history_records:
            r = normalize_race_name(rec.get("enemy_race", "ZERG"))
            res = rec.get("result", "Defeat")
            dur = float(rec.get("duration_sec", 0.0))
            metrics_dict = rec.get("metrics") or {}

            # Construct dummy metrics object
            class DummyMetrics:
                pass
            m = DummyMetrics()
            for k, v in metrics_dict.items():
                setattr(m, k, v)

            # Update race stats
            rs = self.data["race_stats"][r]
            rs["games"] += 1
            if res == "Victory":
                rs["wins"] += 1
            elif res == "Defeat":
                rs["losses"] += 1
            else:
                rs["ties"] += 1

            # Update overall
            ov = self.data["overall"]
            ov["total_games"] += 1
            if res == "Victory":
                ov["wins"] += 1
            elif res == "Defeat":
                ov["losses"] += 1

            # Phase scores
            ps = calculate_match_phase_scores(m, dur, res, r)
            for p_key, p_score in [("early", ps.early_score), ("mid", ps.mid_score), ("late", ps.late_score)]:
                if p_score is not None:
                    cell = self.data["matrix"][r][p_key]
                    cell["count"] += 1
                    cell["last_score"] = p_score
                    cell["scores"].append(p_score)
                    if len(cell["scores"]) > 20:
                        cell["scores"].pop(0)

        # Finalize averages
        for r in VALID_RACES:
            rs = self.data["race_stats"][r]
            rs["win_rate"] = round((rs["wins"] / max(1, rs["games"])) * 100, 1)
            for p in PHASE_KEYS:
                cell = self.data["matrix"][r][p]
                if cell["scores"]:
                    cell["avg_score"] = round(sum(cell["scores"]) / len(cell["scores"]), 1)
                    cell["grade"] = compute_grade(cell["avg_score"])
            r_sc = [self.data["matrix"][r][p]["avg_score"] for p in PHASE_KEYS if self.data["matrix"][r][p]["count"] > 0]
            self.data["matrix"][r]["avg"] = round(sum(r_sc) / len(r_sc), 1) if r_sc else 75.0

        ov = self.data["overall"]
        ov["win_rate"] = round((ov["wins"] / max(1, ov["total_games"])) * 100, 1)

        self._save()

    def format_console_scorecard(
        self,
        phase_scores: MatchPhaseScores,
        benchmark: OpponentBenchmarkReport,
        game_num: int = 0,
    ) -> str:
        """Renders an eSports-grade console scorecard and benchmark diagnostic block."""
        race = phase_scores.enemy_race
        res = phase_scores.result
        mins, secs = divmod(int(phase_scores.duration_sec), 60)
        time_str = f"{mins:02d}분 {secs:02d}초"

        lines = []
        lines.append("=" * 82)
        lines.append(f"  [경기 #{game_num} 종료] 경기 평가 스코어카드 & 상대 대조 벤치마크")
        lines.append("=" * 82)
        res_tag = "[승리 VICTORY]" if res == "Victory" else f"[{res.upper()}]"
        lines.append(f"  [대전 정보] 결과: {res_tag} | 상대 종족: {race} | 경기 시간: {time_str}")
        lines.append("")
        lines.append("  ▶ 이번 경기 3대 국면별 평가 점수:")
        lines.append(f"    - 초반 (0~4분)  : {phase_scores.early_score:5.1f}점 [{phase_scores.early_grade}등급] ({phase_scores.early_summary})")

        if phase_scores.mid_score is not None:
            lines.append(f"    - 중반 (4~9분)  : {phase_scores.mid_score:5.1f}점 [{phase_scores.mid_grade}등급] ({phase_scores.mid_summary})")
        else:
            lines.append(f"    - 중반 (4~9분)  :   -   점 [미진행] (경기 시간 4분 미만)")

        if phase_scores.late_score is not None:
            lines.append(f"    - 종반 (9분+)   : {phase_scores.late_score:5.1f}점 [{phase_scores.late_grade}등급] ({phase_scores.late_summary})")
        else:
            lines.append(f"    - 종반 (9분+)   :   -   점 [미진행] (경기 시간 9분 미만)")

        lines.append("    " + "-" * 74)
        lines.append(f"    ★ 이번 경기 종합 점수: {phase_scores.total_score:.1f}점 [{phase_scores.total_grade}등급]")
        lines.append("")

        lines.append("  ▶ 상대 대조 AI 벤치마크 (Our Bot vs Opponent):")
        lines.append(f"    - 군사 교전 가성비 : {benchmark.trade_verdict}")
        lines.append(f"    - 화력 집중 타격비 : {benchmark.damage_verdict} (아군 {benchmark.damage_dealt:,.0f} vs 상대 {benchmark.damage_taken:,.0f})")
        lines.append(f"    - 자원 소모 효율성 : {benchmark.spending_verdict}")
        lines.append(f"    - 유닛 트리아지    : {benchmark.triage_verdict}")
        lines.append("    [AI 코치 진단 총평]")
        for st in benchmark.coach_strengths[:2]:
            lines.append(f"      • 강점: \"{st}\"")
        for wk in benchmark.coach_weaknesses[:2]:
            lines.append(f"      • 보완: \"{wk}\"")
        for rc in benchmark.coach_recommendations[:2]:
            lines.append(f"      • 전술: \"{rc}\"")
        lines.append("")

        # Race win rates
        lines.append("  ▶ 상대 종족별 누적 승률 (Race Win Rates):")
        for r in VALID_RACES:
            st = self.data["race_stats"][r]
            r_label = "테란전 (vs Terran)   " if r == "TERRAN" else ("프로토스전 (vs Protoss)" if r == "PROTOSS" else "저그전 (vs Zerg)     ")
            lines.append(f"    - {r_label}: {st['games']:4d}전 {st['wins']:3d}승 {st['losses']:4d}패 (승률: {st['win_rate']:5.1f}%)")
        ov = self.data["overall"]
        lines.append(f"    - 전체 누적 전적         : {ov['total_games']:4d}전 {ov['wins']:3d}승 {ov['losses']:4d}패 (전체 승률: {ov['win_rate']:5.1f}%)")
        lines.append("")

        # 9-Matrix Table
        lines.append("  ▶ 9대 국면 평가 매트릭스 (3 Races x 3 Phases):")
        lines.append("    ┌───────────┬──────────────┬──────────────┬──────────────┬──────────────┐")
        lines.append("    │ 상대 종족  │  초반 (0~4분) │  중반 (4~9분) │  종반 (9분+) │  종족 평균   │")
        lines.append("    ├───────────┼──────────────┼──────────────┼──────────────┼──────────────┤")

        race_labels = {"TERRAN": "테란 (TvT)", "PROTOSS": "토스 (TvP)", "ZERG": "저그 (TvZ)"}
        for r in VALID_RACES:
            lbl = race_labels[r]
            e_str = f"{self.data['matrix'][r]['early']['avg_score']:4.1f}점 [{self.data['matrix'][r]['early']['grade']}]"
            m_str = f"{self.data['matrix'][r]['mid']['avg_score']:4.1f}점 [{self.data['matrix'][r]['mid']['grade']}]"
            l_str = f"{self.data['matrix'][r]['late']['avg_score']:4.1f}점 [{self.data['matrix'][r]['late']['grade']}]"
            avg_val = self.data['matrix'][r].get("avg", 75.0)
            avg_grade = compute_grade(avg_val)
            avg_str = f"{avg_val:4.1f}점 [{avg_grade}]"
            lines.append(f"    │ {lbl:<9} │  {e_str:<11} │  {m_str:<11} │  {l_str:<11} │  {avg_str:<11} │")
        lines.append("    └───────────┴──────────────┴──────────────┴──────────────┴──────────────┘")
        lines.append("=" * 82)

        return "\n".join(lines)


# Global singleton instance
NINE_MATRIX_MGR = NineMatrixManager()
