"""FastAPI Web Dashboard Server for StarCraft II Autonomous AI."""

import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import uvicorn
import subprocess
import time
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from pydantic import BaseModel

os.environ["SC2PATH"] = os.environ.get("SC2PATH", r"C:\Games\StarCraft II")

from src.sc2_learning.evaluator import AutonomousEvaluator
from src.sc2_learning.live_telemetry import get_latest_telemetry, get_all_active_workers
from src.sc2_learning.process_manager import TRAIN_MANAGER

REPLAYS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "replays"))
os.makedirs(REPLAYS_DIR, exist_ok=True)


app = FastAPI(title="SC2 AI CommandCenter Dashboard")
evaluator = AutonomousEvaluator()

TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), "templates", "index.html")


class StartTrainingRequest(BaseModel):
    workers: int = 5
    games: int = 100
    difficulty: str = "veryhard"
    enemy: str = "zerg"
    mode: str = "1v1"
    realtime: bool = False
    map_name: str = "random"


@app.get("/", response_class=HTMLResponse)
async def serve_dashboard():
    """Serves the main single-page web dashboard."""
    if os.path.exists(TEMPLATE_PATH):
        with open(TEMPLATE_PATH, "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>Dashboard template not found!</h1>"


@app.get("/api/stats")
async def get_stats():
    """Returns aggregated stats and recent match records for charts."""
    summary = evaluator.get_summary()
    history = evaluator._load_history()

    # Calculate rolling win rate for Chart.js
    rolling_rates = []
    wins = 0
    for i, match in enumerate(history, 1):
        if match.get("result") == "Victory":
            wins += 1
        rolling_rates.append(round((wins / i) * 100, 1))

    summary["history_rates"] = rolling_rates[-30:]  # last 30 games for chart
    summary["recent_history"] = history[-20:]  # last 20 games for table
    return summary


@app.get("/api/status")
async def get_status():
    """Returns whether the training subprocess is actively running."""
    return TRAIN_MANAGER.get_status()


@app.post("/api/start")
async def start_training(req: StartTrainingRequest):
    """Starts background training subprocess with given configuration."""
    res = TRAIN_MANAGER.start_training(
        workers=req.workers,
        games=req.games,
        difficulty=req.difficulty,
        enemy=req.enemy,
        mode=req.mode,
        realtime=req.realtime,
        map_name=req.map_name,
    )
    return res


@app.post("/api/stop")
async def stop_training():
    """Stops the active training subprocess."""
    return TRAIN_MANAGER.stop_training()


@app.get("/api/telemetry/{worker_id}")
async def get_worker_telemetry(worker_id: int):
    """Returns the latest live tactical telemetry for a specific worker."""
    data = get_latest_telemetry(worker_id)
    if data:
        return data
    return {"worker_id": worker_id, "status": "No active match", "resources": None}


@app.get("/api/workers")
async def list_active_workers():
    """Lists IDs of all currently active workers."""
    return {"active_workers": get_all_active_workers()}


@app.get("/api/replays")
async def list_replays():
    """Lists all available .SC2Replay files with file details."""
    if not os.path.exists(REPLAYS_DIR):
        return {"replays": []}
    files = []
    for f in os.listdir(REPLAYS_DIR):
        if f.endswith(".SC2Replay"):
            fp = os.path.join(REPLAYS_DIR, f)
            stat = os.stat(fp)
            files.append({
                "filename": f,
                "size_kb": round(stat.st_size / 1024, 1),
                "modified": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(stat.st_mtime))
            })
    files.sort(key=lambda x: x["modified"], reverse=True)
    return {"replays": files}


@app.get("/api/replays/download/{filename}")
async def download_replay(filename: str):
    """Downloads a specific .SC2Replay file."""
    # Sanitize filename
    clean_filename = os.path.basename(filename)
    fp = os.path.join(REPLAYS_DIR, clean_filename)
    if not os.path.exists(fp) or not clean_filename.endswith(".SC2Replay"):
        return JSONResponse({"status": "error", "message": "Replay file not found"}, status_code=404)
    return FileResponse(fp, filename=clean_filename, media_type="application/octet-stream")


@app.post("/api/replays/play/{filename}")
async def play_replay(filename: str):
    """Directly launches the SC2 client in replay spectator mode."""
    clean_filename = os.path.basename(filename)
    fp = os.path.abspath(os.path.join(REPLAYS_DIR, clean_filename))
    if not os.path.exists(fp):
        return {"status": "error", "message": f"리플레이 파일을 찾을 수 없습니다: {clean_filename}"}

    try:
        sc2_root = os.environ.get("SC2PATH", r"C:\Games\StarCraft II")
        switcher_64 = os.path.join(sc2_root, "Support64", "SC2Switcher_x64.exe")
        switcher_32 = os.path.join(sc2_root, "Support", "SC2Switcher.exe")
        if os.path.exists(switcher_64):
            subprocess.Popen([switcher_64, fp])
        elif os.path.exists(switcher_32):
            subprocess.Popen([switcher_32, fp])
        else:
            os.startfile(fp)
        return {"status": "success", "message": f"스타크래프트 II에서 리플레이 [{clean_filename}] 재생을 시작했습니다!"}
    except Exception as e:
        return {"status": "error", "message": f"리플레이 재생 실패: {str(e)}"}


@app.post("/api/replays/open_folder")
async def open_replays_folder():
    """Opens the replays directory in Windows File Explorer."""
    try:
        os.makedirs(REPLAYS_DIR, exist_ok=True)
        subprocess.Popen(f'explorer "{REPLAYS_DIR}"')
        return {"status": "success", "message": "리플레이 폴더가 열렸습니다."}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def main():
    print("=" * 70)
    print("  🖥️ StarCraft II AI - 웹 대시보드 서버 가동")
    print("=" * 70)
    print("  - 대시보드 주소: http://127.0.0.1:8000")
    print("  - 브라우저(Chrome/Edge)에서 위 주소로 접속하시면")
    print("    [실시간 통계 + 2D 레이더 중계 + 웹 원클릭 학습 제어]를 이용하실 수 있습니다.")
    print("=" * 70)
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")


if __name__ == "__main__":
    main()
