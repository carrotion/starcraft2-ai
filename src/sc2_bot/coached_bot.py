"""StarCraft II Coached Bot with Crash-Proof Safety, Multi-Base Expansion, Upgrades, and Smart Micro."""

import time
import traceback
from typing import Optional, List
from sc2.bot_ai import BotAI
from sc2.data import Race, Result
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.ability_id import AbilityId
from sc2.ids.upgrade_id import UpgradeId
from sc2.position import Point2

from src.sc2_bot.strategy_guide import StrategyConfig, CURRENT_STRATEGY, get_matchup_strategy
from src.sc2_bot.micro_controller import TerranMicroController
from src.sc2_learning.live_telemetry import LiveTelemetry
from src.sc2_learning.unit_optimizer import UnitOptimizer, ALL_16_UNITS
from src.sc2_learning.combat_policy import CombatPolicyOptimizer


class CoachedTerranBot(BotAI):
    """Crash-proof Terran Bot capable of high-difficulty 1v2 with bunker defense, multi-base expansion, and full upgrades."""

    def __init__(self, strategy: Optional[StrategyConfig] = None, worker_id: int = 1):
        super().__init__()
        self.strategy = strategy or CURRENT_STRATEGY
        self.worker_id = worker_id
        self.combat_policy = CombatPolicyOptimizer()
        self.micro = TerranMicroController(self)
        self.telemetry = LiveTelemetry(worker_id)
        self.unit_optimizer = UnitOptimizer()
        self.units_produced_tracker = {u: 0 for u in ALL_16_UNITS}
        self.actual_enemy_race = "DEFAULT"
        self.matchup_applied = ""
        self.last_log_time = 0.0
        self.prev_status = ""
        self.unspent_minerals_samples: List[int] = []
        self.unspent_vespene_samples: List[int] = []
        self.last_econ_sample_time: float = 0.0
        self.last_metrics = None
        self.last_fitness = None
        self.unit_stuck_watch: dict[int, tuple[Point2, float]] = {}

        # Reconnaissance & Persistent Fog-of-War Intel
        self.seen_enemy_structures: set[UnitTypeId] = set()
        self.seen_enemy_units: set[UnitTypeId] = set()
        self.last_enemy_structure_seen_time: float = 0.0
        self.has_scouted_early: bool = False
        self.scout_tag: Optional[int] = None
        self.scout_retreating: bool = False
        self.last_strategic_scan_time: float = 0.0
        self.scan_count: int = 0

        # Health Preservation & Critical HP Monitoring (유닛 피 관리)
        self.critical_hp_incidents: int = 0
        self.units_saved_from_critical: int = 0
        self.critical_unit_tags: set[int] = set()
        self.army_hp_pct_samples: List[float] = []
        self.last_hp_sample_time: float = 0.0



    def _safe_corner_depots(self) -> List[Point2]:
        """Safely retrieves corner depot points without crashing if map ramp has non-standard shape."""
        try:
            if self.main_base_ramp:
                return list(self.main_base_ramp.corner_depots)
        except Exception:
            pass
        return []

    def _safe_ramp_bunker_placement(self) -> Optional[Point2]:
        """Safely retrieves the exact 3x3 choke wall position for Bunker in the middle of ramp."""
        try:
            if self.main_base_ramp and self.main_base_ramp.barracks_in_middle:
                return self.main_base_ramp.barracks_in_middle
        except Exception:
            pass
        return None

    def _safe_ramp_top_center(self, fallback: Point2) -> Point2:
        """Safely retrieves ramp top center without crashing."""
        try:
            if self.main_base_ramp:
                return self.main_base_ramp.top_center
        except Exception:
            pass
        return fallback

    async def find_safe_main_placement(self, building: UnitTypeId, addon_place: bool = False) -> Optional[Point2]:
        """Finds a safe building placement strictly on the main base high ground, reserving space for add-on if requested."""
        if not self.townhalls:
            return None
        main_base = self.townhalls.first
        base_h = self.get_terrain_height(main_base.position)
        ramp_choke = self._safe_ramp_top_center(main_base.position)
        ramp_bunker = self._safe_ramp_bunker_placement()

        # Vector pointing inward from the ramp into the deep main base
        diff = main_base.position - ramp_choke
        inward_vec = diff.normalized if diff.length > 0.1 else Point2((1, 0))
        perp_vec = Point2((-inward_vec.y, inward_vec.x))

        seeds = [
            main_base.position + inward_vec * 5.0,
            main_base.position + inward_vec * 8.0,
            main_base.position + perp_vec * 6.0,
            main_base.position - perp_vec * 6.0,
            main_base.position + inward_vec * 11.0,
            main_base.position + perp_vec * 9.0,
            main_base.position - perp_vec * 9.0,
        ]

        map_w = self.game_info.map_size[0]
        max_dist = 18 if map_w > 70 else 10
        fallback_dist = 24 if map_w > 70 else 12

        for seed in seeds:
            pos = await self.find_placement(
                building,
                near=seed,
                max_distance=max_dist,
                random_alternative=True,
                placement_step=1,
                addon_place=addon_place,
            )
            if pos:
                # 1. Height must strictly match main base high ground (NEVER build down below on natural)
                if self.get_terrain_height(pos) != base_h:
                    continue
                # 2. Must not crowd or block the ramp choke wall (keep ramp open for army exit)
                if pos.distance_to(ramp_choke) < 6.0:
                    continue
                if ramp_bunker and pos.distance_to(ramp_bunker) < 4.5:
                    continue
                # 3. Must not block mineral harvesters
                if self.mineral_field.closer_than(2.5, pos):
                    continue

                # 4. If add-on required, double check that the right-side slot is completely free and on high ground!
                if addon_place:
                    addon_pos = pos.offset((2.5, -0.5))
                    if self.get_terrain_height(addon_pos) != base_h:
                        continue
                    if not await self.can_place_single(UnitTypeId.SUPPLYDEPOT, addon_pos):
                        continue
                    if self.mineral_field.closer_than(2.5, addon_pos):
                        continue

                # 5. Clearance Aisles: Ensure production & tech buildings do not clump with distance < 4.2
                # Center-to-center distance >= 4.2 guarantees at least a 1.2~1.5 tile walkway for Tanks, Thors, and Bio
                if building in {UnitTypeId.BARRACKS, UnitTypeId.FACTORY, UnitTypeId.STARPORT, UnitTypeId.ENGINEERINGBAY, UnitTypeId.ARMORY}:
                    clumping = self.structures.filter(
                        lambda s: s.type_id in {
                            UnitTypeId.BARRACKS, UnitTypeId.FACTORY, UnitTypeId.STARPORT,
                            UnitTypeId.ENGINEERINGBAY, UnitTypeId.ARMORY, UnitTypeId.COMMANDCENTER
                        } and s.distance_to(pos) < 4.3
                    )
                    if clumping:
                        continue
                elif building == UnitTypeId.SUPPLYDEPOT:
                    # Depots should not block production building doorways
                    if self.structures({UnitTypeId.BARRACKS, UnitTypeId.FACTORY, UnitTypeId.STARPORT}).closer_than(3.2, pos):
                        continue

                return pos


        # Fallback: strictly check height around main base with addon_place
        fallback_pos = await self.find_placement(
            building,
            near=main_base.position,
            max_distance=fallback_dist,
            random_alternative=True,
            addon_place=addon_place,
        )
        if fallback_pos and self.get_terrain_height(fallback_pos) == base_h:
            if addon_place:
                addon_pos = fallback_pos.offset((2.5, -0.5))
                if (
                    self.get_terrain_height(addon_pos) == base_h
                    and await self.can_place_single(UnitTypeId.SUPPLYDEPOT, addon_pos)
                ):
                    return fallback_pos
            else:
                return fallback_pos
        return None




    async def _handle_surrender_requests(self) -> bool:
        """Monitors in-game chat for surrender/resignation proposals ('항복 할까요?', etc.) and unconditionally accepts them."""
        try:
            if not self.state.chat:
                return False

            for chat in self.state.chat:
                raw_msg = chat.message
                clean_msg = raw_msg.replace(" ", "").lower()

                # Checks "항복할까요?", "항복할까요", "항복할까", "항복 제안", "항복하시겠", "surrender"
                is_surrender_query = (
                    "항복할까" in clean_msg
                    or "항복할까요" in clean_msg
                    or "항복하시겠" in clean_msg
                    or "항복제안" in clean_msg
                    or "항복요청" in clean_msg
                    or "항복투표" in clean_msg
                    or "surrender" in clean_msg
                    or clean_msg in ("항복", "항복하자", "항복할래", "gg", "ff")
                )

                if is_surrender_query:
                    print(f"\n[항복 요청 수락] 메시지 감지: '{raw_msg}' (Player {chat.player_id}) ➔ 무조건 수락 및 항복 진행")
                    self.telemetry.log(f"[항복 수락] '{raw_msg}' 감지 ➔ 항복 요청을 무조건 수락합니다 (GG)")
                    try:
                        await self.chat_send("네, 항복 요청을 수락합니다. GG!", team_only=False)
                        await self.chat_send("/항복", team_only=True)
                        await self.chat_send("/surrender", team_only=True)
                    except Exception:
                        pass
                    await self.client.leave()
                    return True
        except Exception as e:
            print(f"[항복 감지 예외]: {e}")
        return False

    async def on_step(self, iteration: int):
        try:
            # 0. Check surrender/resignation requests ("항복 할까요?")
            if await self._handle_surrender_requests():
                return
            await self._step_body(iteration)
        except Exception as e:
            # Prevent any unhandled python exception from terminating the game
            print(f"\n[안전 시스템] Step {iteration} 경고: {e} (게임 지속 실행 중)")

    async def _step_body(self, iteration: int):
        # 0. Enemy Race auto-detection
        if self.actual_enemy_race in ("DEFAULT", "Unknown", "Random", "random"):
            if self.enemy_race and self.enemy_race != Race.Random:
                self.actual_enemy_race = self.enemy_race.name
            elif hasattr(self, "game_info") and self.game_info.players:
                opponents = [p for p in self.game_info.players if p.id != self.player_id]
                if opponents:
                    valid_races = [p.actual_race.name for p in opponents if p.actual_race and p.actual_race != Race.Random]
                    if valid_races:
                        self.actual_enemy_race = "+".join(valid_races)
            if self.actual_enemy_race in ("DEFAULT", "Unknown", "Random", "random"):
                if self.all_enemy_units:
                    self.actual_enemy_race = self.all_enemy_units.first.race.name
                elif self.enemy_structures:
                    self.actual_enemy_race = self.enemy_structures.first.race.name

        # Dynamically apply matchup strategy once enemy race is resolved
        if self.actual_enemy_race != self.matchup_applied:
            self.matchup_applied = self.actual_enemy_race
            matchup_strat = get_matchup_strategy(self.actual_enemy_race)
            self.strategy.matchup = matchup_strat.matchup
            self.strategy.target_barracks = matchup_strat.target_barracks
            self.strategy.barracks_techlab_target = matchup_strat.barracks_techlab_target
            self.strategy.barracks_reactor_target = matchup_strat.barracks_reactor_target
            self.strategy.target_factories = matchup_strat.target_factories
            self.strategy.factory_techlab_target = matchup_strat.factory_techlab_target
            self.strategy.target_starports = matchup_strat.target_starports
            self.strategy.starport_techlab_target = matchup_strat.starport_techlab_target
            self.strategy.priority_upgrade = matchup_strat.priority_upgrade
            self.strategy.ghost_priority = matchup_strat.ghost_priority
            self.strategy.attack_army_threshold = matchup_strat.attack_army_threshold
            self.strategy.scan_interval_sec = matchup_strat.scan_interval_sec
            self.telemetry.log_event(f"종족 맞춤 전술 가동: {matchup_strat.matchup} ({self.actual_enemy_race} 특화 빌드 & 카운터)", "strategy")

        # Persistent Enemy Intelligence Tracker (Fog of War 관통)
        for s in self.enemy_structures:
            if s.type_id not in self.seen_enemy_structures:
                self.seen_enemy_structures.add(s.type_id)
                self.telemetry.log_event(f"🎯 [적 핵심 테크 감지] {s.type_id.name} 포착! 맞춤 카운터 전략 즉각 가동!", "intel")
            self.last_enemy_structure_seen_time = self.time

        for u in self.enemy_units:
            self.seen_enemy_units.add(u.type_id)

        # Health Preservation & Critical HP Monitoring (유닛 피 관리 & 빈사 상태 감점 추적)
        if self.time - self.last_hp_sample_time >= 1.0:
            self.last_hp_sample_time = self.time
            combat_units = self.units.filter(
                lambda u: (u.can_attack_ground or u.can_attack_air) and u.type_id not in {UnitTypeId.SCV, UnitTypeId.MULE}
            )
            if combat_units:
                hp_ratios = [u.health / u.health_max for u in combat_units]
                avg_hp = sum(hp_ratios) / len(hp_ratios)
                self.army_hp_pct_samples.append(avg_hp)

                for u in combat_units:
                    ratio = u.health / u.health_max
                    if ratio <= 0.35:
                        if u.tag not in self.critical_unit_tags:
                            self.critical_unit_tags.add(u.tag)
                            self.critical_hp_incidents += 1
                    elif ratio >= 0.70 and u.tag in self.critical_unit_tags:
                        # Unit was healed/repaired back to safety!
                        self.critical_unit_tags.remove(u.tag)
                        self.units_saved_from_critical += 1
                        self.telemetry.log_event(f"🚑 [체력 회복] 빈사 유닛({u.type_id.name}) 완치되어 전선 복귀!", "heal")

        # Periodic resource sampling for average bank float tracking
        if self.time - self.last_econ_sample_time >= 5.0:
            self.last_econ_sample_time = self.time
            self.unspent_minerals_samples.append(self.minerals)
            self.unspent_vespene_samples.append(self.vespene)

        # 1. Base check
        cc_list = self.townhalls
        if not cc_list:
            combat_units = self.units.filter(lambda u: u.can_attack_ground or u.can_attack_air)
            for unit in combat_units:
                unit.attack(self.enemy_start_locations[0])
            return

        main_base = cc_list.first
        other_ccs = cc_list.further_than(5, main_base)
        ramp_choke = self._safe_ramp_top_center(main_base.position.towards(self.game_info.map_center, 10))

        # 2. Worker distribution, dynamic base-scaling capacity, and SCV production
        # APM Optimization: Throttle distribute_workers to once every 64 iterations (~3s) to eliminate click spam!
        # Macro Rebalancing: When gas is heavily floating (>450) and minerals are starved (<150), pull SCVs to minerals!
        self.iteration = iteration
        if iteration % 64 == 0:
            if self.vespene > 450 and self.minerals < 150:
                for ref in self.gas_buildings.ready:
                    if ref.assigned_harvesters > 1:
                        excess_scvs = self.workers.closer_than(3.0, ref)
                        if excess_scvs:
                            minerals_near = self.mineral_field.closer_than(10.0, main_base)
                            if minerals_near:
                                excess_scvs.first.gather(minerals_near.closest_to(ref))
            else:
                await self.distribute_workers()
        workers = self.workers

        # Calculate true economic capacity based on active resource nodes:
        # 16 per active CC minerals + 3 per active Refinery + 4 buffer when expanding
        active_mineral_cap = sum(th.ideal_harvesters for th in self.townhalls.ready)
        active_gas_cap = sum(ref.ideal_harvesters for ref in self.gas_buildings.ready)
        pre_expansion_buffer = 4 if self.already_pending(UnitTypeId.COMMANDCENTER) > 0 else 0

        # Exact optimal worker target tailored to active bases:
        # 1 base (0 gas) -> 16
        # 1 base (2 gas) -> 22 (+4 if natural expanding = 26)
        # 2 bases (4 gas) -> 44 (+4 if 3rd base expanding = 48)
        # 3 bases (6 gas) -> 66
        # If bases deplete, ideal_harvesters automatically drops to prevent over-harvesting!
        optimal_target_workers = max(16, active_mineral_cap + active_gas_cap + pre_expansion_buffer)
        dynamic_worker_cap = min(self.strategy.max_workers, optimal_target_workers)

        if len(workers) < dynamic_worker_cap and self.can_afford(UnitTypeId.SCV):
            for cc in cc_list.idle:
                cc.train(UnitTypeId.SCV)

        # Ensure Command Centers rally newly produced SCVs directly to the closest mineral patch
        for cc in self.townhalls.ready:
            near_minerals = self.mineral_field.closer_than(10.0, cc)
            if near_minerals:
                cc(AbilityId.RALLY_WORKERS, near_minerals.closest_to(cc))

        # Immediate recovery for idle workers: send to bases that need harvesters
        if self.workers.idle and self.mineral_field:
            for idle_scv in self.workers.idle:
                needy_ccs = [c for c in cc_list.ready if c.assigned_harvesters < c.ideal_harvesters]
                target_cc = needy_ccs[0] if needy_ccs else cc_list.closest_to(idle_scv)
                minerals_near = self.mineral_field.closer_than(10.0, target_cc)
                target_m = minerals_near.closest_to(idle_scv) if minerals_near else self.mineral_field.closest_to(idle_scv)
                idle_scv.gather(target_m)

        # Early Physical Scouting (1:30 ~ 3:30): Dispatch SCV scout to enemy base
        if self.strategy.early_scout and self.enemy_start_locations:
            if not self.has_scouted_early and 90.0 <= self.time <= 180.0 and len(workers) >= 14:
                scout_candidate = workers.idle.first if workers.idle else workers.first
                if scout_candidate:
                    self.scout_tag = scout_candidate.tag
                    self.has_scouted_early = True
                    scout_candidate.move(self.enemy_start_locations[0])
                    self.telemetry.log_event("📡 [초기 정찰] SCV 정찰대 급파! 적진 진영 및 빌드오더 정찰 출발!", "scout")

            if self.scout_tag:
                scout_unit = self.workers.find_by_tag(self.scout_tag) or self.units(UnitTypeId.REAPER).find_by_tag(self.scout_tag)
                if scout_unit:
                    if (scout_unit.health < scout_unit.health_max * 0.40) or self.time > 230.0:
                        if not self.scout_retreating:
                            self.scout_retreating = True
                            minerals_home = self.mineral_field.closer_than(10, main_base)
                            if minerals_home:
                                scout_unit.gather(minerals_home.closest_to(scout_unit))
                                self.telemetry.log_event("🛡️ [정찰 복귀] 정찰 임무 완수 후 기지로 안전 복귀!", "scout")
                            else:
                                scout_unit.move(main_base.position)
                    elif not self.scout_retreating:
                        enemy_main_pos = self.enemy_start_locations[0]
                        enemy_nat_pos = enemy_main_pos.towards(self.game_info.map_center, 12)
                        if scout_unit.distance_to(enemy_main_pos) < 14:
                            scout_unit.move(enemy_nat_pos)
                        elif scout_unit.distance_to(enemy_nat_pos) < 6:
                            scout_unit.move(enemy_main_pos)

        # 3. Orbital Command Morphing & MULE / Scan Deployment (경제력 2배 부스팅)
        if self.strategy.upgrade_orbital and self.structures(UnitTypeId.BARRACKS).ready:
            for cc in self.townhalls(UnitTypeId.COMMANDCENTER).idle:
                if self.can_afford(UnitTypeId.ORBITALCOMMAND):
                    cc(AbilityId.UPGRADETOORBITAL_ORBITALCOMMAND)

        for oc in self.townhalls(UnitTypeId.ORBITALCOMMAND).ready:
            # 1. Emergency Scan: Whenever cloaked/burrowed enemies threaten our bases or army
            if oc.energy >= 50:
                cloaked_threats = self.enemy_units.filter(
                    lambda u: (u.is_cloaked or u.is_burrowed) and u.distance_to(oc.position) < 30
                )
                if cloaked_threats:
                    oc(AbilityId.SCANNERSWEEP_SCAN, cloaked_threats.first.position)
                    continue

                # 2. Strategic Scanner Sweeps (적 테크 및 확장 정찰)
                if self.strategy.periodic_scan and self.enemy_start_locations and self.time >= 180.0:
                    time_since_scan = self.time - self.last_strategic_scan_time
                    time_since_seen_bld = self.time - self.last_enemy_structure_seen_time
                    if time_since_scan >= self.strategy.scan_interval_sec or (time_since_seen_bld >= 90.0 and self.time >= 240.0):
                        enemy_main = self.enemy_start_locations[0]
                        enemy_nat = enemy_main.towards(self.game_info.map_center, 12)
                        scan_target = enemy_main if (self.scan_count % 2 == 0 or time_since_seen_bld >= 60.0) else enemy_nat
                        target_name = "본진 테크 거점" if scan_target == enemy_main else "앞마당 확장"
                        oc(AbilityId.SCANNERSWEEP_SCAN, scan_target)
                        self.last_strategic_scan_time = self.time
                        self.scan_count += 1
                        self.telemetry.log_event(f"📡 [전술 궤도 스캔] 적 {target_name} 정찰 스캔 실시! (누적 {self.scan_count}회)", "scan")
                        continue

            # 3. MULE deployment: Only when energy reaches 100 (reserving 50 energy for emergency scans)
            if oc.energy >= self.strategy.mule_energy_threshold:
                minerals = self.mineral_field.closer_than(10, oc)
                if minerals:
                    richest = max(minerals, key=lambda m: m.mineral_contents)
                    oc(AbilityId.CALLDOWNMULE_CALLDOWNMULE, richest)


        # 4. Multi-Base Expansion (자원 상황 및 전황에 따른 지능형 멀티 확장)
        total_cc = cc_list.amount + self.already_pending(UnitTypeId.COMMANDCENTER)
        pending_cc = self.already_pending(UnitTypeId.COMMANDCENTER)
        has_secure_main = (
            self.structures(UnitTypeId.BUNKER).ready.amount >= 1
            and self.units(UnitTypeId.MARINE).amount >= 4
        )
        enemies_near_any_base = any(self.enemy_units.closer_than(20, cc.position) for cc in cc_list)

        should_expand = False
        if total_cc < self.strategy.max_bases and pending_cc == 0 and not enemies_near_any_base:
            if total_cc == 1:
                # [제2기지: 앞마당 멀티] 본진 벙커 + 해병 4기 + SCV 16기 이상 시 안정적 확장
                # 또는 미네랄 500 이상 누적 시 빠른 앞마당 확장
                if (
                    (len(workers) >= 16 and has_secure_main and self.can_afford(UnitTypeId.COMMANDCENTER))
                    or (self.minerals >= 500 and self.structures(UnitTypeId.BARRACKS).ready)
                ):
                    should_expand = True

            elif total_cc == 2:
                # [제3기지: 삼룡이 멀티] 앞마당 사령부가 완성된 후:
                # 1) 일꾼 32기 이상 확보되어 앞마당이 활성화되었거나
                # 2) 전차 1기 이상 또는 병력 인구수 16 이상으로 수비력 확보 시
                # 3) 본진 미네랄 필드가 고갈되기 시작할 때 (남은 미네랄 필드 5개 미만)
                # 4) 미네랄 잉여자원이 500 이상 누적될 때
                nat_cc_ready = other_ccs.ready.amount >= 1
                main_minerals = self.mineral_field.closer_than(10, main_base)
                main_depleted = len(main_minerals) < 5
                has_midgame_army = (
                    self.units(UnitTypeId.SIEGETANK).ready.amount >= 1
                    or self.supply_army >= 16
                    or self.time > 360
                )
                if (
                    nat_cc_ready
                    and (len(workers) >= 32 or has_midgame_army or main_depleted or self.minerals >= 500)
                    and self.can_afford(UnitTypeId.COMMANDCENTER)
                ):
                    should_expand = True

            elif total_cc >= 3:
                # [제4기지+: 후반 매크로 멀티]
                # 1) 잉여 미네랄이 600 이상 누적되어 자원 회전 필요
                # 2) 이전 기지들의 자원 고갈이 진행 중 (활성 미네랄 패치 14개 미만)
                # 3) 게임 시간 10분(600초) 이상 장기전
                active_minerals_count = sum(len(self.mineral_field.closer_than(10, cc)) for cc in cc_list.ready)
                if (
                    (self.minerals >= 600 or active_minerals_count < 14 or self.time > 600)
                    and self.can_afford(UnitTypeId.COMMANDCENTER)
                ):
                    should_expand = True

        if should_expand:
            await self.expand_now()
            self.telemetry.log_event(f"자원 확장: 제{total_cc + 1}기지(멀티) 건설 착공!", "expansion")

        # 5. Supply Depot logic (입구 보급고 심시티 + 스마트 게이트)
        pending_depots = self.already_pending(UnitTypeId.SUPPLYDEPOT)
        buffer = 14 if total_cc >= 3 else (8 if total_cc >= 2 else 4)
        max_pending_depots = 3 if total_cc >= 3 else 2

        if self.supply_left < buffer and pending_depots < max_pending_depots and self.supply_cap < 200:
            if self.can_afford(UnitTypeId.SUPPLYDEPOT):
                existing_wall_blds = self.structures({UnitTypeId.SUPPLYDEPOT, UnitTypeId.SUPPLYDEPOTLOWERED, UnitTypeId.BUNKER})
                free_corners = [
                    p for p in self._safe_corner_depots()
                    if not existing_wall_blds.closer_than(1.2, p)
                ]

                placed_depot = False
                if free_corners:
                    for corner_pos in free_corners:
                        if await self.can_place_single(UnitTypeId.SUPPLYDEPOT, corner_pos):
                            worker = self.select_build_worker(corner_pos)
                            if worker:
                                self.do(worker.build(UnitTypeId.SUPPLYDEPOT, corner_pos), subtract_cost=True, ignore_warning=True)
                                placed_depot = True
                                break

                if not placed_depot:
                    pos = await self.find_safe_main_placement(UnitTypeId.SUPPLYDEPOT)
                    if pos:
                        worker = self.select_build_worker(pos)
                        if worker:
                            self.do(worker.build(UnitTypeId.SUPPLYDEPOT, pos), subtract_cost=True, ignore_warning=True)

        # Smart Gate: Raise if enemies approach ramp choke; otherwise keep lowered for unit flow
        enemies_near_ramp = self.enemy_units.closer_than(16, ramp_choke)
        if enemies_near_ramp:
            for depot in self.structures(UnitTypeId.SUPPLYDEPOTLOWERED):
                if depot.distance_to(ramp_choke) < 7:
                    depot(AbilityId.MORPH_SUPPLYDEPOT_RAISE)
        else:
            for depot in self.structures(UnitTypeId.SUPPLYDEPOT).ready:
                depot(AbilityId.MORPH_SUPPLYDEPOT_LOWER)

        # 6. First Barracks (병영 1개 - 본진 내부 고지대에 부속 건물 공간을 확보하여 안전하게 건설)
        rax_structures = self.structures(UnitTypeId.BARRACKS)
        rax_count = rax_structures.amount + self.already_pending(UnitTypeId.BARRACKS)
        if rax_count < 1 and self.can_afford(UnitTypeId.BARRACKS):
            pos = await self.find_safe_main_placement(UnitTypeId.BARRACKS, addon_place=True)
            if pos:
                worker = self.select_build_worker(pos)
                if worker:
                    self.do(worker.build(UnitTypeId.BARRACKS, pos), subtract_cost=True, ignore_warning=True)

        # 7. Bunker Defense: 언덕 입구 정중앙(barracks_in_middle)에 3x3 벙커 직접 배치하여 입구 완전 밀폐!
        if self.strategy.build_bunker and rax_structures.amount >= 1:
            bunker_count = (
                self.structures(UnitTypeId.BUNKER).amount
                + self.already_pending(UnitTypeId.BUNKER)
            )
            # 1st Bunker: 입구 정중앙(barracks_in_middle)에 오차 없이 정확히 건설
            if bunker_count < 1 and self.can_afford(UnitTypeId.BUNKER):
                ramp_bunker_pos = self._safe_ramp_bunker_placement()
                placed_bunker = False
                if ramp_bunker_pos and await self.can_place_single(UnitTypeId.BUNKER, ramp_bunker_pos):
                    worker = self.select_build_worker(ramp_bunker_pos)
                    if worker:
                        self.do(worker.build(UnitTypeId.BUNKER, ramp_bunker_pos), subtract_cost=True, ignore_warning=True)
                        placed_bunker = True
                
                # Fallback: if exact position isn't available, build at top center
                if not placed_bunker:
                    choke_bunker_pos = ramp_choke.towards(main_base.position, 2.0)
                    await self.build(UnitTypeId.BUNKER, near=choke_bunker_pos)

            # 2nd Bunker: 앞마당 길목(2차 최전선)
            elif (
                self.strategy.bunker_at_natural
                and total_cc >= 2
                and bunker_count < 2
                and self.can_afford(UnitTypeId.BUNKER)
            ):
                if other_ccs:
                    nat_cc = other_ccs.first
                    nat_choke = nat_cc.position.towards(self.game_info.map_center, 8)
                    await self.build(UnitTypeId.BUNKER, near=nat_choke)

        # 8. Additional Barracks (멀티 확보 및 자원 누적 시 최대 7~8병영까지 생산 인프라 확장)
        target_rax = self.strategy.target_barracks
        if total_cc >= 3 and self.minerals > 600:
            target_rax = min(8, self.strategy.target_barracks + 2)

        if (
            self.structures(UnitTypeId.BUNKER).amount + self.already_pending(UnitTypeId.BUNKER) >= 1
            or not self.strategy.build_bunker
        ):
            if rax_count < target_rax and self.can_afford(UnitTypeId.BARRACKS):
                pos = await self.find_safe_main_placement(UnitTypeId.BARRACKS, addon_place=True)
                if pos:
                    worker = self.select_build_worker(pos)
                    if worker:
                        self.do(worker.build(UnitTypeId.BARRACKS, pos), subtract_cost=True, ignore_warning=True)



        # Garrison up to 4 Marines inside each ready Bunker
        for bunker in self.structures(UnitTypeId.BUNKER).ready:
            if bunker.cargo_used < bunker.cargo_max:
                idle_marines = self.units(UnitTypeId.MARINE).idle
                if idle_marines:
                    bunker(AbilityId.LOAD_BUNKER, idle_marines.first)

        # SCV Auto-Repair for defensive structures
        damaged_defenses = self.structures({
            UnitTypeId.BUNKER, UnitTypeId.SUPPLYDEPOT,
            UnitTypeId.SUPPLYDEPOTLOWERED, UnitTypeId.MISSILETURRET
        }).filter(lambda s: s.health < s.health_max)
        for bld in damaged_defenses:
            close_scvs = workers.closer_than(15, bld)
            if close_scvs:
                close_scvs.first(AbilityId.EFFECT_REPAIR, bld)

        # 8. Vespene Gas: Refineries for all ready Command Centers
        if self.strategy.build_refinery and self.structures(UnitTypeId.BARRACKS).amount >= 1:
            for cc in cc_list.ready:
                for vespene in self.vespene_geyser.closer_than(15, cc):
                    if self.gas_buildings.closer_than(1.0, vespene):
                        continue
                    if self.already_pending(UnitTypeId.REFINERY) >= 1:
                        break
                    if self.can_afford(UnitTypeId.REFINERY):
                        worker = self.select_build_worker(vespene.position)
                        if worker:
                            worker.build_gas(vespene)
                            break

        # 9. Barracks Addons: Matchup-driven Tech Labs (Marauders/Upgrades) + Reactors (Marine Spam)
        ready_barracks = self.structures(UnitTypeId.BARRACKS).ready
        tech_lab_count = (
            self.structures(UnitTypeId.BARRACKSTECHLAB).amount
            + self.already_pending(UnitTypeId.BARRACKSTECHLAB)
        )
        reactor_count = (
            self.structures(UnitTypeId.BARRACKSREACTOR).amount
            + self.already_pending(UnitTypeId.BARRACKSREACTOR)
        )

        for rax in ready_barracks.idle:
            if not rax.has_add_on:
                addon_slot = rax.position.offset((2.5, -0.5))
                if await self.can_place_single(UnitTypeId.SUPPLYDEPOT, addon_slot):
                    if tech_lab_count < self.strategy.barracks_techlab_target and self.can_afford(UnitTypeId.BARRACKSTECHLAB):
                        rax.build(UnitTypeId.BARRACKSTECHLAB)
                        tech_lab_count += 1
                        break
                    elif reactor_count < self.strategy.barracks_reactor_target and self.can_afford(UnitTypeId.BARRACKSREACTOR):
                        rax.build(UnitTypeId.BARRACKSREACTOR)
                        reactor_count += 1
                        break


        # 10. Factory (군수공장 2개 + 기술실) - 본진 내부 고지대에만 안전하게 건설
        factory_count = (
            self.structures(UnitTypeId.FACTORY).amount
            + self.already_pending(UnitTypeId.FACTORY)
        )
        if (
            self.strategy.build_factory
            and self.structures(UnitTypeId.BARRACKS).ready
            and factory_count < self.strategy.target_factories
        ):
            if self.can_afford(UnitTypeId.FACTORY):
                pos = await self.find_safe_main_placement(UnitTypeId.FACTORY, addon_place=True)
                if pos:
                    worker = self.select_build_worker(pos)
                    if worker:
                        self.do(worker.build(UnitTypeId.FACTORY, pos), subtract_cost=True, ignore_warning=True)

        # Factory Tech Labs for Siege Tanks (오른쪽 부속 슬롯 공간 확인 후 즉각 건설)
        for factory in self.structures(UnitTypeId.FACTORY).ready.idle:
            if not factory.has_add_on:
                addon_slot = factory.position.offset((2.5, -0.5))
                if await self.can_place_single(UnitTypeId.SUPPLYDEPOT, addon_slot) and self.can_afford(UnitTypeId.FACTORYTECHLAB):
                    factory.build(UnitTypeId.FACTORYTECHLAB)
                    break

        # 11. Starport (우주공항 1개) - 본진 내부 고지대에만 안전하게 건설
        starport_count = (
            self.structures(UnitTypeId.STARPORT).amount
            + self.already_pending(UnitTypeId.STARPORT)
        )
        if (
            self.strategy.build_starport
            and self.structures(UnitTypeId.FACTORY).ready
            and starport_count < self.strategy.target_starports
        ):
            if self.can_afford(UnitTypeId.STARPORT):
                pos = await self.find_safe_main_placement(UnitTypeId.STARPORT, addon_place=True)
                if pos:
                    worker = self.select_build_worker(pos)
                    if worker:
                        self.do(worker.build(UnitTypeId.STARPORT, pos), subtract_cost=True, ignore_warning=True)


        # Calculate real-time effective utility weights first (with Fog-of-War scouted tech memory)
        effective_weights = self.unit_optimizer.get_effective_weights(
            enemy_race=self.actual_enemy_race,
            enemy_units=self.enemy_units,
            game_time=self.time,
            minerals=self.minerals,
            vespene=self.vespene,
            seen_enemy_structures=self.seen_enemy_structures,
        )

        # Snapshot active forces to make composition-driven, rational tech & upgrade decisions
        bio_forces = self.units(UnitTypeId.MARINE) | self.units(UnitTypeId.MARAUDER) | self.units(UnitTypeId.REAPER)
        mech_ground_forces = (
            self.units(UnitTypeId.SIEGETANK)
            | self.units(UnitTypeId.SIEGETANKSIEGED)
            | self.units(UnitTypeId.THOR)
            | self.units(UnitTypeId.THORAP)
            | self.units(UnitTypeId.HELLIONTANK)
            | self.units(UnitTypeId.HELLION)
            | self.units(UnitTypeId.CYCLONE)
            | self.units(UnitTypeId.WIDOWMINE)
            | self.units(UnitTypeId.WIDOWMINEBURROWED)
        )
        air_forces = (
            self.units(UnitTypeId.BATTLECRUISER)
            | self.units(UnitTypeId.VIKINGFIGHTER)
            | self.units(UnitTypeId.VIKINGASSAULT)
            | self.units(UnitTypeId.LIBERATOR)
            | self.units(UnitTypeId.LIBERATORAG)
            | self.units(UnitTypeId.BANSHEE)
            | self.units(UnitTypeId.RAVEN)
        )

        # 12. Engineering Bay (공학연구소) & Missile Turrets
        # 건물을 짓는 목적: 바이오닉 병력이 실존하거나(5기+), 공중/은폐 방어용 터렛이 필요할 때만 건설!
        if self.strategy.build_engineering_bay:
            ebay_count = (
                self.structures(UnitTypeId.ENGINEERINGBAY).amount
                + self.already_pending(UnitTypeId.ENGINEERINGBAY)
            )
            needs_ebay = (len(bio_forces) >= 5 or self.strategy.build_missile_turrets or effective_weights.get("marine", 1.0) >= 0.9)
            if ebay_count < 1 and needs_ebay and self.structures(UnitTypeId.BARRACKS).ready and self.can_afford(UnitTypeId.ENGINEERINGBAY):
                pos = await self.find_safe_main_placement(UnitTypeId.ENGINEERINGBAY)
                if pos:
                    worker = self.select_build_worker(pos)
                    if worker:
                        self.do(worker.build(UnitTypeId.ENGINEERINGBAY, pos), subtract_cost=True, ignore_warning=True)

            # Infantry Upgrades: 바이오닉 병력이 최소 6기 이상 전장에 있을 때만 연구 (순수 메카닉 시 낭비 차단)
            if len(bio_forces) >= 6:
                armory_ready = self.structures(UnitTypeId.ARMORY).ready
                for ebay in self.structures(UnitTypeId.ENGINEERINGBAY).ready.idle:
                    # Weapons: 1 -> 2 -> 3
                    if self.strategy.research_weapons:
                        if self.already_pending_upgrade(UpgradeId.TERRANINFANTRYWEAPONSLEVEL1) == 0 and self.can_afford(UpgradeId.TERRANINFANTRYWEAPONSLEVEL1):
                            ebay.research(UpgradeId.TERRANINFANTRYWEAPONSLEVEL1)
                            continue
                        elif armory_ready and self.already_pending_upgrade(UpgradeId.TERRANINFANTRYWEAPONSLEVEL2) == 0 and self.can_afford(UpgradeId.TERRANINFANTRYWEAPONSLEVEL2):
                            ebay.research(UpgradeId.TERRANINFANTRYWEAPONSLEVEL2)
                            continue
                        elif armory_ready and self.already_pending_upgrade(UpgradeId.TERRANINFANTRYWEAPONSLEVEL3) == 0 and self.can_afford(UpgradeId.TERRANINFANTRYWEAPONSLEVEL3):
                            ebay.research(UpgradeId.TERRANINFANTRYWEAPONSLEVEL3)
                            continue

                    # Armors: 1 -> 2 -> 3
                    if self.strategy.research_armor:
                        if self.already_pending_upgrade(UpgradeId.TERRANINFANTRYARMORSLEVEL1) == 0 and self.can_afford(UpgradeId.TERRANINFANTRYARMORSLEVEL1):
                            ebay.research(UpgradeId.TERRANINFANTRYARMORSLEVEL1)
                            continue
                        elif armory_ready and self.already_pending_upgrade(UpgradeId.TERRANINFANTRYARMORSLEVEL2) == 0 and self.can_afford(UpgradeId.TERRANINFANTRYARMORSLEVEL2):
                            ebay.research(UpgradeId.TERRANINFANTRYARMORSLEVEL2)
                            continue
                        elif armory_ready and self.already_pending_upgrade(UpgradeId.TERRANINFANTRYARMORSLEVEL3) == 0 and self.can_afford(UpgradeId.TERRANINFANTRYARMORSLEVEL3):
                            ebay.research(UpgradeId.TERRANINFANTRYARMORSLEVEL3)
                            continue

            # Building armor & sensor range (미사일 포탑 2기 이상 구축되고 자원 여유 시)
            turret_count = self.structures(UnitTypeId.MISSILETURRET).amount
            if turret_count >= 2 and self.minerals > 500 and self.vespene > 200:
                for ebay in self.structures(UnitTypeId.ENGINEERINGBAY).ready.idle:
                    if self.already_pending_upgrade(UpgradeId.TERRANBUILDINGARMOR) == 0 and self.can_afford(UpgradeId.TERRANBUILDINGARMOR):
                        ebay.research(UpgradeId.TERRANBUILDINGARMOR)
                    elif self.already_pending_upgrade(UpgradeId.HISECAUTOTRACKING) == 0 and self.can_afford(UpgradeId.HISECAUTOTRACKING):
                        ebay.research(UpgradeId.HISECAUTOTRACKING)

            # Missile Turrets for Air & Cloaked unit defense (적 테크 및 종족별 능동 대응)
            has_air_threat = bool(self.seen_enemy_structures & {
                UnitTypeId.SPIRE, UnitTypeId.GREATERSPIRE,
                UnitTypeId.STARGATE, UnitTypeId.FLEETBEACON,
                UnitTypeId.DARKSHRINE, UnitTypeId.TWILIGHTCOUNCIL,
                UnitTypeId.STARPORTTECHLAB
            })
            needs_turret = self.strategy.build_missile_turrets or has_air_threat
            if needs_turret and self.structures(UnitTypeId.ENGINEERINGBAY).ready:
                target_turrets = 3 if (has_air_threat or total_cc >= 2) else 2
                t_amount = turret_count + self.already_pending(UnitTypeId.MISSILETURRET)
                if t_amount < target_turrets and self.can_afford(UnitTypeId.MISSILETURRET):
                    if t_amount == 0:
                        m_pos = main_base.position.towards(self.game_info.map_center, -4)
                        await self.build(UnitTypeId.MISSILETURRET, near=m_pos)
                    elif t_amount == 1 and other_ccs:
                        nat_cc = other_ccs.first
                        nat_turret_pos = nat_cc.position.towards(self.game_info.map_center, 7)
                        await self.build(UnitTypeId.MISSILETURRET, near=nat_turret_pos)
                    elif t_amount == 2:
                        m_pos = main_base.position.towards(self.game_info.map_center, 6)
                        await self.build(UnitTypeId.MISSILETURRET, near=m_pos)

        # 13. Barracks Tech Lab Research: 보병 주력일 때 종족 맞춤형 순차 연구
        if len(bio_forces) >= 4:
            for lab in self.structures(UnitTypeId.BARRACKSTECHLAB).ready.idle:
                if self.strategy.priority_upgrade == "concussive_first":
                    # 토스전/복합전: 불곰 충격탄 선행 연구 (추적자/광전사 기동력 봉쇄 & 카이팅 극대화)
                    if self.units(UnitTypeId.MARAUDER).amount >= 1 and self.already_pending_upgrade(UpgradeId.PUNISHERGRENADES) == 0 and self.can_afford(UpgradeId.PUNISHERGRENADES):
                        lab.research(UpgradeId.PUNISHERGRENADES)
                        continue
                    elif self.strategy.research_stimpack and self.already_pending_upgrade(UpgradeId.STIMPACK) == 0 and self.can_afford(UpgradeId.STIMPACK):
                        lab.research(UpgradeId.STIMPACK)
                        continue
                    elif self.strategy.research_combat_shield and self.already_pending_upgrade(UpgradeId.SHIELDWALL) == 0 and self.can_afford(UpgradeId.SHIELDWALL):
                        lab.research(UpgradeId.SHIELDWALL)
                        continue
                else:
                    # 저그전/테란전: 스팀팩 -> 전투 방패 -> 충격탄 순차 연구
                    if self.strategy.research_stimpack and self.already_pending_upgrade(UpgradeId.STIMPACK) == 0 and self.can_afford(UpgradeId.STIMPACK):
                        lab.research(UpgradeId.STIMPACK)
                        continue
                    elif self.strategy.research_combat_shield and self.already_pending_upgrade(UpgradeId.SHIELDWALL) == 0 and self.can_afford(UpgradeId.SHIELDWALL):
                        lab.research(UpgradeId.SHIELDWALL)
                        continue
                    elif self.strategy.research_concussive_shells and self.units(UnitTypeId.MARAUDER).amount >= 2 and self.already_pending_upgrade(UpgradeId.PUNISHERGRENADES) == 0 and self.can_afford(UpgradeId.PUNISHERGRENADES):
                        lab.research(UpgradeId.PUNISHERGRENADES)
                        continue

        # 13-B. Armory (무기고) 건설 및 차량/함선 공방 1~3업 연구
        # 무기고 건설 조건: 토르/기갑병 의향, 메카닉 병력 실존, 적 공중위협(둥지탑 등), 또는 보병 2/2업 해금
        wants_thor = (effective_weights.get("thor", 0.5) >= 0.75 and total_cc >= 2)
        has_mech = (len(mech_ground_forces) >= 2 or len(air_forces) >= 2)
        has_air_threat = bool(self.seen_enemy_structures & {UnitTypeId.SPIRE, UnitTypeId.GREATERSPIRE, UnitTypeId.STARGATE})
        needs_infantry_tier2 = (len(bio_forces) >= 12 and self.already_pending_upgrade(UpgradeId.TERRANINFANTRYWEAPONSLEVEL1) == 1)
        needs_armory = (wants_thor or has_mech or has_air_threat or needs_infantry_tier2)

        if self.strategy.build_armory and self.structures(UnitTypeId.FACTORY).ready and needs_armory:
            armory_count = self.structures(UnitTypeId.ARMORY).amount + self.already_pending(UnitTypeId.ARMORY)
            if armory_count < (2 if total_cc >= 3 and self.minerals > 700 else 1) and self.can_afford(UnitTypeId.ARMORY):
                pos = await self.find_safe_main_placement(UnitTypeId.ARMORY, addon_place=False)
                if pos:
                    worker = self.select_build_worker(pos)
                    if worker:
                        self.do(worker.build(UnitTypeId.ARMORY, pos), subtract_cost=True, ignore_warning=True)

            for armory in self.structures(UnitTypeId.ARMORY).ready.idle:
                # 1. Vehicle Weapons: 지상 메카닉 병력이 최소 2기 이상 있을 때만 연구
                if self.strategy.research_mech_weapons and len(mech_ground_forces) >= 2:
                    if self.already_pending_upgrade(UpgradeId.TERRANVEHICLEWEAPONSLEVEL1) == 0 and self.can_afford(UpgradeId.TERRANVEHICLEWEAPONSLEVEL1):
                        armory.research(UpgradeId.TERRANVEHICLEWEAPONSLEVEL1)
                        continue
                    elif self.already_pending_upgrade(UpgradeId.TERRANVEHICLEWEAPONSLEVEL2) == 0 and self.can_afford(UpgradeId.TERRANVEHICLEWEAPONSLEVEL2):
                        armory.research(UpgradeId.TERRANVEHICLEWEAPONSLEVEL2)
                        continue
                    elif self.already_pending_upgrade(UpgradeId.TERRANVEHICLEWEAPONSLEVEL3) == 0 and self.can_afford(UpgradeId.TERRANVEHICLEWEAPONSLEVEL3):
                        armory.research(UpgradeId.TERRANVEHICLEWEAPONSLEVEL3)
                        continue

                # 2. Vehicle & Ship Plating / Armor: 메카닉/함대 병력이 3기 이상일 때만 연구
                if self.strategy.research_mech_armor and (len(mech_ground_forces) + len(air_forces)) >= 3:
                    if self.already_pending_upgrade(UpgradeId.TERRANVEHICLEANDSHIPARMORSLEVEL1) == 0 and self.can_afford(UpgradeId.TERRANVEHICLEANDSHIPARMORSLEVEL1):
                        armory.research(UpgradeId.TERRANVEHICLEANDSHIPARMORSLEVEL1)
                        continue
                    elif self.already_pending_upgrade(UpgradeId.TERRANVEHICLEANDSHIPARMORSLEVEL2) == 0 and self.can_afford(UpgradeId.TERRANVEHICLEANDSHIPARMORSLEVEL2):
                        armory.research(UpgradeId.TERRANVEHICLEANDSHIPARMORSLEVEL2)
                        continue
                    elif self.already_pending_upgrade(UpgradeId.TERRANVEHICLEANDSHIPARMORSLEVEL3) == 0 and self.can_afford(UpgradeId.TERRANVEHICLEANDSHIPARMORSLEVEL3):
                        armory.research(UpgradeId.TERRANVEHICLEANDSHIPARMORSLEVEL3)
                        continue

                # 3. Ship Weapons: 공중 유닛이 2기 이상 있을 때만 연구
                if self.strategy.research_mech_weapons and len(air_forces) >= 2:
                    if self.already_pending_upgrade(UpgradeId.TERRANSHIPWEAPONSLEVEL1) == 0 and self.can_afford(UpgradeId.TERRANSHIPWEAPONSLEVEL1):
                        armory.research(UpgradeId.TERRANSHIPWEAPONSLEVEL1)
                        continue
                    elif self.already_pending_upgrade(UpgradeId.TERRANSHIPWEAPONSLEVEL2) == 0 and self.can_afford(UpgradeId.TERRANSHIPWEAPONSLEVEL2):
                        armory.research(UpgradeId.TERRANSHIPWEAPONSLEVEL2)
                        continue
                    elif self.already_pending_upgrade(UpgradeId.TERRANSHIPWEAPONSLEVEL3) == 0 and self.can_afford(UpgradeId.TERRANSHIPWEAPONSLEVEL3):
                        armory.research(UpgradeId.TERRANSHIPWEAPONSLEVEL3)
                        continue

        # 13-C. Fusion Core (융합로) 건설 및 야마토포 / 해방선 고급 탄도학 연구
        # 융합로 건설 조건: AI가 전투순양함을 실제로 원하거나(배틀 가중치 0.8+), 해방선이 다수 활약 중일 때만 건설! (시간 경과로 짓는 낭비 100% 제거)
        wants_bc = (effective_weights.get("battlecruiser", 0.5) >= 0.8 and total_cc >= 2)
        has_many_libs = (self.units(UnitTypeId.LIBERATOR).amount + self.units(UnitTypeId.LIBERATORAG).amount >= 3)
        needs_fusion_core = (wants_bc or has_many_libs)

        if self.strategy.build_fusion_core and self.structures(UnitTypeId.STARPORT).ready and needs_fusion_core:
            fusion_count = self.structures(UnitTypeId.FUSIONCORE).amount + self.already_pending(UnitTypeId.FUSIONCORE)
            if fusion_count < 1 and self.can_afford(UnitTypeId.FUSIONCORE):
                pos = await self.find_safe_main_placement(UnitTypeId.FUSIONCORE, addon_place=False)
                if pos:
                    worker = self.select_build_worker(pos)
                    if worker:
                        self.do(worker.build(UnitTypeId.FUSIONCORE, pos), subtract_cost=True, ignore_warning=True)

        for fc in self.structures(UnitTypeId.FUSIONCORE).ready.idle:
            if self.strategy.research_special_abilities:
                # 야마토포는 전투순양함이 최소 1기 이상 존재하거나 건조 중일 때만 연구!
                has_bc = (self.units(UnitTypeId.BATTLECRUISER).amount + self.already_pending(UnitTypeId.BATTLECRUISER)) >= 1
                if has_bc and self.already_pending_upgrade(UpgradeId.BATTLECRUISERENABLESPECIALIZATIONS) == 0 and self.can_afford(UpgradeId.BATTLECRUISERENABLESPECIALIZATIONS):
                    fc.research(UpgradeId.BATTLECRUISERENABLESPECIALIZATIONS)
                # 해방선 사거리는 해방선이 2기 이상 있을 때만 연구!
                has_lib = (self.units(UnitTypeId.LIBERATOR).amount + self.units(UnitTypeId.LIBERATORAG).amount) >= 2
                if has_lib and self.already_pending_upgrade(UpgradeId.LIBERATORAGRANGEUPGRADE) == 0 and self.can_afford(UpgradeId.LIBERATORAGRANGEUPGRADE):
                    fc.research(UpgradeId.LIBERATORAGRANGEUPGRADE)

        # 13-D. Ghost Academy (유령사관학교) 건설 및 개인 은폐 연구
        # 유령사관학교 건설 조건: 프로토스전 실드/스톰 카운터(ghost_priority)이거나 AI가 유령을 원할 때 건설
        ghost_w = effective_weights.get("ghost", 0.5)
        wants_ghost = (ghost_w >= 0.8 and total_cc >= 2) or (self.strategy.ghost_priority and total_cc >= 2 and self.time > 260)
        if self.strategy.build_ghost_academy and self.structures(UnitTypeId.BARRACKS).ready and wants_ghost:
            academy_count = (
                self.structures(UnitTypeId.GHOSTACADEMY).amount
                + self.already_pending(UnitTypeId.GHOSTACADEMY)
            )
            if academy_count < 1 and self.can_afford(UnitTypeId.GHOSTACADEMY):
                pos = await self.find_safe_main_placement(UnitTypeId.GHOSTACADEMY, addon_place=False)
                if pos:
                    worker = self.select_build_worker(pos)
                    if worker:
                        self.do(worker.build(UnitTypeId.GHOSTACADEMY, pos), subtract_cost=True, ignore_warning=True)

        for academy in self.structures(UnitTypeId.GHOSTACADEMY).ready.idle:
            if self.strategy.research_special_abilities:
                # 유령 은폐 연구는 유령이 최소 1기 이상 있거나 훈련 중일 때만 연구!
                has_ghost = (self.units(UnitTypeId.GHOST).amount + self.already_pending(UnitTypeId.GHOST)) >= 1
                if has_ghost and self.already_pending_upgrade(UpgradeId.PERSONALCLOAKING) == 0 and self.can_afford(UpgradeId.PERSONALCLOAKING):
                    academy.research(UpgradeId.PERSONALCLOAKING)

        # 13-E. Factory Tech Lab Research: 해당 유닛이 실제로 존재할 때만 특수기술 연구
        if self.strategy.research_special_abilities:
            for flab in self.structures(UnitTypeId.FACTORYTECHLAB).ready.idle:
                # 지옥불: 화염차/화염기갑병 3기 이상
                if (self.units(UnitTypeId.HELLIONTANK).amount + self.units(UnitTypeId.HELLION).amount) >= 3 and self.already_pending_upgrade(UpgradeId.HIGHCAPACITYBARRELS) == 0 and self.can_afford(UpgradeId.HIGHCAPACITYBARRELS):
                    flab.research(UpgradeId.HIGHCAPACITYBARRELS)
                # 사이클론 락온 가속: 사이클론 2기 이상
                elif self.units(UnitTypeId.CYCLONE).amount >= 2 and self.already_pending_upgrade(UpgradeId.CYCLONELOCKONDAMAGEUPGRADE) == 0 and self.can_afford(UpgradeId.CYCLONELOCKONDAMAGEUPGRADE):
                    flab.research(UpgradeId.CYCLONELOCKONDAMAGEUPGRADE)
                # 땅거미 지뢰 천공발톱: 지뢰 2기 이상
                elif (self.units(UnitTypeId.WIDOWMINE).amount + self.units(UnitTypeId.WIDOWMINEBURROWED).amount) >= 2 and self.already_pending_upgrade(UpgradeId.DRILLCLAWS) == 0 and self.can_afford(UpgradeId.DRILLCLAWS):
                    flab.research(UpgradeId.DRILLCLAWS)
                # 스마트 서보: 메카닉 대군 5기 이상
                elif len(mech_ground_forces) >= 5 and self.already_pending_upgrade(UpgradeId.SMARTSERVOS) == 0 and self.can_afford(UpgradeId.SMARTSERVOS):
                    flab.research(UpgradeId.SMARTSERVOS)

        # 13-F. Starport Tech Lab Construction & Research
        for starport in self.structures(UnitTypeId.STARPORT).ready.idle:
            if not starport.has_add_on and self.can_afford(UnitTypeId.STARPORTTECHLAB):
                addon_slot = starport.position.offset((2.5, -0.5))
                if await self.can_place_single(UnitTypeId.SUPPLYDEPOT, addon_slot):
                    starport.build(UnitTypeId.STARPORTTECHLAB)
                    break

        if self.strategy.research_special_abilities:
            for slab in self.structures(UnitTypeId.STARPORTTECHLAB).ready.idle:
                # 밴시 은폐: 밴시가 최소 1기 이상 있거나 생산 중일 때만 연구!
                has_banshee = (self.units(UnitTypeId.BANSHEE).amount + self.already_pending(UnitTypeId.BANSHEE)) >= 1
                if has_banshee and self.already_pending_upgrade(UpgradeId.BANSHEECLOAK) == 0 and self.can_afford(UpgradeId.BANSHEECLOAK):
                    slab.research(UpgradeId.BANSHEECLOAK)
                elif self.units(UnitTypeId.BANSHEE).amount >= 2 and self.already_pending_upgrade(UpgradeId.BANSHEESPEED) == 0 and self.can_afford(UpgradeId.BANSHEESPEED):
                    slab.research(UpgradeId.BANSHEESPEED)
        # 14. Unit Production (Top-Down Priority Allocation & Resource Reservation)
        # Helper: Soft Diminishing Utility Function (강제 상한선 없이 비례 샘플링 허용)
        def unit_utility(u_name: str, count: int, scale: float = 0.10) -> float:
            base_w = effective_weights.get(u_name, 0.5)
            return round(base_w / (1.0 + count * scale), 4)

        # Count active & pending units
        marine_count = self.units(UnitTypeId.MARINE).amount + self.already_pending(UnitTypeId.MARINE)
        reaper_count = self.units(UnitTypeId.REAPER).amount + self.already_pending(UnitTypeId.REAPER)
        marauder_count = self.units(UnitTypeId.MARAUDER).amount + self.already_pending(UnitTypeId.MARAUDER)
        ghost_count = self.units(UnitTypeId.GHOST).amount + self.already_pending(UnitTypeId.GHOST)
        ghost_academy_ready = self.structures(UnitTypeId.GHOSTACADEMY).ready

        thor_count = self.units(UnitTypeId.THOR).amount + self.units(UnitTypeId.THORAP).amount + self.already_pending(UnitTypeId.THOR)
        tank_count = self.units(UnitTypeId.SIEGETANK).amount + self.units(UnitTypeId.SIEGETANKSIEGED).amount + self.already_pending(UnitTypeId.SIEGETANK)
        cyclone_count = self.units(UnitTypeId.CYCLONE).amount + self.already_pending(UnitTypeId.CYCLONE)
        mine_count = self.units(UnitTypeId.WIDOWMINE).amount + self.units(UnitTypeId.WIDOWMINEBURROWED).amount + self.already_pending(UnitTypeId.WIDOWMINE)
        hellbat_count = self.units(UnitTypeId.HELLIONTANK).amount + self.already_pending(UnitTypeId.HELLIONTANK)
        hellion_count = self.units(UnitTypeId.HELLION).amount + self.already_pending(UnitTypeId.HELLION)
        armory_ready = self.structures(UnitTypeId.ARMORY).ready

        bc_count = self.units(UnitTypeId.BATTLECRUISER).amount + self.already_pending(UnitTypeId.BATTLECRUISER)
        raven_count = self.units(UnitTypeId.RAVEN).amount + self.already_pending(UnitTypeId.RAVEN)
        banshee_count = self.units(UnitTypeId.BANSHEE).amount + self.already_pending(UnitTypeId.BANSHEE)
        medivac_count = self.units(UnitTypeId.MEDIVAC).amount + self.already_pending(UnitTypeId.MEDIVAC)
        viking_count = self.units(UnitTypeId.VIKINGFIGHTER).amount + self.units(UnitTypeId.VIKINGASSAULT).amount + self.already_pending(UnitTypeId.VIKINGFIGHTER)
        lib_count = self.units(UnitTypeId.LIBERATOR).amount + self.units(UnitTypeId.LIBERATORAG).amount + self.already_pending(UnitTypeId.LIBERATOR)
        fusion_ready = self.structures(UnitTypeId.FUSIONCORE).ready

        # --- Resource Reservation & Golden Ratio Quotas ---
        # Bio-Medivac Golden Ratio: 1 Medivac per 8 Marines
        needs_medivac = (marine_count >= 8 and medivac_count < max(2, marine_count // 8))
        
        idle_starports = self.structures(UnitTypeId.STARPORT).ready.idle
        idle_factories = self.structures(UnitTypeId.FACTORY).ready.idle

        # 14-A. Starport Production (Tier 3 Priority: 의료선, 바이킹, 해방선, 밤까마귀, 밴시, 배틀크루저)
        for starport in idle_starports:
            if self.supply_left < 2:
                break
            addon_type = None
            if starport.add_on_tag:
                addon = self.structures.find_by_tag(starport.add_on_tag)
                if addon: addon_type = addon.type_id
            has_techlab = (addon_type == UnitTypeId.STARPORTTECHLAB)
            candidates = []

            # Medivac has top priority if bio ball needs healing!
            medivac_utility_boost = 1.8 if needs_medivac else 1.0
            if self.strategy.train_medivacs and self.can_afford(UnitTypeId.MEDIVAC) and self.supply_left >= 2:
                candidates.append((unit_utility("medivac", medivac_count, 0.12) * medivac_utility_boost, UnitTypeId.MEDIVAC, "medivac"))
            if self.strategy.train_vikings and self.can_afford(UnitTypeId.VIKINGFIGHTER) and self.supply_left >= 2:
                candidates.append((unit_utility("viking", viking_count, 0.10), UnitTypeId.VIKINGFIGHTER, "viking"))
            if self.strategy.train_liberators and self.can_afford(UnitTypeId.LIBERATOR) and self.supply_left >= 3:
                candidates.append((unit_utility("liberator", lib_count, 0.15), UnitTypeId.LIBERATOR, "liberator"))

            if has_techlab:
                if self.strategy.train_battlecruisers and fusion_ready and self.can_afford(UnitTypeId.BATTLECRUISER) and self.supply_left >= 6:
                    candidates.append((unit_utility("battlecruiser", bc_count, 0.10), UnitTypeId.BATTLECRUISER, "battlecruiser"))
                if self.strategy.train_ravens and self.can_afford(UnitTypeId.RAVEN) and self.supply_left >= 3:
                    candidates.append((unit_utility("raven", raven_count, 0.35), UnitTypeId.RAVEN, "raven"))
                if self.strategy.train_banshees and self.can_afford(UnitTypeId.BANSHEE) and self.supply_left >= 3:
                    candidates.append((unit_utility("banshee", banshee_count, 0.15), UnitTypeId.BANSHEE, "banshee"))

            if candidates:
                candidates.sort(key=lambda c: c[0], reverse=True)
                _, best_type, best_name = candidates[0]
                starport.train(best_type)
                self.units_produced_tracker[best_name] = self.units_produced_tracker.get(best_name, 0) + 1
                if best_name == "battlecruiser":
                    bc_count += 1
                    self.telemetry.log_event("함대 출격: 전투순양함(Battlecruiser) 건조 착수!", "battlecruiser")
                elif best_name == "raven": raven_count += 1
                elif best_name == "banshee": banshee_count += 1
                elif best_name == "medivac":
                    medivac_count += 1
                    needs_medivac = (marine_count >= 8 and medivac_count < max(2, marine_count // 8))
                elif best_name == "viking": viking_count += 1
                elif best_name == "liberator": lib_count += 1

        # 14-B. Factory Production (Tier 2 Priority: 공성전차, 토르, 화염차, 화염기갑병, 사이클론, 땅거미 지뢰)
        for factory in idle_factories:
            if self.supply_left < 2:
                break
            addon_type = None
            if factory.add_on_tag:
                addon = self.structures.find_by_tag(factory.add_on_tag)
                if addon: addon_type = addon.type_id
            has_techlab = (addon_type == UnitTypeId.FACTORYTECHLAB)
            candidates = []

            # Siege Tanks & Thors are top priority if techlab is ready!
            if has_techlab:
                if self.strategy.train_thors and armory_ready and self.can_afford(UnitTypeId.THOR) and self.supply_left >= 6:
                    candidates.append((unit_utility("thor", thor_count, 0.10) * 1.5, UnitTypeId.THOR, "thor"))
                if self.strategy.train_siege_tanks and self.can_afford(UnitTypeId.SIEGETANK) and self.supply_left >= 3:
                    candidates.append((unit_utility("siegetank", tank_count, 0.08) * 1.6, UnitTypeId.SIEGETANK, "siegetank"))
                if self.strategy.train_cyclones and self.can_afford(UnitTypeId.CYCLONE) and self.supply_left >= 3:
                    candidates.append((unit_utility("cyclone", cyclone_count, 0.10), UnitTypeId.CYCLONE, "cyclone"))
                if self.strategy.train_widow_mines and self.can_afford(UnitTypeId.WIDOWMINE) and self.supply_left >= 2:
                    candidates.append((unit_utility("widowmine", mine_count, 0.10), UnitTypeId.WIDOWMINE, "widowmine"))
                if self.strategy.train_hellbats and armory_ready and self.can_afford(UnitTypeId.HELLIONTANK) and self.supply_left >= 2:
                    candidates.append((unit_utility("hellbat", hellbat_count, 0.08), UnitTypeId.HELLIONTANK, "hellbat"))
                if self.strategy.train_hellions and self.can_afford(UnitTypeId.HELLION) and self.supply_left >= 2:
                    candidates.append((unit_utility("hellion", hellion_count, 0.12), UnitTypeId.HELLION, "hellion"))
            else:
                if self.strategy.train_cyclones and self.can_afford(UnitTypeId.CYCLONE) and self.supply_left >= 3:
                    candidates.append((unit_utility("cyclone", cyclone_count, 0.10), UnitTypeId.CYCLONE, "cyclone"))
                if self.strategy.train_widow_mines and self.can_afford(UnitTypeId.WIDOWMINE) and self.supply_left >= 2:
                    candidates.append((unit_utility("widowmine", mine_count, 0.10), UnitTypeId.WIDOWMINE, "widowmine"))
                if self.strategy.train_hellbats and armory_ready and self.can_afford(UnitTypeId.HELLIONTANK) and self.supply_left >= 2:
                    candidates.append((unit_utility("hellbat", hellbat_count, 0.08), UnitTypeId.HELLIONTANK, "hellbat"))
                if self.strategy.train_hellions and self.can_afford(UnitTypeId.HELLION) and self.supply_left >= 2:
                    candidates.append((unit_utility("hellion", hellion_count, 0.12), UnitTypeId.HELLION, "hellion"))

            if candidates:
                candidates.sort(key=lambda c: c[0], reverse=True)
                _, best_type, best_name = candidates[0]
                factory.train(best_type)
                self.units_produced_tracker[best_name] = self.units_produced_tracker.get(best_name, 0) + 1
                if best_name == "thor": thor_count += 1
                elif best_name == "siegetank": tank_count += 1
                elif best_name == "cyclone": cyclone_count += 1
                elif best_name == "widowmine": mine_count += 1
                elif best_name == "hellbat": hellbat_count += 1
                elif best_name == "hellion": hellion_count += 1

        # 14-C. Barracks Production (Tier 1: 해병, 사신, 불곰, 유령 - 가용 미네랄 한도 내 생산)
        # If Starport desperately needs to build the first medivac, don't let barracks steal the 100 minerals
        starport_waiting_for_medivac = (needs_medivac and self.structures(UnitTypeId.STARPORT).amount > 0 and medivac_count == 0)

        for rax in self.structures(UnitTypeId.BARRACKS).ready.idle:
            if self.supply_left < 1:
                break

            if starport_waiting_for_medivac and self.minerals < 100 and self.vespene >= 100:
                break

            addon_type = None
            if rax.add_on_tag:
                addon = self.structures.find_by_tag(rax.add_on_tag)
                if addon: addon_type = addon.type_id

            has_techlab = (addon_type == UnitTypeId.BARRACKSTECHLAB)
            candidates = []

            if has_techlab:
                if self.strategy.train_ghosts and ghost_academy_ready and self.can_afford(UnitTypeId.GHOST) and self.supply_left >= 2:
                    candidates.append((unit_utility("ghost", ghost_count, 0.20), UnitTypeId.GHOST, "ghost"))
                if self.strategy.train_marauders and self.can_afford(UnitTypeId.MARAUDER) and self.vespene >= 25 and self.supply_left >= 2:
                    candidates.append((unit_utility("marauder", marauder_count, 0.05), UnitTypeId.MARAUDER, "marauder"))
                if self.strategy.train_reapers and self.can_afford(UnitTypeId.REAPER) and self.supply_left >= 1:
                    candidates.append((unit_utility("reaper", reaper_count, 0.50), UnitTypeId.REAPER, "reaper"))
                if self.strategy.train_marines and self.can_afford(UnitTypeId.MARINE) and self.supply_left >= 1:
                    candidates.append((unit_utility("marine", marine_count, 0.03), UnitTypeId.MARINE, "marine"))
            else:
                if self.strategy.train_reapers and self.can_afford(UnitTypeId.REAPER) and self.supply_left >= 1:
                    candidates.append((unit_utility("reaper", reaper_count, 0.50), UnitTypeId.REAPER, "reaper"))
                if self.strategy.train_marines and self.can_afford(UnitTypeId.MARINE) and self.supply_left >= 1:
                    candidates.append((unit_utility("marine", marine_count, 0.03), UnitTypeId.MARINE, "marine"))

            if candidates:
                candidates.sort(key=lambda c: c[0], reverse=True)
                _, best_type, best_name = candidates[0]
                rax.train(best_type)
                self.units_produced_tracker[best_name] = self.units_produced_tracker.get(best_name, 0) + 1
                if best_name == "ghost": ghost_count += 1
                elif best_name == "marauder": marauder_count += 1
                elif best_name == "reaper": reaper_count += 1
                elif best_name == "marine": marine_count += 1

        # 15. Combat, Defense Anchoring & Micro-Control (제병 협동 전술 - 16종 전 유닛 통합 관제)
        marines = self.units(UnitTypeId.MARINE)
        marauders = self.units(UnitTypeId.MARAUDER)
        reapers = self.units(UnitTypeId.REAPER)
        ghosts = self.units(UnitTypeId.GHOST)
        bio = marines | marauders

        mobile_tanks = self.units(UnitTypeId.SIEGETANK)
        sieged_tanks = self.units(UnitTypeId.SIEGETANKSIEGED)
        tanks = mobile_tanks | sieged_tanks
        hellbats = self.units(UnitTypeId.HELLIONTANK)
        hellions = self.units(UnitTypeId.HELLION)
        widowmines = self.units(UnitTypeId.WIDOWMINE) | self.units(UnitTypeId.WIDOWMINEBURROWED)
        cyclones = self.units(UnitTypeId.CYCLONE)
        thors = self.units(UnitTypeId.THOR) | self.units(UnitTypeId.THORAP)

        medivacs = self.units(UnitTypeId.MEDIVAC)
        vikings = self.units(UnitTypeId.VIKINGFIGHTER) | self.units(UnitTypeId.VIKINGASSAULT)
        liberators = self.units(UnitTypeId.LIBERATOR) | self.units(UnitTypeId.LIBERATORAG)
        ravens = self.units(UnitTypeId.RAVEN)
        banshees = self.units(UnitTypeId.BANSHEE)
        battlecruisers = self.units(UnitTypeId.BATTLECRUISER)

        total_combat_army = (
            len(bio) + len(reapers) + len(ghosts)
            + len(tanks) + len(hellbats) + len(hellions) + len(widowmines) + len(cyclones) + len(thors)
            + len(medivacs) + len(vikings) + len(liberators) + len(ravens) + len(banshees) + len(battlecruisers)
        )

        # Determine Active Frontline Defense Anchor (앞마당 기지가 있으면 앞마당이 전선 집결지!)
        bunkers = self.structures(UnitTypeId.BUNKER).ready
        if other_ccs and bunkers:
            nat_cc = other_ccs.first
            frontline_bunker = bunkers.closest_to(nat_cc)
            rally_point = frontline_bunker.position.towards(nat_cc.position, 3.5)
        elif bunkers:
            rally_point = bunkers.first.position.towards(main_base.position, 3.5)
        else:
            rally_point = ramp_choke.towards(main_base.position, 3.5)

        # Smart Production Rally: Direct newly produced units immediately towards the open frontline
        for pb in self.structures({UnitTypeId.BARRACKS, UnitTypeId.FACTORY, UnitTypeId.STARPORT}).ready:
            pb(AbilityId.RALLY_BUILDING, rally_point)

        # Anti-Stuck & Trapped Combat Unit Watchdog:
        # Detect combat ground units trapped between structures for > 4.5 seconds and unstick them
        # CRITICAL: Exclude SCVs and MULEs completely! Harvesters have dedicated mining distribution.
        now_time = self.time
        combat_stuck_candidates = self.units.filter(
            lambda x: (x.can_attack_ground or x.can_attack_air)
            and x.type_id not in {UnitTypeId.SCV, UnitTypeId.MULE}
            and not x.is_flying
            and x.is_moving
        )
        for u in combat_stuck_candidates:
            last_pos, stuck_time = self.unit_stuck_watch.get(u.tag, (u.position, now_time))
            if u.distance_to(last_pos) < 0.3:
                if now_time - stuck_time >= 4.5:
                    # Unit is stuck in building maze!
                    # 1. Give move order towards wide open rally point
                    u.move(rally_point)
                    # 2. If an adjacent production building is idle and has no active add-on research, lift off briefly!
                    trapping_blds = self.structures({UnitTypeId.BARRACKS, UnitTypeId.FACTORY, UnitTypeId.STARPORT}).closer_than(3.2, u.position).idle
                    for tb in trapping_blds:
                        if not tb.is_flying and not tb.has_add_on:
                            tb(AbilityId.LIFT)
                            break
                    self.unit_stuck_watch[u.tag] = (u.position, now_time)
                else:
                    self.unit_stuck_watch[u.tag] = (last_pos, stuck_time)
            else:
                self.unit_stuck_watch[u.tag] = (u.position, now_time)


        # Land any lifted buildings once units have cleared
        for fb in self.structures({UnitTypeId.BARRACKSFLYING, UnitTypeId.FACTORYFLYING, UnitTypeId.STARPORTFLYING}).idle:
            if fb.distance_to(main_base.position) < 20:
                land_pos = await self.find_placement(UnitTypeId.BARRACKS, near=fb.position)
                if land_pos:
                    fb(AbilityId.LAND, land_pos)

        bio_center = bio.center if bio else rally_point
        enemy_units = self.enemy_units
        enemy_structures = self.enemy_structures

        if enemy_structures:
            target_pos = enemy_structures.closest_to(main_base).position
        elif self.enemy_start_locations:
            target_pos = self.enemy_start_locations[0]
        else:
            target_pos = self.game_info.map_center

        # Detect any enemies threatening our bases
        enemies_near_base = enemy_units.closer_than(24, main_base)
        if other_ccs:
            enemies_near_base = enemies_near_base | enemy_units.closer_than(24, other_ccs.first)

        if self.strategy.defend_base_on_attack and enemies_near_base:
            # Defend base immediately with all arms
            def_target = enemies_near_base.closest_to(main_base).position
            self.micro.micro_bio(bio, enemy_units, def_target)
            self.micro.micro_reapers(reapers, enemy_units, def_target, bio_center)
            self.micro.micro_ghosts(ghosts, enemy_units, def_target, bio_center)
            self.micro.micro_tanks(mobile_tanks, sieged_tanks, enemy_units, def_target, bio_center)
            self.micro.micro_hellbats(hellbats, enemy_units, def_target, bio_center)
            self.micro.micro_hellions(hellions, enemy_units, def_target, bio_center)
            self.micro.micro_widowmines(widowmines, enemy_units, def_target, bio_center)
            self.micro.micro_cyclones(cyclones, enemy_units, def_target, bio_center)
            self.micro.micro_thors(thors, enemy_units, def_target, bio_center)
            self.micro.micro_medivacs(medivacs, bio, bio_center)
            self.micro.micro_vikings(vikings, enemy_units, def_target, bio_center)
            self.micro.micro_liberators(liberators, enemy_units, def_target, bio_center)
            self.micro.micro_ravens(ravens, enemy_units, def_target, bio_center)
            self.micro.micro_banshees(banshees, enemy_units, def_target, bio_center)
            self.micro.micro_battlecruisers(battlecruisers, enemy_units, def_target)
        elif total_combat_army >= self.strategy.attack_army_threshold:
            # Full Combined Arms Assault Push!
            self.micro.micro_bio(bio, enemy_units, target_pos)
            self.micro.micro_reapers(reapers, enemy_units, target_pos, bio_center)
            self.micro.micro_ghosts(ghosts, enemy_units, target_pos, bio_center)
            self.micro.micro_tanks(mobile_tanks, sieged_tanks, enemy_units, target_pos, bio_center)
            self.micro.micro_hellbats(hellbats, enemy_units, target_pos, bio_center)
            self.micro.micro_hellions(hellions, enemy_units, target_pos, bio_center)
            self.micro.micro_widowmines(widowmines, enemy_units, target_pos, bio_center)
            self.micro.micro_cyclones(cyclones, enemy_units, target_pos, bio_center)
            self.micro.micro_thors(thors, enemy_units, target_pos, bio_center)
            self.micro.micro_medivacs(medivacs, bio, bio_center)
            self.micro.micro_vikings(vikings, enemy_units, target_pos, bio_center)
            self.micro.micro_liberators(liberators, enemy_units, target_pos, bio_center)
            self.micro.micro_ravens(ravens, enemy_units, target_pos, bio_center)
            self.micro.micro_banshees(banshees, enemy_units, target_pos, bio_center)
            self.micro.micro_battlecruisers(battlecruisers, enemy_units, target_pos)
        else:
            # Defense Anchor Mode:
            self.micro.micro_bio(bio, enemy_units, rally_point)
            self.micro.micro_reapers(reapers, enemy_units, rally_point, rally_point)
            self.micro.micro_ghosts(ghosts, enemy_units, rally_point, rally_point)
            self.micro.micro_defense_tanks(mobile_tanks, sieged_tanks, enemy_units, rally_point)
            self.micro.micro_hellbats(hellbats, enemy_units, rally_point, rally_point)
            self.micro.micro_hellions(hellions, enemy_units, rally_point, rally_point)
            self.micro.micro_widowmines(widowmines, enemy_units, rally_point, rally_point)
            self.micro.micro_cyclones(cyclones, enemy_units, rally_point, rally_point)
            self.micro.micro_thors(thors, enemy_units, rally_point, rally_point)
            self.micro.micro_medivacs(medivacs, bio, rally_point)
            self.micro.micro_vikings(vikings, enemy_units, rally_point, rally_point)
            self.micro.micro_liberators(liberators, enemy_units, rally_point, rally_point)
            self.micro.micro_ravens(ravens, enemy_units, rally_point, rally_point)
            self.micro.micro_banshees(banshees, enemy_units, rally_point, rally_point)
            self.micro.micro_battlecruisers(battlecruisers, enemy_units, rally_point)

        # 16. Live brief in console
        now = time.time()
        if total_combat_army >= self.strategy.attack_army_threshold:
            status = "풀업 대군 총공격 중!"
        elif cc_list.amount >= 3:
            status = f"제{cc_list.amount}기지 확장 및 거점 수비 중"
        elif total_cc >= 2:
            status = "앞마당 철벽 방어선 구축 중"
        else:
            status = "본진 방어선 및 기반 구축"

        if now - self.last_log_time > 5.0:
            self.last_log_time = now
            game_sec = int(self.time)
            mins, secs = divmod(game_sec, 60)
            turret_count = self.structures(UnitTypeId.MISSILETURRET).ready.amount
            orbital_count = self.townhalls(UnitTypeId.ORBITALCOMMAND).ready.amount

            extra_parts = []
            if thors: extra_parts.append(f"토르:{len(thors)}")
            if vikings: extra_parts.append(f"바이킹:{len(vikings)}")
            if hellbats: extra_parts.append(f"화기병:{len(hellbats)}")
            if battlecruisers: extra_parts.append(f"배틀:{len(battlecruisers)}")
            if ghosts: extra_parts.append(f"유령:{len(ghosts)}")
            if cyclones: extra_parts.append(f"사이클론:{len(cyclones)}")
            if liberators: extra_parts.append(f"해방선:{len(liberators)}")
            if ravens: extra_parts.append(f"밤까:{len(ravens)}")
            if banshees: extra_parts.append(f"밴시:{len(banshees)}")
            if widowmines: extra_parts.append(f"지뢰:{len(widowmines)}")
            if reapers: extra_parts.append(f"사신:{len(reapers)}")
            if hellions: extra_parts.append(f"화염차:{len(hellions)}")
            extra_str = f" | {' '.join(extra_parts)}" if extra_parts else ""

            matchup_tag = f"[{self.strategy.matchup}]" if self.strategy.matchup != "DEFAULT" else f"[{self.actual_enemy_race}]"
            intel_parts = []
            if self.scan_count > 0:
                intel_parts.append(f"스캔:{self.scan_count}회")
            if self.seen_enemy_structures:
                tech_names = [s.name for s in list(self.seen_enemy_structures)[:3]]
                intel_parts.append(f"적테크:{','.join(tech_names)}")
            intel_str = f" | {' '.join(intel_parts)}" if intel_parts else ""

            print(
                f"[AI 브리핑] {matchup_tag} [{mins:02d}:{secs:02d}] "
                f"기지: {cc_list.amount}개(궤도:{orbital_count}) | 미네랄: {self.minerals} | 가스: {self.vespene} | "
                f"일꾼: {len(workers)}/{dynamic_worker_cap}(대기:{self.idle_worker_count}) | "
                f"해병: {len(marines)} | 불곰: {len(marauders)} | 전차: {len(tanks)}(시즈:{len(sieged_tanks)}) | "
                f"의료선: {len(medivacs)}{extra_str}{intel_str} (군대: {total_combat_army}/{self.strategy.attack_army_threshold}) | {status}"
            )

        # 17. Live Telemetry Export for Web Dashboard & Radar Broadcast
        if status != self.prev_status:
            self.prev_status = status
            self.telemetry.log_event(f"전술 전환: {status}", "status")

        friendly_dots = []
        for u in self.units:
            friendly_dots.append({"x": round(u.position.x, 1), "y": round(u.position.y, 1), "t": u.type_id.name})
        for b in self.structures:
            friendly_dots.append({"x": round(b.position.x, 1), "y": round(b.position.y, 1), "t": b.type_id.name})

        enemy_dots = []
        for eu in self.enemy_units:
            enemy_dots.append({"x": round(eu.position.x, 1), "y": round(eu.position.y, 1), "t": eu.type_id.name})

        map_w = float(self.game_info.map_size[0])
        map_h = float(self.game_info.map_size[1])

        self.telemetry.export(
            game_time=self.time,
            minerals=self.minerals,
            vespene=self.vespene,
            supply_used=self.supply_used,
            supply_cap=self.supply_cap,
            workers_count=len(workers),
            marines_count=len(marines),
            marauders_count=len(marauders),
            tanks_mobile=len(mobile_tanks),
            tanks_sieged=len(sieged_tanks),
            medivacs_count=len(medivacs),
            bunkers_count=self.structures(UnitTypeId.BUNKER).ready.amount,
            turrets_count=self.structures(UnitTypeId.MISSILETURRET).ready.amount,
            cc_count=cc_list.amount,
            orbital_count=self.townhalls(UnitTypeId.ORBITALCOMMAND).ready.amount,
            status_text=status,
            map_size=(map_w, map_h),
            friendly_units=friendly_dots,
            enemy_units=enemy_dots,
            defense_anchor=(rally_point.x, rally_point.y) if rally_point else None,
            thors_count=len(thors),
            hellbats_count=len(hellbats),
            vikings_count=len(vikings),
            bcs_count=len(battlecruisers),
            idle_workers_count=self.idle_worker_count,
            matchup=self.strategy.matchup,
            scans_count=self.scan_count,
            scouted_tech=[s.name for s in self.seen_enemy_structures],
        )


    async def on_end(self, game_result: Result):
        """Called automatically by python-sc2 at match conclusion to trigger reinforcement learning updates."""
        try:
            from src.sc2_learning.fitness import extract_metrics_from_bot, calculate_fitness

            res_str = game_result.name.capitalize() if hasattr(game_result, "name") else str(game_result)
            metrics = extract_metrics_from_bot(self, game_result, self.time)
            fitness = calculate_fitness(metrics)
            self.last_metrics = metrics
            self.last_fitness = fitness

            self.unit_optimizer.update_after_match(
                enemy_race=self.actual_enemy_race,
                result=res_str,
                duration=self.time,
                units_built=self.units_produced_tracker,
                fitness_breakdown=fitness,
            )
            self.combat_policy.update_after_match(
                enemy_race=self.actual_enemy_race,
                result=res_str,
                duration=self.time,
                fitness_breakdown=fitness,
            )

            print(
                f"\n[RL 복합 피트니스 평가] 종합 스코어: {fitness.composite_score:+.1f}점 "
                f"(결과: {fitness.result_score:+.0f} | "
                f"교전가성비: {fitness.trade_score:+.1f}[비율 {fitness.trade_ratio:.2f}:1] | "
                f"피관리: {fitness.hp_preservation_score - fitness.critical_hp_penalty:+.1f}[빈사감점 -{fitness.critical_hp_penalty:.1f}, 구조회복 +{fitness.units_saved_from_critical * 2}] | "
                f"자원소모: {fitness.econ_score:+.1f}[소모율 {fitness.spending_ratio*100:.1f}%, 잉여감점 -{fitness.float_penalty:.1f}] | "
                f"전투마이크로: {fitness.micro_score:+.1f}[피해교환 {fitness.damage_ratio:.2f}:1])"
            )
            print(f"[RL 지능형 최적화] {self.actual_enemy_race}전 결과({res_str}) 기반 16종 조합 가중치 & 예술적 전투 마이크로 정책 강화학습 갱신 완료!\n")
        except Exception as e:
            print(f"[RL 가중치 최적화 경고] on_end 가중치 업데이트 오류: {e}")



