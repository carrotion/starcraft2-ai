"""Live Telemetry Broadcaster for StarCraft II Bot.
Exports in-game real-time tactical state (units, positions, resources, caster log) for the dashboard.
"""

import os
import json
import time
from typing import Dict, Any, List


TELEMETRY_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "learning_stats", "telemetry")
os.makedirs(TELEMETRY_DIR, exist_ok=True)


class LiveTelemetry:
    """Manages telemetry export for a single bot match."""

    def __init__(self, worker_id: int = 1):
        self.worker_id = worker_id
        self.telemetry_file = os.path.join(TELEMETRY_DIR, f"worker_{worker_id}.json")
        self.last_export = 0.0
        self.caster_logs: List[Dict[str, str]] = []

    def log_event(self, message: str, event_type: str = "info"):
        """Logs a tactical event for live caster display."""
        timestamp = time.strftime("%H:%M:%S")
        entry = {"time": timestamp, "text": message, "type": event_type}
        self.caster_logs.append(entry)
        if len(self.caster_logs) > 20:
            self.caster_logs.pop(0)

    def export(
        self,
        game_time: float,
        minerals: int,
        vespene: int,
        supply_used: int,
        supply_cap: int,
        workers_count: int,
        marines_count: int,
        marauders_count: int,
        tanks_mobile: int,
        tanks_sieged: int,
        medivacs_count: int,
        bunkers_count: int,
        turrets_count: int,
        cc_count: int,
        orbital_count: int,
        status_text: str,
        map_size: tuple[float, float],
        friendly_units: List[Dict[str, Any]],
        enemy_units: List[Dict[str, Any]],
        defense_anchor: tuple[float, float] | None = None,
        thors_count: int = 0,
        hellbats_count: int = 0,
        vikings_count: int = 0,
        bcs_count: int = 0,
        idle_workers_count: int = 0,
    ):
        """Dumps structured live game observation to disk for websocket streaming."""
        now = time.time()
        if now - self.last_export < 0.4:
            return  # Throttle to max 2.5 updates/sec to save CPU
        self.last_export = now

        mins, secs = divmod(int(game_time), 60)
        time_str = f"{mins:02d}:{secs:02d}"

        data = {
            "worker_id": self.worker_id,
            "timestamp": now,
            "game_time": game_time,
            "game_time_str": time_str,
            "resources": {
                "minerals": minerals,
                "vespene": vespene,
                "supply_used": supply_used,
                "supply_cap": supply_cap,
                "workers": workers_count,
                "idle_workers": idle_workers_count,
            },
            "army": {
                "workers": workers_count,
                "idle_workers": idle_workers_count,
                "marines": marines_count,
                "marauders": marauders_count,
                "tanks_mobile": tanks_mobile,
                "tanks_sieged": tanks_sieged,
                "tanks_total": tanks_mobile + tanks_sieged,
                "medivacs": medivacs_count,
                "thors": thors_count,
                "hellbats": hellbats_count,
                "vikings": vikings_count,
                "battlecruisers": bcs_count,
                "bunkers": bunkers_count,
                "turrets": turrets_count,
                "bases": cc_count,
                "orbitals": orbital_count,
            },
            "status": status_text,
            "map_size": {"width": map_size[0], "height": map_size[1]},
            "radar": {
                "friendly": friendly_units[:60],  # sample for bandwidth
                "enemy": enemy_units[:60],
                "anchor": {"x": defense_anchor[0], "y": defense_anchor[1]} if defense_anchor else None,
            },
            "caster_logs": self.caster_logs[-8:],
        }

        try:
            temp_file = self.telemetry_file + ".tmp"
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
            os.replace(temp_file, self.telemetry_file)
        except Exception:
            pass


def get_latest_telemetry(worker_id: int) -> Dict[str, Any] | None:
    path = os.path.join(TELEMETRY_DIR, f"worker_{worker_id}.json")
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if time.time() - data.get("timestamp", 0) > 6.0:
                    data["is_stale"] = True
                else:
                    data["is_stale"] = False
                return data
        except Exception:
            pass
    return None


def get_all_active_workers() -> List[int]:
    workers = []
    if os.path.exists(TELEMETRY_DIR):
        now = time.time()
        for fname in os.listdir(TELEMETRY_DIR):
            if fname.startswith("worker_") and fname.endswith(".json"):
                full_path = os.path.join(TELEMETRY_DIR, fname)
                try:
                    # If updated in last 5 seconds, consider active
                    if now - os.path.getmtime(full_path) < 5.0:
                        wid = int(fname.replace("worker_", "").replace(".json", ""))
                        workers.append(wid)
                except Exception:
                    pass
    return sorted(workers)
