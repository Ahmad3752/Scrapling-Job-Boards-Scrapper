"""
Bulk scraper runner for DevLens:
role query variants -> board scraping -> Redis dedupe/stats -> enrichment -> Supabase.

Run locally first, then schedule on AWS. DevLens reads Supabase only.
"""

from __future__ import annotations

import hashlib
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.devlens_roles import queries_for_role, role_label_for_key
from core.settings import get_settings
from core.state import AgentState
from langchain_core.messages import HumanMessage
from pipeline.enricher_node import job_enricher_node
from scraper.spider import JobScraperSpider
from services.redis import get_redis_service
from services.supabase import get_supabase_service


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fallback_job_id(job: dict) -> str:
    raw = "|".join(
        str(job.get(key, "")).strip().lower()
        for key in ("title", "company", "location", "job_url")
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


@contextmanager
def _suppress_scrapling_logs():
    """Filter noisy Scrapling [INFO]/[ERROR] lines from stdout/stderr."""

    class _StreamFilter:
        def __init__(self, stream):
            self.stream = stream

        def write(self, data):
            if "] INFO:" in data or "] ERROR:" in data:
                return
            try:
                self.stream.write(data)
            except UnicodeEncodeError:
                self.stream.write(data.encode("ascii", errors="ignore").decode("ascii"))

        def flush(self):
            self.stream.flush()

    original_out = sys.stdout
    original_err = sys.stderr
    sys.stdout = _StreamFilter(original_out)
    sys.stderr = _StreamFilter(original_err)
    try:
        yield
    finally:
        sys.stdout = original_out
        sys.stderr = original_err


@dataclass
class _SliceCounters:
    scraped: int = 0
    inserted: int = 0
    updated: int = 0
    skipped: int = 0
    failed: int = 0
    enriched: int = 0

    @property
    def db_upserts(self) -> int:
        return self.inserted + self.updated

    def add(self, other: "_SliceCounters") -> None:
        self.scraped += other.scraped
        self.inserted += other.inserted
        self.updated += other.updated
        self.skipped += other.skipped
        self.failed += other.failed
        self.enriched += other.enriched


class _TotalsAccumulator:
    """Thread-safe counters for the pipeline summary."""

    def __init__(self):
        self._lock = threading.Lock()
        self.counters = _SliceCounters()
        self.failed_roles: list[str] = []

    def add_counters(self, counters: _SliceCounters):
        with self._lock:
            self.counters.add(counters)

    def add_failed_role(self, role_key: str):
        with self._lock:
            if role_key not in self.failed_roles:
                self.failed_roles.append(role_key)


def _enrich_jobs(role_label: str, jobs: list[dict]) -> list[dict]:
    if not jobs:
        return []

    state: AgentState = {
        "messages": [HumanMessage(content=f"Find {role_label} jobs")],
        "user_id": "bulk_scraper_admin",
        "search_query": role_label,
        "raw_job_list": jobs,
        "scraping_status": "completed",
        "current_page": 1,
        "error": None,
        "retry_count": 0,
    }
    result = job_enricher_node(state)
    return result.get("raw_job_list", jobs)


def _process_query_board(
    *,
    run_id: str,
    role_key: str,
    role_label: str,
    query: str,
    board: str,
    settings,
    redis,
    supabase,
) -> _SliceCounters:
    counters = _SliceCounters()
    started_at = _utc_now()
    status = "success"
    error_message = None
    spider = JobScraperSpider()

    print(f"\nRole={role_key} Board={board} Query='{query}'")
    print("-" * 72)

    try:
        raw_jobs = spider.scrape_all_boards(
            query=query,
            location="Pakistan",
            boards=[board],
            max_pages_per_board=settings.job_scraping_max_pages_per_board,
            max_jobs_per_board=settings.job_scraping_max_jobs_per_board,
        )
        counters.scraped = len(raw_jobs)
        if raw_jobs:
            redis.increment_scrape_stat(board, "scraped", len(raw_jobs))

        new_jobs: list[dict] = []
        for job in raw_jobs:
            job["role_key"] = role_key
            job["role_label"] = role_label
            job["role_query"] = query
            job["job_id"] = job.get("job_id") or _fallback_job_id(job)

            if redis.reserve_job(job["job_id"]):
                new_jobs.append(job)
            else:
                counters.skipped += 1
                redis.increment_scrape_stat(board, "skipped")

        print(f"   Raw jobs: {counters.scraped}")
        print(f"   New jobs: {len(new_jobs)}")
        print(f"   Redis duplicates skipped: {counters.skipped}")

        enriched_jobs = _enrich_jobs(role_label, new_jobs)
        counters.enriched = len(enriched_jobs)

        for job in enriched_jobs:
            job_id = job.get("job_id") or _fallback_job_id(job)
            try:
                result = supabase.upsert_scraper_job(job, role_key=role_key, role_query=query)
                if result == "inserted":
                    counters.inserted += 1
                    redis.increment_scrape_stat(board, "inserted")
                else:
                    counters.updated += 1
                    redis.increment_scrape_stat(board, "updated")
            except Exception as exc:
                counters.failed += 1
                redis.increment_scrape_stat(board, "failed")
                redis.release_job_reservation(job_id)
                print(f"   Supabase write failed for {job_id}: {exc}")

        if counters.failed:
            status = "partial_failed" if counters.db_upserts else "failed"

    except Exception as exc:
        counters.failed += 1
        redis.increment_scrape_stat(board, "failed")
        status = "failed"
        error_message = str(exc)
        print(f"   Slice failed: {exc}")

    finished_at = _utc_now()
    supabase.log_scrape_run(
        run_id=run_id,
        started_at=started_at,
        finished_at=finished_at,
        status=status,
        platform=board,
        role_key=role_key,
        role_label=role_label,
        query=query,
        location="Pakistan",
        scraped_count=counters.scraped,
        inserted_count=counters.inserted,
        updated_count=counters.updated,
        skipped_count=counters.skipped,
        failed_count=counters.failed,
        redis_stats_key=redis.stats_key(board),
        error_message=error_message,
        metadata={"country": "Pakistan"},
    )

    print(
        "   Slice summary: "
        f"scraped={counters.scraped}, inserted={counters.inserted}, "
        f"updated={counters.updated}, skipped={counters.skipped}, failed={counters.failed}"
    )
    return counters


def _process_single_role(role_key, index, total, run_id, settings, redis, supabase, totals):
    role_label = role_label_for_key(role_key)
    role_counters = _SliceCounters()

    print(f"\n[{index}/{total}] Role: {role_key} ({role_label})")
    print("=" * 78)

    for query in queries_for_role(role_key):
        for board in settings.job_scraping_boards:
            counters = _process_query_board(
                run_id=run_id,
                role_key=role_key,
                role_label=role_label,
                query=query,
                board=board,
                settings=settings,
                redis=redis,
                supabase=supabase,
            )
            role_counters.add(counters)

    totals.add_counters(role_counters)
    if role_counters.failed:
        totals.add_failed_role(role_key)
        return False
    return True


def run_bulk_pipeline():
    """Run scrape + enrichment for all canonical DevLens roles and upsert to Supabase."""
    settings = get_settings()
    role_keys = settings.scraper_role_keys
    run_id = str(uuid4())
    supabase = get_supabase_service()
    redis = get_redis_service()
    max_workers = settings.job_scraping_workers

    from pipeline.enricher import get_enricher

    get_enricher()
    supabase.mark_stale_jobs_inactive(days=settings.job_stale_after_days)

    print("\n" + "=" * 78)
    print(f"RUNNING DEVLENS SCRAPER CORPUS PIPELINE ({run_id})")
    print(f"Country: Pakistan")
    print(f"Roles: {', '.join(role_keys)}")
    print(f"Boards: {', '.join(settings.job_scraping_boards)}")
    print(f"Workers: {max_workers}")
    print("=" * 78 + "\n")

    totals = _TotalsAccumulator()

    if max_workers > 1:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(
                    _process_single_role,
                    role_key,
                    idx,
                    len(role_keys),
                    run_id,
                    settings,
                    redis,
                    supabase,
                    totals,
                ): role_key
                for idx, role_key in enumerate(role_keys, 1)
            }
            for future in as_completed(futures):
                role_key = futures[future]
                try:
                    future.result()
                except Exception as exc:
                    print(f"   Unexpected worker error for '{role_key}': {exc}")
                    totals.add_failed_role(role_key)
    else:
        for idx, role_key in enumerate(role_keys, 1):
            _process_single_role(role_key, idx, len(role_keys), run_id, settings, redis, supabase, totals)

    failed = totals.failed_roles[:]
    if failed:
        print("\n" + "=" * 78)
        print(f"RETRYING {len(failed)} FAILED ROLES (sequential)")
        print("=" * 78 + "\n")

        totals.failed_roles.clear()
        for idx, role_key in enumerate(failed, 1):
            _process_single_role(role_key, idx, len(failed), run_id, settings, redis, supabase, totals)

    counters = totals.counters
    print("\n" + "=" * 78)
    print("BULK PIPELINE SUMMARY")
    print(f"Run ID: {run_id}")
    print(f"Roles processed: {len(role_keys)}")
    print(f"Roles failed (after retry): {len(totals.failed_roles)}")
    if totals.failed_roles:
        print(f"Failed roles: {', '.join(totals.failed_roles)}")
    print(f"Jobs scraped: {counters.scraped}")
    print(f"Jobs enriched: {counters.enriched}")
    print(f"DB inserted: {counters.inserted}")
    print(f"DB updated: {counters.updated}")
    print(f"Redis skipped: {counters.skipped}")
    print(f"Failed writes/slices: {counters.failed}")
    print("=" * 78 + "\n")

    return {
        "run_id": run_id,
        "roles": len(role_keys),
        "scraped": counters.scraped,
        "enriched": counters.enriched,
        "inserted": counters.inserted,
        "updated": counters.updated,
        "skipped": counters.skipped,
        "failed": counters.failed,
        "failed_roles": len(totals.failed_roles),
    }


if __name__ == "__main__":
    with _suppress_scrapling_logs():
        run_bulk_pipeline()
