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
