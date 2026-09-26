"""User & AI Shared Strategy Guide for StarCraft II.

전략 가이드북:
- [종족별 맞춤 전략] TvZ (저그전), TvP (토스전), TvT (테란전), TvMulti (1v2 다대일)
- [능동 정찰 & 스캔] 초반 SCV/사신 정찰 및 주기적 궤도 스캐너 스캔 (적 테크/확장 실시간 파악)
- [방어] 입구 벙커(Bunker) 건설 및 해병 4기 탑승 + SCV 수리
- [멀티] 앞마당 멀티 확장 (2베이스~4베이스 유동적 확장)
- [업그레이드] 종족별 우선 연구 (토스전 충격탄/EMP 선행, 저그전 스팀팩/방패 선행)
- [생산] 종족 맞춤형 인프라 및 부속건물(기술실/반응로) 최적 비율 배분
- [전술] 16종 복합 유닛 제병협동 카운터 총공격
"""

from dataclasses import dataclass
from typing import Dict, Any


@dataclass
class StrategyConfig:
    race: str = "Terran"
    matchup: str = "DEFAULT"

    # [1단계: 멀티 및 경제]
    max_bases: int = 4  # 최대 사령부 수 (본진 + 앞마당 + 제3, 제4 멀티 자원 기반 유동적 확장)
    max_workers: int = 70  # 최대 일꾼 수 (기지당 약 20~22기 최적 분배)
    upgrade_orbital: bool = True  # 궤도 사령부 변태 + 지게로봇(MULE) 자원 부스팅
    mule_energy_threshold: int = 100  # 지게로봇은 에너지 100 이상일 때만 사용 (비상 스캔 50 상시 비축)

    # [2단계: 입구 및 앞마당 철벽 방어 (1v2 생존 핵심)]
    build_bunker: bool = True  # 본진 언덕 + 앞마당 길목 벙커 방어선
    bunker_at_natural: bool = True  # 앞마당 사령부 보호 벙커
    build_missile_turrets: bool = True  # 본진/앞마당 공중 견제 및 은폐 탐지 포탑

    # [3단계: 가스 및 인프라]
    build_refinery: bool = True  # 4가스 완전 채취
    target_barracks: int = 5  # 병영 목표치 (종족별 가변)
    barracks_techlab_target: int = 2  # 병영 기술실 목표치 (토스전 3~4개로 불곰 집중)
    barracks_reactor_target: int = 2  # 병영 반응로 목표치 (저그전 3개로 해병 양산)
    build_factory: bool = True  # 군수공장
    target_factories: int = 2  # 군수공장 목표치 (테란전/저그전 2~3공장 전차 체제)
    factory_techlab_target: int = 2  # 군수공장 기술실 (공성전차/토르)
    build_starport: bool = True  # 우주공항
    target_starports: int = 1  # 우주공항 목표치 (토스전/테란전 2개로 바이킹/밤까마귀 확보)
    starport_techlab_target: int = 1  # 우주공항 기술실 (밤까마귀/밴시/배틀)

    # [4단계: 테크 인프라 및 업그레이드 연구]
    build_engineering_bay: bool = True  # 공학연구소
    build_armory: bool = True  # 무기고 (토르 필수 & 차량/함선/보병 고티어 업그레이드 해금)
    build_fusion_core: bool = True  # 융합로 (우주공항 후반 전투순양함 필수)
    build_ghost_academy: bool = True  # 유령사관학교 (유령 해금 및 핵/EMP 지원)
    ghost_priority: bool = False  # 프로토스전 실드/스톰 카운터용 유령사관학교 우선 건설
    priority_upgrade: str = "balanced"  # balanced, stim_first (저그전), concussive_first (토스전), mech_balanced (테란전)
    research_stimpack: bool = True  # 스팀팩
    research_combat_shield: bool = True  # 전투 방패
    research_concussive_shells: bool = True  # 불곰 충격탄 (적 돌진 감속)
    research_weapons: bool = True  # 보병 공1~3업
    research_armor: bool = True  # 보병 방1~3업
    research_mech_weapons: bool = True  # 차량 및 함선 공격 1~3업
    research_mech_armor: bool = True  # 차량 및 함선 장갑 1~3업
    research_special_abilities: bool = True  # 야마토포, 밴시/유령 은폐, 해방선 사거리, 지뢰 천공발톱 등 특수기술

    # [5단계: 능동 정찰 및 스캐너 스캔 (Fog of War 관통)]
    early_scout: bool = True  # 1:30~2:30 SCV / 사신 전술 정찰 급파
    periodic_scan: bool = True  # 궤도사령부 에너지 활용 주기적 적진 정찰 스캔
    scan_interval_sec: float = 90.0  # 90초마다 적진 핵심 테크/확장 스캔

    # [6단계: 자율 복합 유닛 생산 - 강화학습/전황에 따른 지능형 조합 16종 전면 해금]
    composition_focus: str = "adaptive"  # adaptive(자율 적응 강화학습 가중치 제어)
    train_marines: bool = True           # 해병
    train_reapers: bool = True           # 사신
    train_marauders: bool = True         # 불곰
    train_ghosts: bool = True            # 유령
    train_hellions: bool = True          # 화염차
    train_hellbats: bool = True          # 화염기갑병
    train_widow_mines: bool = True       # 땅거미 지뢰
    train_cyclones: bool = True          # 사이클론
    train_siege_tanks: bool = True       # 공성전차
    train_thors: bool = True             # 토르
    train_vikings: bool = True           # 바이킹
    train_medivacs: bool = True          # 의료선
    train_liberators: bool = True        # 해방선
    train_ravens: bool = True            # 밤까마귀
    train_banshees: bool = True          # 밴시
    train_battlecruisers: bool = True    # 전투순양함

    # [7단계: 교전 및 전술]
    attack_army_threshold: int = 28  # 탄탄한 화력 구축 후 진격 (종족별 최적화)
    defend_base_on_attack: bool = True


