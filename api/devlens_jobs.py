"""Local-cache job search API for the DevLens scraper pilot."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query

from scraper.spider import JobScraperSpider


OpportunityType = Literal["all", "jobs", "internships"]

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = PROJECT_ROOT / "data" / "job_cache"
DEFAULT_BOARDS = ["linkedin", "indeed", "rozee", "mustakbil"]

DEVELOPER_ROLES: dict[str, str] = {
    "backend": "Backend Developer",
    "frontend": "Frontend Developer",
    "full_stack": "Full Stack Developer",
    "mobile": "Mobile Developer",
    "ai_ml": "AI/ML Engineer",
    "devops": "DevOps Engineer",
    "data_engineer": "Data Engineer",
    "qa_automation": "QA Automation Engineer",
}

ROLE_QUERIES: dict[str, list[str]] = {
    "backend": ["Backend Developer", "Backend Engineer", "Backend Developer Intern"],
    "frontend": ["Frontend Developer", "Frontend Engineer", "Frontend Developer Intern"],
    "full_stack": ["Full Stack Developer", "Full-Stack Developer", "MERN Stack Developer"],
    "mobile": ["Mobile Developer", "Mobile App Developer", "Android Developer", "iOS Developer"],
    "ai_ml": ["AI Engineer", "Machine Learning Engineer", "AI/ML Engineer", "AI Intern"],
    "devops": ["DevOps Engineer", "Cloud Engineer", "DevOps Intern"],
    "data_engineer": ["Data Engineer", "ETL Developer", "Data Engineer Intern"],
    "qa_automation": ["QA Automation Engineer", "SQA Engineer", "Automation Tester"],
}


router = APIRouter(prefix="/api")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _validate_role(role: str) -> None:
    if role not in DEVELOPER_ROLES:
        raise HTTPException(status_code=400, detail=f"Unsupported role '{role}'")


def _validate_type(opportunity_type: str) -> None:
    if opportunity_type not in {"all", "jobs", "internships"}:
        raise HTTPException(status_code=400, detail=f"Unsupported type '{opportunity_type}'")


def _cache_path(role: str, cache_dir: Path | None = None) -> Path:
    return (cache_dir or CACHE_DIR) / f"{role}.json"


def _compact_text(value: Any, limit: int | None = None) -> str:
    text = " ".join(str(value or "").split()).strip()
    if limit and len(text) > limit:
        return text[: limit - 3].rstrip() + "..."
    return text


def _is_internship(job: dict[str, Any]) -> bool:
    haystack = " ".join(
        str(job.get(key, ""))
        for key in ("title", "description", "employment_type", "job_type")
    ).lower()
    return any(signal in haystack for signal in ("intern", "internship", "trainee"))


def filter_jobs(jobs: list[dict[str, Any]], opportunity_type: OpportunityType) -> list[dict[str, Any]]:
    if opportunity_type == "all":
        return jobs
    if opportunity_type == "internships":
        return [job for job in jobs if _is_internship(job)]
    return [job for job in jobs if not _is_internship(job)]


def _normalize_skills(job: dict[str, Any]) -> list[str]:
    skills = job.get("skills") or []
    if isinstance(skills, dict):
        flattened: list[str] = []
        for values in skills.values():
            if isinstance(values, list):
                flattened.extend(str(item) for item in values if item)
        skills = flattened
    if not isinstance(skills, list):
        return []
    return list(dict.fromkeys(_compact_text(skill) for skill in skills if _compact_text(skill)))


def normalize_job(job: dict[str, Any]) -> dict[str, Any]:
    job_type = job.get("employment_type") or job.get("job_type") or ""
    description = _compact_text(job.get("description"), 420)
    normalized = {
        "job_id": _compact_text(job.get("job_id")),
        "title": _compact_text(job.get("title")) or "Untitled role",
        "company": _compact_text(job.get("company")) or "Unknown company",
        "location": _compact_text(job.get("location")) or "Pakistan",
        "board": _compact_text(job.get("board") or job.get("job_source")).lower(),
        "job_url": _compact_text(job.get("job_url") or job.get("url")),
        "description": description,
        "skills": _normalize_skills(job),
        "employment_type": _compact_text(job_type) or "Not specified",
        "experience_required": job.get("experience_required"),
        "education_required": job.get("education_required"),
        "salary": job.get("salary"),
        "posted_date": job.get("posted_date"),
    }
    if not normalized["job_id"]:
        normalized["job_id"] = _dedupe_key(normalized)
    normalized["is_internship"] = _is_internship(normalized)
    return normalized


def _dedupe_key(job: dict[str, Any]) -> str:
    return "|".join(
        _compact_text(job.get(key)).lower()
        for key in ("job_id", "job_url", "title", "company", "location")
        if _compact_text(job.get(key))
    )


def dedupe_jobs(jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for job in jobs:
        normalized = normalize_job(job)
        key = _dedupe_key(normalized)
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(normalized)
    return unique


def _load_cached_payload(role: str, cache_dir: Path | None = None) -> dict[str, Any] | None:
    path = _cache_path(role, cache_dir)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _write_cached_payload(payload: dict[str, Any], cache_dir: Path | None = None) -> None:
    path = _cache_path(payload["role_key"], cache_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def build_response_from_cache(
    role: str,
    opportunity_type: OpportunityType = "all",
    cache_dir: Path | None = None,
) -> dict[str, Any]:
    _validate_role(role)
    _validate_type(opportunity_type)

    payload = _load_cached_payload(role, cache_dir)
    if not payload:
        return {
            "cache_status": "missing",
            "role_key": role,
            "role_label": DEVELOPER_ROLES[role],
            "type": opportunity_type,
            "jobs": [],
            "count": 0,
            "total_cached": 0,
            "message": "No cached jobs yet. Refresh this role to scrape jobs.",
        }

    jobs = filter_jobs(payload.get("jobs", []), opportunity_type)
    return {
        **payload,
        "cache_status": "hit",
        "type": opportunity_type,
        "jobs": jobs,
        "count": len(jobs),
        "total_cached": len(payload.get("jobs", [])),
    }


def _enrich_jobs(jobs: list[dict[str, Any]], errors: list[dict[str, str]]) -> list[dict[str, Any]]:
    if not jobs:
        return []
    try:
        from pipeline.enricher import get_enricher

        return get_enricher().enrich_batch(jobs)
    except Exception as exc:
        errors.append({"stage": "enrichment", "error": str(exc)})
        return jobs


def refresh_role_cache(
    role: str,
    opportunity_type: OpportunityType = "all",
    cache_dir: Path | None = None,
    boards: list[str] | None = None,
    max_pages_per_board: int | None = None,
    max_jobs_per_board: int | None = None,
) -> dict[str, Any]:
    _validate_role(role)
    _validate_type(opportunity_type)

    selected_boards = boards or DEFAULT_BOARDS
    pages = max_pages_per_board or _get_int_env("DEVLENS_JOB_MAX_PAGES_PER_BOARD", 1)
    jobs_per_board = max_jobs_per_board or _get_int_env("DEVLENS_JOB_MAX_JOBS_PER_BOARD", 10)
    spider = JobScraperSpider()
    raw_jobs: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    queries = ROLE_QUERIES.get(role, [DEVELOPER_ROLES[role]])

    for query in queries:
        for board in selected_boards:
            try:
                raw_jobs.extend(
                    spider.scrape_all_boards(
                        query=query,
                        location="Pakistan",
                        boards=[board],
                        max_pages_per_board=pages,
                        max_jobs_per_board=jobs_per_board,
                    )
                )
            except Exception as exc:
                errors.append({"board": board, "query": query, "error": str(exc)})

    enriched_jobs = _enrich_jobs(raw_jobs, errors)
    jobs = dedupe_jobs(enriched_jobs)
    payload = {
        "role_key": role,
        "role_label": DEVELOPER_ROLES[role],
        "queries": queries,
        "boards": selected_boards,
        "fetched_at": _utc_now(),
        "jobs": jobs,
        "errors": errors,
    }
    _write_cached_payload(payload, cache_dir)
    return build_response_from_cache(role, opportunity_type, cache_dir)


@router.get("/roles")
def get_roles() -> dict[str, Any]:
    return {
        "roles": [
            {"key": key, "label": label}
            for key, label in DEVELOPER_ROLES.items()
        ]
    }


@router.get("/jobs")
def get_jobs(
    role: str = Query(...),
    type: OpportunityType = Query("all"),  # noqa: A002 - public API name
) -> dict[str, Any]:
    return build_response_from_cache(role, type)


@router.post("/jobs/refresh")
def refresh_jobs(
    role: str = Query(...),
    type: OpportunityType = Query("all"),  # noqa: A002 - public API name
) -> dict[str, Any]:
    return refresh_role_cache(role, type)
