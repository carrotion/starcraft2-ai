"""Background Training Process Manager for SC2 Web Dashboard."""

import os
import sys
import subprocess
import time
from typing import Dict, Any, Optional


VENV_PYTHON = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".venv", "Scripts", "python.exe")
TRAIN_SCRIPT = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "train_sc2.py")
TRAIN_LOG_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "learning_stats", "training.log")


class TrainingProcessManager:
    """Manages the background execution of train_sc2.py triggered via the Web Dashboard."""

    def __init__(self):
        self.process: Optional[subprocess.Popen] = None
        self.log_file = None
        self.start_time: float = 0.0
        self.config: Dict[str, Any] = {}

    def is_running(self) -> bool:
        if self.process is not None:
            poll = self.process.poll()
            if poll is None:
                return True
            else:
                self.process = None
                if self.log_file:
                    try:
                        self.log_file.close()
                    except Exception:
                        pass
                    self.log_file = None
        return False

    def start_training(
        self,
        workers: int = 5,
        games: int = 100,
        difficulty: str = "veryhard",
        enemy: str = "zerg",
        mode: str = "1v1",
        realtime: bool = False,
        map_name: str = "random",
    ) -> Dict[str, Any]:
        """Launches train_sc2.py in the background."""
        if self.is_running():
            return {"status": "error", "message": "Training is already running!"}

        cmd = [
            VENV_PYTHON,
            TRAIN_SCRIPT,
            "--workers", str(workers),
            "--games", str(games),
            "--difficulty", difficulty,
            "--enemy", enemy,
            "--mode", mode,
            "--map", map_name,
        ]
        if realtime:
            cmd.append("--realtime")

        os.makedirs(os.path.dirname(TRAIN_LOG_FILE), exist_ok=True)
        self.log_file = open(TRAIN_LOG_FILE, "a", encoding="utf-8", buffering=1)
        self.log_file.write(f"\n--- [훈련 세션 시작: {time.strftime('%Y-%m-%d %H:%M:%S')}] ---\n")

        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        sc2_p = os.environ.get("SC2PATH")
        if not sc2_p or not os.path.exists(sc2_p):
            for cand in [r"F:\Game\StarCraft II", r"C:\Games\StarCraft II", r"D:\Games\StarCraft II"]:
                if os.path.exists(cand):
                    sc2_p = cand
                    break
        env["SC2PATH"] = sc2_p or r"F:\Game\StarCraft II"

        # Start non-blocking process with log redirect
        self.process = subprocess.Popen(
            cmd,
            cwd=os.path.dirname(TRAIN_SCRIPT),
            stdout=self.log_file,
            stderr=subprocess.STDOUT,
            env=env,
        )
        self.start_time = time.time()
        self.config = {
            "workers": workers,
            "games": games,
            "difficulty": difficulty,
            "enemy": enemy,
            "mode": mode,
            "realtime": realtime,
            "map": map_name,
            "pid": self.process.pid,
        }

        return {"status": "success", "message": f"Started training with {workers} workers!", "config": self.config}

    def stop_training(self) -> Dict[str, Any]:
        """Stops the running training process and cleans up SC2 child processes."""
        if not self.is_running():
            return {"status": "info", "message": "Training is not currently running."}

        try:
            if self.process:
                pid = self.process.pid
                subprocess.run(f"taskkill /f /t /pid {pid} >nul 2>&1", shell=True, timeout=5)
                self.process.terminate()
                self.process.wait(timeout=2)
        except Exception:
            try:
                if self.process:
                    self.process.kill()
            except Exception:
                pass
        finally:
            self.process = None
            if self.log_file:
                try:
                    self.log_file.close()
                except Exception:
                    pass
                self.log_file = None

        # Clean any lingering SC2 instances
        try:
            subprocess.run("taskkill /f /im SC2_x64.exe /im BlizzardError.exe >nul 2>&1", shell=True, timeout=5)
        except Exception:
            pass

        return {"status": "success", "message": "Training stopped and SC2 processes cleaned."}

    def get_status(self) -> Dict[str, Any]:
        running = self.is_running()
        elapsed = time.time() - self.start_time if running else 0.0
        last_log = ""
        if os.path.exists(TRAIN_LOG_FILE):
            try:
                with open(TRAIN_LOG_FILE, "r", encoding="utf-8", errors="replace") as f:
                    lines = [ln.strip() for ln in f if ln.strip()]
                    if lines:
                        last_log = lines[-1]
            except Exception:
                pass

        return {
            "is_running": running,
            "elapsed_sec": round(elapsed, 1),
            "config": self.config if running else {},
            "last_log": last_log,
        }


# Singleton manager instance
TRAIN_MANAGER = TrainingProcessManager()
