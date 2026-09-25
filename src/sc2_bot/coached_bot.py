"""StarCraft II Coached Bot with Crash-Proof Safety, Multi-Base Expansion, Upgrades, and Smart Micro."""

import time
import traceback
from typing import Optional, List
from sc2.bot_ai import BotAI
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.ability_id import AbilityId
from sc2.ids.upgrade_id import UpgradeId
from sc2.position import Point2

from src.sc2_bot.strategy_guide import StrategyConfig, CURRENT_STRATEGY
from src.sc2_bot.micro_controller import TerranMicroController
from src.sc2_learning.live_telemetry import LiveTelemetry


class CoachedTerranBot(BotAI):
    """Crash-proof Terran Bot capable of high-difficulty 1v2 with bunker defense, multi-base expansion, and full upgrades."""

    def __init__(self, strategy: Optional[StrategyConfig] = None, worker_id: int = 1):
        super().__init__()
        self.strategy = strategy or CURRENT_STRATEGY
        self.worker_id = worker_id
        self.micro = TerranMicroController(self)
        self.telemetry = LiveTelemetry(worker_id)
        self.last_log_time = 0.0
        self.prev_status = ""


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

        # 2. Worker distribution & SCV production across all bases
        await self.distribute_workers()
        workers = self.workers
        dynamic_worker_cap = min(self.strategy.max_workers, max(44, cc_list.amount * 22))
        if len(workers) < dynamic_worker_cap and self.can_afford(UnitTypeId.SCV):
            for cc in cc_list.idle:
                cc.train(UnitTypeId.SCV)

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

            # 2. MULE deployment: Only when energy reaches 100 (reserving 50 energy for emergency scans)
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

        # 9. Barracks Addons: 2 Tech Labs (Marauders/Upgrades) + 2 Reactors (Marine Spam)
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
                    if tech_lab_count < 2 and self.can_afford(UnitTypeId.BARRACKSTECHLAB):
                        rax.build(UnitTypeId.BARRACKSTECHLAB)
                        break
                    elif reactor_count < 2 and self.can_afford(UnitTypeId.BARRACKSREACTOR):
                        rax.build(UnitTypeId.BARRACKSREACTOR)
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


        # 12. Engineering Bay (공학연구소) & Missile Turrets (공중/은폐 방어)
        if self.strategy.build_engineering_bay:
            ebay_count = (
                self.structures(UnitTypeId.ENGINEERINGBAY).amount
                + self.already_pending(UnitTypeId.ENGINEERINGBAY)
            )
            if ebay_count < 1 and self.structures(UnitTypeId.BARRACKS).ready and self.can_afford(UnitTypeId.ENGINEERINGBAY):
                pos = await self.find_safe_main_placement(UnitTypeId.ENGINEERINGBAY)
                if pos:
                    worker = self.select_build_worker(pos)
                    if worker:
                        self.do(worker.build(UnitTypeId.ENGINEERINGBAY, pos), subtract_cost=True, ignore_warning=True)


            # Infantry Upgrades
            for ebay in self.structures(UnitTypeId.ENGINEERINGBAY).ready.idle:
                if self.strategy.research_weapons and self.can_afford(UpgradeId.TERRANINFANTRYWEAPONSLEVEL1):
                    ebay.research(UpgradeId.TERRANINFANTRYWEAPONSLEVEL1)
                elif self.strategy.research_armor and self.can_afford(UpgradeId.TERRANINFANTRYARMORSLEVEL1):
                    ebay.research(UpgradeId.TERRANINFANTRYARMORSLEVEL1)

            # Missile Turrets for Air & Cloaked unit defense
            if self.strategy.build_missile_turrets and self.structures(UnitTypeId.ENGINEERINGBAY).ready:
                turret_count = (
                    self.structures(UnitTypeId.MISSILETURRET).amount
                    + self.already_pending(UnitTypeId.MISSILETURRET)
                )
                if turret_count < 2 and self.can_afford(UnitTypeId.MISSILETURRET):
                    if turret_count == 0:
                        # 1st Turret: Main base mineral line
                        m_pos = main_base.position.towards(self.game_info.map_center, -4)
                        await self.build(UnitTypeId.MISSILETURRET, near=m_pos)
                    elif turret_count == 1 and other_ccs:
                        # 2nd Turret: Natural choke
                        nat_cc = other_ccs.first
                        nat_turret_pos = nat_cc.position.towards(self.game_info.map_center, 7)
                        await self.build(UnitTypeId.MISSILETURRET, near=nat_turret_pos)

        # 13. Barracks Tech Lab Research: Stimpack -> Combat Shield -> Concussive Shells
        for lab in self.structures(UnitTypeId.BARRACKSTECHLAB).ready.idle:
            if self.strategy.research_stimpack and self.can_afford(UpgradeId.STIMPACK):
                lab.research(UpgradeId.STIMPACK)
            elif self.strategy.research_combat_shield and self.can_afford(UpgradeId.SHIELDWALL):
                lab.research(UpgradeId.SHIELDWALL)
            elif self.strategy.research_concussive_shells and self.can_afford(UpgradeId.PUNISHERGRENADES):
                lab.research(UpgradeId.PUNISHERGRENADES)

        # 14. Unit Production
        for rax in self.structures(UnitTypeId.BARRACKS).ready.idle:
            if self.supply_left < 1:
                break

            addon_type = None
            if rax.add_on_tag:
                addon = self.structures.find_by_tag(rax.add_on_tag)
                if addon:
                    addon_type = addon.type_id

            if addon_type == UnitTypeId.BARRACKSTECHLAB:
                if self.strategy.train_marauders and self.can_afford(UnitTypeId.MARAUDER) and self.vespene >= 25:
                    rax.train(UnitTypeId.MARAUDER)
                elif self.strategy.train_marines and self.can_afford(UnitTypeId.MARINE):
                    rax.train(UnitTypeId.MARINE)
            else:
                # Reactor or Plain: Train Marines
                if self.strategy.train_marines and self.can_afford(UnitTypeId.MARINE):
                    rax.train(UnitTypeId.MARINE)

        # Tanks
        if self.strategy.train_siege_tanks:
            for factory in self.structures(UnitTypeId.FACTORY).ready.idle:
                if factory.has_add_on and self.can_afford(UnitTypeId.SIEGETANK) and self.supply_left >= 3:
                    factory.train(UnitTypeId.SIEGETANK)

        # Medivacs
        if self.strategy.train_medivacs:
            medivac_count = self.units(UnitTypeId.MEDIVAC).amount + self.already_pending(UnitTypeId.MEDIVAC)
            if medivac_count < 4:
                for starport in self.structures(UnitTypeId.STARPORT).ready.idle:
                    if self.can_afford(UnitTypeId.MEDIVAC) and self.supply_left >= 2:
                        starport.train(UnitTypeId.MEDIVAC)

        # 15. Combat, Defense Anchoring & Micro-Control
        marines = self.units(UnitTypeId.MARINE)
        marauders = self.units(UnitTypeId.MARAUDER)
        bio = marines | marauders

        mobile_tanks = self.units(UnitTypeId.SIEGETANK)
        sieged_tanks = self.units(UnitTypeId.SIEGETANKSIEGED)
        tanks = mobile_tanks | sieged_tanks
        medivacs = self.units(UnitTypeId.MEDIVAC)
        total_combat_army = len(bio) + len(tanks) + len(medivacs)

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
            # Defend base immediately
            def_target = enemies_near_base.closest_to(main_base).position
            self.micro.micro_bio(bio, enemy_units, def_target)
            self.micro.micro_tanks(mobile_tanks, sieged_tanks, enemy_units, def_target, bio_center)
            self.micro.micro_medivacs(medivacs, bio, bio_center)
        elif total_combat_army >= self.strategy.attack_army_threshold:
            # Full Assault with Siege Push!
            self.micro.micro_bio(bio, enemy_units, target_pos)
            self.micro.micro_tanks(mobile_tanks, sieged_tanks, enemy_units, target_pos, bio_center)
            self.micro.micro_medivacs(medivacs, bio, bio_center)
        else:
            # Defense Anchor Mode:
            # Bio holds rally point, Siege Tanks siege down at the perimeter to shred incoming attacks
            self.micro.micro_bio(bio, enemy_units, rally_point)
            self.micro.micro_defense_tanks(mobile_tanks, sieged_tanks, enemy_units, rally_point)
            self.micro.micro_medivacs(medivacs, bio, rally_point)

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
            print(
                f"[AI 브리핑] [{mins:02d}:{secs:02d}] "
                f"기지: {cc_list.amount}개(궤도:{orbital_count}) | 미네랄: {self.minerals} | 가스: {self.vespene} | "
                f"일꾼: {len(workers)}/{dynamic_worker_cap}(상한:{self.strategy.max_workers}) | "
                f"해병: {len(marines)} | 불곰: {len(marauders)} | 전차: {len(tanks)}(시즈:{len(sieged_tanks)}) | "
                f"의료선: {len(medivacs)} | 포탑: {turret_count} (군대: {total_combat_army}/{self.strategy.attack_army_threshold}) | {status}"
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
        )


