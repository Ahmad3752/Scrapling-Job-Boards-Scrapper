"""FastAPI entrypoint for the DevLens job-search pilot."""

import threading
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from api.devlens_jobs import router as devlens_jobs_router
from main import run_bulk_pipeline
from services.redis import get_redis_service


ROOT = Path(__file__).resolve().parent
STATIC_DIR = ROOT / "static"

app = FastAPI(title="DevLens Jobs Pilot", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(devlens_jobs_router)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _run_scraper_background(trigger_id: str) -> None:
    redis = get_redis_service()
    try:
        result = run_bulk_pipeline()
        redis.set_scraper_trigger_status(
            {
                "status": "success",
                "trigger_id": trigger_id,
                "finished_at": _utc_now(),
                "result": result,
            }
        )
    except Exception as exc:
        redis.set_scraper_trigger_status(
            {
                "status": "failed",
                "trigger_id": trigger_id,
                "finished_at": _utc_now(),
                "error": str(exc),
            }
        )
    finally:
        redis.release_scraper_trigger_lock(trigger_id)


def _start_scraper_thread(trigger_id: str) -> None:
    thread = threading.Thread(
        target=_run_scraper_background,
        args=(trigger_id,),
        daemon=True,
        name=f"scraper-trigger-{trigger_id[:8]}",
    )
    thread.start()


@app.get("/run-scraper", status_code=status.HTTP_202_ACCEPTED)
def run_scraper(response: Response):
    try:
        redis = get_redis_service()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Redis unavailable: {exc}") from exc

    active_trigger_id = redis.get_scraper_trigger_lock()
    if active_trigger_id:
        response.status_code = status.HTTP_200_OK
        current_status = redis.get_scraper_trigger_status()
        return {
            "status": "already_running",
            "trigger_id": active_trigger_id,
            "current": current_status,
        }

    trigger_id = str(uuid4())
    if not redis.acquire_scraper_trigger_lock(trigger_id):
        response.status_code = status.HTTP_200_OK
        current_status = redis.get_scraper_trigger_status()
        return {
            "status": "already_running",
            "trigger_id": redis.get_scraper_trigger_lock(),
            "current": current_status,
        }

    started_at = _utc_now()
    redis.set_scraper_trigger_status(
        {
            "status": "running",
            "trigger_id": trigger_id,
            "started_at": started_at,
        }
    )
    _start_scraper_thread(trigger_id)

    return {
        "status": "started",
        "trigger_id": trigger_id,
        "started_at": started_at,
    }


@app.get("/scraper-status")
def scraper_status():
    try:
        redis = get_redis_service()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Redis unavailable: {exc}") from exc

    payload = redis.get_scraper_trigger_status()
    active_trigger_id = redis.get_scraper_trigger_lock()
    if active_trigger_id and payload.get("status") != "running":
        payload = {
            **payload,
            "status": "running",
            "trigger_id": active_trigger_id,
        }
    return payload
