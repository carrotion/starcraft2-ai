"""User & AI Shared Strategy Guide for StarCraft II.

전략 가이드북:
- [난이도] 어려움(Hard) ~ 아주 어려움(Very Hard) 1 vs 2 다대일 대응
- [방어] 입구 벙커(Bunker) 건설 및 해병 4기 탑승 + SCV 수리
- [멀티] 앞마당 멀티 확장 (2베이스 체제)
- [업그레이드] 스팀팩, 전투방패, 보병 공1업, 방1업
- [생산] 4배럭 + 2팩토리 + 1스타포트
- [전술] 24+ 업그레이드 복합 대군 총공격
"""

from dataclasses import dataclass


@dataclass
class StrategyConfig:
    race: str = "Terran"

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
    target_barracks: int = 5  # 5병영 (반응로 해병 양산 + 기술실 불곰)
    build_factory: bool = True  # 군수공장
    target_factories: int = 2  # 2군수공장 (더블 전차 체제)
    build_starport: bool = True  # 우주공항
    target_starports: int = 1

    # [4단계: 테크 인프라 및 업그레이드 연구]
    build_engineering_bay: bool = True  # 공학연구소
    build_armory: bool = True  # 무기고 (토르 필수 & 차량/함선/보병 고티어 업그레이드 해금)
    build_fusion_core: bool = True  # 융합로 (우주공항 후반 전투순양함 필수)
    build_ghost_academy: bool = True  # 유령사관학교 (유령 해금 및 핵/EMP 지원)
    research_stimpack: bool = True  # 스팀팩
    research_combat_shield: bool = True  # 전투 방패
    research_concussive_shells: bool = True  # 불곰 충격탄 (적 돌진 감속)
    research_weapons: bool = True  # 보병 공1~3업
    research_armor: bool = True  # 보병 방1~3업
    research_mech_weapons: bool = True  # 차량 및 함선 공격 1~3업
    research_mech_armor: bool = True  # 차량 및 함선 장갑 1~3업
    research_special_abilities: bool = True  # 야마토포, 밴시/유령 은폐, 해방선 사거리, 지뢰 천공발톱 등 특수기술

    # [5단계: 자율 복합 유닛 생산 - 강화학습/전황에 따른 지능형 조합 16종 전면 해금]
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

    # [6단계: 교전 및 전술]
    attack_army_threshold: int = 28  # 탄탄한 화력(전차 4+, 바이오닉 20+) 구축 후 진격
    defend_base_on_attack: bool = True


# 기본 활성 전략 인스턴스
CURRENT_STRATEGY = StrategyConfig()