# ==============================================================================
# 종족별 전문 맞춤 전략 프로필 (TvZ / TvP / TvT / TvMulti)
# ==============================================================================

def get_matchup_strategy(enemy_race: str) -> StrategyConfig:
    """상대 종족(TvZ, TvP, TvT, TvMulti)에 특화된 빌드오더, 생산 인프라, 연구 우선순위 전략을 반환합니다."""
    norm = enemy_race.upper() if enemy_race else "DEFAULT"

    # [1] TvMulti (1 vs 2 다대일: 저그 + 프로토스 등 복합 전장)
    if "ZERG" in norm and "PROTOSS" in norm:
        return StrategyConfig(
            matchup="TvMulti",
            target_barracks=6,
            barracks_techlab_target=3,  # 토스 중장갑 저격용 불곰
            barracks_reactor_target=3,  # 저그 저글링/뮤탈 대응 해병
            target_factories=2,
            factory_techlab_target=2,   # 공성전차 필수 (맹독충/히드라 방어)
            target_starports=2,
            starport_techlab_target=1,  # 밤까마귀/밴시 + 바이킹
            priority_upgrade="concussive_first",
            ghost_priority=True,        # 토스 실드 파괴용 EMP 유령
            attack_army_threshold=32,
            scan_interval_sec=80.0,
        )

    # [2] TvZ (테란 vs 저그: 스웜 분쇄, 맹독충 카운터 전차, 뮤탈 대비 토르/바이킹)
    if "ZERG" in norm:
        return StrategyConfig(
            matchup="TvZ",
            target_barracks=5,
            barracks_techlab_target=2,  # 스팀팩/방패 연구 및 지원 불곰
            barracks_reactor_target=3,  # 반응로 해병 대량 쏟아붓기 (저글링/뮤탈 제압)
            target_factories=2,
            factory_techlab_target=2,   # 공성전차 더블 생산 (맹독충 러시/바퀴/히드라 원거리 폭격)
            target_starports=1,
            starport_techlab_target=0,  # 의료선 쾌속 수송 & 바이킹 지원
            priority_upgrade="stim_first",  # 저그전은 보병 기동성 & 화력 극대화(스팀팩) 최우선
            ghost_priority=False,
            attack_army_threshold=28,
            scan_interval_sec=90.0,
        )

    # [3] TvP (테란 vs 프로토스: 실드 분쇄 EMP, 추적자/거신 분쇄 불곰 충격탄, 대공 바이킹)
    if "PROTOSS" in norm:
        return StrategyConfig(
            matchup="TvP",
            target_barracks=6,
            barracks_techlab_target=4,  # 기술실 4개: 충격탄 중장갑 불곰 집중 생산 (추적자/불멸자 압살)
            barracks_reactor_target=2,  # 해병 DPS 보조
            target_factories=2,
            factory_techlab_target=1,   # 전차 거점 방어 + 사이클론/지뢰
            target_starports=2,         # 2우주공항: 거신/우주모함 저격용 바이킹 필수 확보!
            starport_techlab_target=1,
            priority_upgrade="concussive_first",  # 불곰 충격탄 선행 (광전사/추적자 카이팅 핵심)
            ghost_priority=True,        # 프로토스 실드 50%를 일격에 날리고 스톰을 차단하는 EMP 유령 필수!
            attack_army_threshold=30,
            scan_interval_sec=85.0,
        )

    # [4] TvT (테란 vs 테란: 제공권 바이킹, 공성전차 라인 배틀, 밤까마귀 방해매트릭스)
    if "TERRAN" in norm:
        return StrategyConfig(
            matchup="TvT",
            target_barracks=4,
            barracks_techlab_target=2,
            barracks_reactor_target=2,
            target_factories=3,         # 3군수공장: 공성전차 라인 싸움이 승패를 결정짓는 핵심!
            factory_techlab_target=2,
            target_starports=2,         # 2우주공항: 바이킹 제공권 장악 (시야 확보) + 밤까마귀
            starport_techlab_target=1,  # 밤까마귀(방해 매트릭스로 적 전차/토르/배틀 무력화)
            priority_upgrade="mech_balanced",  # 메카닉 공방업과 바이오닉 공방업 균형
            ghost_priority=False,
            attack_army_threshold=28,
            scan_interval_sec=80.0,
        )

    # [5] Default Strategy (상대 종족 미확인 시 기본 균형형)
    return StrategyConfig(
        matchup="DEFAULT",
        target_barracks=5,
        barracks_techlab_target=2,
        barracks_reactor_target=2,
        target_factories=2,
        factory_techlab_target=2,
        target_starports=1,
        starport_techlab_target=1,
        priority_upgrade="balanced",
        ghost_priority=False,
        attack_army_threshold=28,
        scan_interval_sec=90.0,
    )


# 기본 활성 전략 인스턴스
CURRENT_STRATEGY = StrategyConfig()
