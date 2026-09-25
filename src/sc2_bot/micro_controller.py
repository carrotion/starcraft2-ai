"""Combat Micro-Controller for StarCraft II Terran Army.

Features:
- Stutter-step / Kiting (무빙샷 및 카이팅) against melee units
- Focus Fire (체력 적은 적 우선 일제사격 점사)
- Stimpack usage (전투 돌입 시 스팀팩 자동 사용)
- Siege Tank positioning (전투 시 공성 모드, 진격 시 이동 모드 전환)
- Medivac healing & smart following (부상병 치료 및 보병 후방 지원)
"""

from typing import Any
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.ability_id import AbilityId
from sc2.ids.buff_id import BuffId
from sc2.position import Point2


class TerranMicroController:
    """Handles tactical movement and micro-management for Terran units."""

    def __init__(self, bot: Any):
        self.bot = bot

    def micro_bio(self, bio_units, enemies, target_position: Point2):
        """Micro for Marines and Marauders: Focus fire, kiting, stutter-step, and Stimpack."""
        if not bio_units:
            return

        base_pos = self.bot.start_location

        for unit in bio_units:
            nearby_enemies = enemies.closer_than(9.0, unit)

            if nearby_enemies:
                # 1. Stimpack: Activate if health is safe (> 25) and not already stimmed
                if unit.health > 25 and (
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

                # 3. Focus fire: Target enemy with lowest health in range
                enemies_in_range = nearby_enemies.closer_than(6.0, unit)
                if enemies_in_range:
                    lowest_hp_enemy = min(enemies_in_range, key=lambda e: e.health + e.shield)

                    # Kiting: If melee enemy is too close (< 3 range), step backward
                    if melee_enemies and melee_enemies.closest_to(unit).distance_to(unit) < 3.0:
                        retreat_pos = unit.position.towards(base_pos, 2.5)
                        unit.move(retreat_pos)
                    else:
                        unit.attack(lowest_hp_enemy)
                else:
                    closest = nearby_enemies.closest_to(unit)
                    unit.attack(closest)
            else:
                if unit.is_idle:
                    unit.attack(target_position)

    def micro_tanks(self, mobile_tanks, sieged_tanks, enemies, target_position: Point2, bio_center: Point2):
        """Micro for Siege Tanks during assault/skirmish: Smart Siege / Unsiege and push."""
        for tank in mobile_tanks:
            enemies_in_siege_range = enemies.closer_than(13.0, tank)
            if enemies_in_siege_range:
                tank(AbilityId.SIEGEMODE_SIEGEMODE)
            else:
                if tank.is_idle:
                    tank.attack(bio_center if bio_center else target_position)

        for tank in sieged_tanks:
            enemies_nearby = enemies.closer_than(14.0, tank)
            # Unsiege if no enemies in range and army has moved forward
            if not enemies_nearby and bio_center and tank.distance_to(bio_center) > 13.0:
                tank(AbilityId.UNSIEGE_UNSIEGE)

    def micro_defense_tanks(self, mobile_tanks, sieged_tanks, enemies, rally_position: Point2):
        """Anchor defense for Siege Tanks: Secure the choke point in Siege Mode."""
        for tank in mobile_tanks:
            enemies_in_range = enemies.closer_than(13.0, tank)
            if enemies_in_range or tank.distance_to(rally_position) < 8.0:
                # Siege down at the defense perimeter
                tank(AbilityId.SIEGEMODE_SIEGEMODE)
            else:
                tank.move(rally_position)

        for tank in sieged_tanks:
            # If accidentally sieged too far away from the active defense line, unsiege to reposition
            if tank.distance_to(rally_position) > 16.0 and not enemies.closer_than(14.0, tank):
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
        for thor in thors:
            nearby = enemies.closer_than(11.0, thor)
            if nearby:
                priority = nearby.filter(lambda e: e.is_flying or e.is_massive)
                if priority:
                    thor.attack(priority.closest_to(thor))
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
        """Micro for Vikings: Air superiority, kite ground units, snipe Colossi/Carriers/Mutas."""
        for viking in vikings:
            air_targets = enemies.filter(lambda e: (e.is_flying or e.type_id == UnitTypeId.COLOSSUS) and e.distance_to(viking) < 11.0)
            if air_targets:
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
        for bc in bcs:
            nearby = enemies.closer_than(11.0, bc)
            if nearby:
                available_abilities = getattr(bc, "abilities", set()) or set()
                if AbilityId.YAMATO_YAMATOGUN in available_abilities:
                    high_value = nearby.filter(lambda e: (e.health + e.shield) >= 200 and not e.is_structure)
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
        for reaper in reapers:
            nearby = enemies.closer_than(7.0, reaper)
            if nearby:
                available = getattr(reaper, "abilities", set()) or set()
                if AbilityId.KD8CHARGE_KD8CHARGE in available and reaper.distance_to(nearby.first) < 5.0:
                    reaper(AbilityId.KD8CHARGE_KD8CHARGE, nearby.first.position)
                elif nearby.closest_to(reaper).distance_to(reaper) < 3.5:
                    reaper.move(reaper.position.towards(self.bot.start_location, 2.5))
                else:
                    reaper.attack(nearby.closest_to(reaper))
            else:
                if reaper.is_idle:
                    reaper.attack(bio_center if bio_center else target_position)

    def micro_ghosts(self, ghosts, enemies, target_position: Point2, bio_center: Point2):
        """Micro for Ghosts: EMP shockwave against shields/energy, Snipe on high-HP biological."""
        for ghost in ghosts:
            nearby = enemies.closer_than(10.0, ghost)
            if nearby:
                available = getattr(ghost, "abilities", set()) or set()
                # 1. EMP on shields / energy clumps
                if AbilityId.EMP_EMP in available and ghost.energy >= 75:
                    emp_targets = nearby.filter(lambda e: getattr(e, "shield", 0) > 40 or getattr(e, "energy", 0) > 40)
                    if emp_targets:
                        ghost(AbilityId.EMP_EMP, emp_targets.first.position)
                        continue
                # 2. Snipe on massive biological (Ultralisk, Broodlord, etc.)
                if AbilityId.EFFECT_GHOSTSNIPE in available and ghost.energy >= 50:
                    bio_targets = nearby.filter(lambda e: getattr(e, "is_biological", False) and getattr(e, "is_massive", False))
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
