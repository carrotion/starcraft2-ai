"""Combat Micro-Controller for StarCraft II Terran Army.

Features:
- Stutter-step / Kiting (무빙샷 및 카이팅) against melee units
- Focus Fire (체력 적은 적 우선 일제사격 점사)
- Stimpack usage (전투 돌입 시 스팀팩 자동 사용)
- Siege Tank positioning (전투 시 공성 모드, 진격 시 이동 모드 전환)
- Medivac healing & smart following (부상병 치료 및 보병 후방 지원)
"""

import random
from typing import Any
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.ability_id import AbilityId
from sc2.ids.buff_id import BuffId
from sc2.position import Point2


class TerranMicroController:
    """Handles tactical movement and micro-management for Terran units."""

    def __init__(self, bot: Any):
        self.bot = bot

    def get_policy(self) -> dict:
        """Retrieves learned combat policy parameters from the bot."""
        if hasattr(self.bot, "combat_policy"):
            return self.bot.combat_policy.get_policy(getattr(self.bot, "actual_enemy_race", "DEFAULT"))
        return {
            "focus_fire_rate": 0.85,
            "kiting_distance": 3.2,
            "stim_health_threshold": 22.0,
            "retreat_hp_pct": 0.28,
            "yamato_min_hp": 180.0,
            "emp_energy_shield": 40.0,
            "tank_siege_range": 12.5,
            "snipe_hp_threshold": 120.0,
        }

    def micro_bio(self, bio_units, enemies, target_position: Point2):
        """Micro for Marines and Marauders: Pro-level Focus fire (1점사), kiting, low-HP retreat, and Stimpack."""
        if not bio_units:
            return

        base_pos = self.bot.start_location
        policy = self.get_policy()
        focus_rate = policy.get("focus_fire_rate", 0.85)
        kiting_dist = policy.get("kiting_distance", 3.2)
        stim_thresh = policy.get("stim_health_threshold", 22.0)
        retreat_pct = policy.get("retreat_hp_pct", 0.28)

        for unit in bio_units:
            nearby_enemies = enemies.closer_than(9.0, unit)

            if nearby_enemies:
                # 0. Low HP Tactical Retreat (프로게이머의 빈사 유닛 살리기 무빙)
                if (unit.health / unit.health_max) <= retreat_pct:
                    medivacs = getattr(self.bot, "units", None)
                    close_medivacs = medivacs(UnitTypeId.MEDIVAC).closer_than(12.0, unit) if medivacs else None
                    if close_medivacs:
                        retreat_pos = unit.position.towards(close_medivacs.closest_to(unit).position, 3.0)
                    else:
                        retreat_pos = unit.position.towards(base_pos, 3.0)
                    unit.move(retreat_pos)
                    continue

                # 1. Stimpack: Activate if health is above learned threshold and not already stimmed
                if unit.health >= stim_thresh and (
                    not unit.has_buff(BuffId.STIMPACK)
                    and not unit.has_buff(BuffId.STIMPACKMARAUDER)
                ):
                    if unit.type_id == UnitTypeId.MARINE:
                        unit(AbilityId.EFFECT_STIM_MARINE)
                    elif unit.type_id == UnitTypeId.MARAUDER:
                        unit(AbilityId.EFFECT_STIM_MARAUDER)

                # 2. Prioritize dangerous melee units
                melee_enemies = nearby_enemies.filter(
                    lambda e: e.type_id in {UnitTypeId.ZERGLING, UnitTypeId.ZEALOT, UnitTypeId.BANELING}
                    or (getattr(e, "can_attack_ground", False) and getattr(e, "ground_range", 10) <= 1.5)
                )

                # 3. Kiting: If melee enemy is closer than learned kiting_distance, step backward
                if melee_enemies and melee_enemies.closest_to(unit).distance_to(unit) < kiting_dist:
                    retreat_pos = unit.position.towards(base_pos, kiting_dist * 0.75)
                    unit.move(retreat_pos)
                    continue

                # 4. Focus fire (프로들의 칼 1점사): Target enemy with lowest health within range
                enemies_in_range = nearby_enemies.closer_than(6.0, unit)
                if enemies_in_range:
                    if random.random() < focus_rate:
                        lowest_hp_enemy = min(enemies_in_range, key=lambda e: e.health + e.shield)
                        unit.attack(lowest_hp_enemy)
                    else:
                        unit.attack(enemies_in_range.closest_to(unit))
                else:
                    closest = nearby_enemies.closest_to(unit)
                    unit.attack(closest)
            else:
                if unit.is_idle:
                    unit.attack(target_position)

    def micro_tanks(self, mobile_tanks, sieged_tanks, enemies, target_position: Point2, bio_center: Point2):
        """Micro for Siege Tanks: Smart Siege / Unsiege driven by learned tactical distance."""
        policy = self.get_policy()
        siege_range = policy.get("tank_siege_range", 12.5)

        for tank in mobile_tanks:
            enemies_in_siege_range = enemies.closer_than(siege_range, tank)
            if enemies_in_siege_range:
                tank(AbilityId.SIEGEMODE_SIEGEMODE)
            else:
                if tank.is_idle:
                    tank.attack(bio_center if bio_center else target_position)

        for tank in sieged_tanks:
            enemies_nearby = enemies.closer_than(siege_range + 1.5, tank)
            # Unsiege if no enemies in range and army has moved forward
            if not enemies_nearby and bio_center and tank.distance_to(bio_center) > 13.0:
                tank(AbilityId.UNSIEGE_UNSIEGE)

    def micro_defense_tanks(self, mobile_tanks, sieged_tanks, enemies, rally_position: Point2):
        """Anchor defense for Siege Tanks: Secure the choke point in Siege Mode."""
        policy = self.get_policy()
        siege_range = policy.get("tank_siege_range", 12.5)

        for tank in mobile_tanks:
            enemies_in_range = enemies.closer_than(siege_range, tank)
            if enemies_in_range or tank.distance_to(rally_position) < 8.0:
                tank(AbilityId.SIEGEMODE_SIEGEMODE)
            else:
                tank.move(rally_position)

        for tank in sieged_tanks:
            if tank.distance_to(rally_position) > 16.0 and not enemies.closer_than(siege_range + 1.5, tank):
                tank(AbilityId.UNSIEGE_UNSIEGE)

    def micro_medivacs(self, medivacs, bio_units, bio_center: Point2):
        """Micro for Medivacs: Heal wounded soldiers and stay safe behind frontline."""
        if not medivacs:
            return

        wounded_bio = [u for u in bio_units if u.health < u.health_max]

        for medivac in medivacs:
            if wounded_bio:
                critical_unit = min(wounded_bio, key=lambda u: u.health / u.health_max)
                medivac(AbilityId.MEDIVACHEAL_HEAL, critical_unit)
            elif bio_center:
                medivac.move(bio_center)
            else:
                medivac.move(self.bot.start_location)

    def micro_thors(self, thors, enemies, target_position: Point2, bio_center: Point2):
        """Micro for Thors: Prioritize enemy massive/air units and advance firmly with the deathball."""
        policy = self.get_policy()
        focus_rate = policy.get("focus_fire_rate", 0.85)

        for thor in thors:
            nearby = enemies.closer_than(11.0, thor)
            if nearby:
                priority = nearby.filter(lambda e: e.is_flying or e.is_massive)
                if priority:
                    target = min(priority, key=lambda e: e.health + e.shield) if random.random() < focus_rate else priority.closest_to(thor)
                    thor.attack(target)
                else:
                    thor.attack(nearby.closest_to(thor))
            else:
                if thor.is_idle:
                    thor.attack(bio_center if bio_center else target_position)

    def micro_hellbats(self, hellbats, enemies, target_position: Point2, bio_center: Point2):
        """Micro for Hellbats: Lead the frontline to incinerate light melee swarms."""
        for hellbat in hellbats:
            nearby = enemies.closer_than(8.0, hellbat)
            if nearby:
                light = nearby.filter(lambda e: e.is_light)
                if light:
                    hellbat.attack(light.closest_to(hellbat))
                else:
                    hellbat.attack(nearby.closest_to(hellbat))
            else:
                if hellbat.is_idle:
                    hellbat.attack(bio_center if bio_center else target_position)

    def micro_vikings(self, vikings, enemies, target_position: Point2, bio_center: Point2):
        """Micro for Vikings: Air superiority, kite ground units, focus-fire Colossi/Carriers/Mutas."""
        policy = self.get_policy()
        focus_rate = policy.get("focus_fire_rate", 0.85)

        for viking in vikings:
            air_targets = enemies.filter(lambda e: (e.is_flying or e.type_id == UnitTypeId.COLOSSUS) and e.distance_to(viking) < 11.0)
            if air_targets:
                if random.random() < focus_rate:
                    lowest = min(air_targets, key=lambda e: e.health + e.shield)
                    viking.attack(lowest)
                else:
                    viking.attack(air_targets.closest_to(viking))
            else:
                nearby_ground = enemies.closer_than(9.0, viking)
                if nearby_ground:
                    if nearby_ground.closest_to(viking).distance_to(viking) < 5.0 and bio_center:
                        viking.move(viking.position.towards(bio_center, 3.0))
                    else:
                        viking.attack(nearby_ground.closest_to(viking))
                else:
                    if viking.is_idle:
                        viking.attack(bio_center if bio_center else target_position)

    def micro_battlecruisers(self, bcs, enemies, target_position: Point2):
        """Micro for Battlecruisers: Yamato Cannon on high-value targets, relentless bombardment."""
        policy = self.get_policy()
        yamato_hp = policy.get("yamato_min_hp", 180.0)

        for bc in bcs:
            nearby = enemies.closer_than(11.0, bc)
            if nearby:
                available_abilities = getattr(bc, "abilities", set()) or set()
                if AbilityId.YAMATO_YAMATOGUN in available_abilities:
                    high_value = nearby.filter(lambda e: (e.health + e.shield) >= yamato_hp and not e.is_structure)
                    if high_value:
                        target = max(high_value, key=lambda e: e.health + e.shield)
                        bc(AbilityId.YAMATO_YAMATOGUN, target)
                        continue
                bc.attack(nearby.closest_to(bc))
            else:
                if bc.is_idle:
                    bc.attack(target_position)

    def micro_reapers(self, reapers, enemies, target_position: Point2, bio_center: Point2):
        """Micro for Reapers: KD8 grenade knockback & mobile hit-and-run kiting."""
        policy = self.get_policy()
        kiting_dist = policy.get("kiting_distance", 3.2)

        for reaper in reapers:
            nearby = enemies.closer_than(7.0, reaper)
            if nearby:
                available = getattr(reaper, "abilities", set()) or set()
                if AbilityId.KD8CHARGE_KD8CHARGE in available and reaper.distance_to(nearby.first) < 5.0:
                    reaper(AbilityId.KD8CHARGE_KD8CHARGE, nearby.first.position)
                elif nearby.closest_to(reaper).distance_to(reaper) < kiting_dist:
                    reaper.move(reaper.position.towards(self.bot.start_location, kiting_dist * 0.75))
                else:
                    reaper.attack(nearby.closest_to(reaper))
            else:
                if reaper.is_idle:
                    reaper.attack(bio_center if bio_center else target_position)

    def micro_ghosts(self, ghosts, enemies, target_position: Point2, bio_center: Point2):
        """Micro for Ghosts: EMP shockwave against shields/energy, Snipe on high-HP biological."""
        policy = self.get_policy()
        emp_thresh = policy.get("emp_energy_shield", 40.0)
        snipe_thresh = policy.get("snipe_hp_threshold", 120.0)

        for ghost in ghosts:
            nearby = enemies.closer_than(10.0, ghost)
            if nearby:
                available = getattr(ghost, "abilities", set()) or set()
                # 1. EMP on shields / energy clumps
                if AbilityId.EMP_EMP in available and ghost.energy >= 75:
                    emp_targets = nearby.filter(lambda e: getattr(e, "shield", 0) >= emp_thresh or getattr(e, "energy", 0) >= emp_thresh)
                    if emp_targets:
                        ghost(AbilityId.EMP_EMP, emp_targets.first.position)
                        continue
                # 2. Snipe on massive biological
                if AbilityId.EFFECT_GHOSTSNIPE in available and ghost.energy >= 50:
                    bio_targets = nearby.filter(lambda e: getattr(e, "is_biological", False) and (e.health + e.shield) >= snipe_thresh)
                    if bio_targets:
                        ghost(AbilityId.EFFECT_GHOSTSNIPE, bio_targets.first)
                        continue
                ghost.attack(nearby.closest_to(ghost))
            else:
                if ghost.is_idle:
                    ghost.attack(bio_center if bio_center else target_position)

    def micro_hellions(self, hellions, enemies, target_position: Point2, bio_center: Point2):
        """Micro for Hellions: High mobility kiting against light ground."""
        for h in hellions:
            nearby = enemies.closer_than(7.0, h)
            if nearby:
                if nearby.closest_to(h).distance_to(h) < 3.0:
                    h.move(h.position.towards(self.bot.start_location, 2.5))
                else:
                    h.attack(nearby.closest_to(h))
            else:
                if h.is_idle:
                    h.attack(bio_center if bio_center else target_position)

    def micro_widowmines(self, mines, enemies, target_position: Point2, bio_center: Point2):
        """Micro for Widow Mines: Burrow when enemies approach, unburrow to advance."""
        for mine in mines:
            nearby = enemies.closer_than(9.0, mine)
            if nearby:
                if mine.type_id == UnitTypeId.WIDOWMINE:
                    mine(AbilityId.BURROWDOWN_WIDOWMINE)
            else:
                if mine.type_id == UnitTypeId.WIDOWMINEBURROWED and bio_center and mine.distance_to(bio_center) > 15.0:
                    mine(AbilityId.BURROWUP_WIDOWMINE)
                elif mine.type_id == UnitTypeId.WIDOWMINE and mine.is_idle:
                    mine.move(bio_center if bio_center else target_position)

    def micro_cyclones(self, cyclones, enemies, target_position: Point2, bio_center: Point2):
        """Micro for Cyclones: Lock-on mobile firing and kiting."""
        for cyc in cyclones:
            nearby = enemies.closer_than(9.0, cyc)
            if nearby:
                available = getattr(cyc, "abilities", set()) or set()
                if AbilityId.LOCKON_LOCKON in available:
                    cyc(AbilityId.LOCKON_LOCKON, nearby.closest_to(cyc))
                elif nearby.closest_to(cyc).distance_to(cyc) < 4.0:
                    cyc.move(cyc.position.towards(self.bot.start_location, 2.5))
                else:
                    cyc.attack(nearby.closest_to(cyc))
            else:
                if cyc.is_idle:
                    cyc.attack(bio_center if bio_center else target_position)

    def micro_liberators(self, libs, enemies, target_position: Point2, bio_center: Point2):
        """Micro for Liberators: Defender mode zone denial over enemy concentrations."""
        for lib in libs:
            nearby = enemies.closer_than(11.0, lib)
            if nearby:
                available = getattr(lib, "abilities", set()) or set()
                if AbilityId.LIBERATORMORPHTOAG_LIBERATORAGMODE in available and lib.type_id == UnitTypeId.LIBERATOR:
                    lib(AbilityId.LIBERATORMORPHTOAG_LIBERATORAGMODE, nearby.first.position)
            else:
                if lib.type_id == UnitTypeId.LIBERATORAG and bio_center and lib.distance_to(bio_center) > 14.0:
                    lib(AbilityId.LIBERATORMORPHTOAA_LIBERATORAAMODE)
                elif lib.type_id == UnitTypeId.LIBERATOR and lib.is_idle:
                    lib.attack(bio_center if bio_center else target_position)

    def micro_ravens(self, ravens, enemies, target_position: Point2, bio_center: Point2):
        """Micro for Ravens: Interference Matrix on heavy threats, Anti-Armor missile, safe escort."""
        for raven in ravens:
            nearby = enemies.closer_than(10.0, raven)
            if nearby and raven.energy >= 75:
                available = getattr(raven, "abilities", set()) or set()
                # Matrix on massive mechanical / Colossi / Siege Tanks
                if AbilityId.EFFECT_INTERFERENCEMATRIX in available:
                    priority = nearby.filter(lambda e: getattr(e, "is_mechanical", False) and (getattr(e, "is_massive", False) or e.type_id in {UnitTypeId.SIEGETANK, UnitTypeId.THOR, UnitTypeId.COLOSSUS}))
                    if priority:
                        raven(AbilityId.EFFECT_INTERFERENCEMATRIX, priority.first)
                        continue
                if AbilityId.EFFECT_ANTIARMORMISSILE in available:
                    raven(AbilityId.EFFECT_ANTIARMORMISSILE, nearby.first)
                    continue
            if bio_center:
                raven.move(bio_center)
            else:
                raven.move(self.bot.start_location)

    def micro_banshees(self, banshees, enemies, target_position: Point2, bio_center: Point2):
        """Micro for Banshees: Cloak when threatened, ground strafing."""
        for banshee in banshees:
            nearby = enemies.closer_than(9.0, banshee)
            if nearby:
                if banshee.health < banshee.health_max * 0.9:
                    available = getattr(banshee, "abilities", set()) or set()
                    if AbilityId.BEHAVIOR_CLOAKON_BANSHEE in available and banshee.energy >= 25:
                        banshee(AbilityId.BEHAVIOR_CLOAKON_BANSHEE)
                banshee.attack(nearby.closest_to(banshee))
            else:
                if banshee.is_idle:
                    banshee.attack(bio_center if bio_center else target_position)
