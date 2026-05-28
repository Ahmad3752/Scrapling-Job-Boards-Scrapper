"""
Bulk pipeline runner for all permitted roles:
Scraping -> Enrichment/Cleaning/Skill extraction -> Optional vetting -> DB upsert.

Run this to execute the end-to-end scout stack in one go.
"""

import sys
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.state import AgentState
from pipeline.enricher_node import job_enricher_node
from langchain_core.messages import HumanMessage
from core.settings import get_settings
from services.supabase import get_supabase_service
from services.redis import get_redis_service
from scraper.spider import JobScraperSpider


def _batched(items, batch_size):
    for i in range(0, len(items), batch_size):
        yield items[i:i + batch_size]


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


class _TotalsAccumulator:
    """Thread-safe counters for pipeline summary."""

    def __init__(self):
        self._lock = threading.Lock()
        self.scraped = 0
        self.enriched = 0
        self.db_upserts = 0
        self.failed_roles: list = []

    def add_scraped(self, n: int):
        with self._lock:
            self.scraped += n

    def add_enriched(self, n: int):
        with self._lock:
            self.enriched += n

    def add_db_upserts(self, n: int):
        with self._lock:
            self.db_upserts += n

    def add_failed_role(self, role: str):
        with self._lock:
            self.failed_roles.append(role)


def _process_single_role(role, index, total, settings, redis, supabase, totals, batch_size=200):
    """
    Process one role through the full pipeline.
    Each call creates its own spider instance for thread safety.
    Returns True on success, False on failure.
    """
    print(f"\n[{index}/{total}] Role: {role}")
    print("-" * 60)

    spider = JobScraperSpider()

    state: AgentState = {
        "messages": [HumanMessage(content=f"Find {role} jobs")],
        "user_id": "bulk_scraper_admin",
        "search_query": role,
        "raw_job_list": [],
        "scraping_status": "pending",
        "current_page": 1,
        "error": None,
        "retry_count": 0,
    }

    try:
        raw_jobs = spider.scrape_all_boards(
            query=role,
            location="Pakistan",
            boards=settings.job_scraping_boards,
            max_pages_per_board=settings.job_scraping_max_pages_per_board,
            max_jobs_per_board=settings.job_scraping_max_jobs_per_board,
        )
        totals.add_scraped(len(raw_jobs))
        print(f"   Raw jobs: {len(raw_jobs)}")

        new_jobs = []
        duplicate_count = 0
        for job in raw_jobs:
            if not redis.is_job_processed(job["job_id"]):
                new_jobs.append(job)
                redis.mark_job_processed(job["job_id"])
            else:
                duplicate_count += 1

        print(f"   New jobs: {len(new_jobs)}")
        print(f"   Duplicates filtered: {duplicate_count}")

        enrich_input = dict(state)
        enrich_input["raw_job_list"] = new_jobs
        enrich_input["scraping_status"] = "completed"
        enrich_result = job_enricher_node(enrich_input)
        enriched_jobs = enrich_result.get("raw_job_list", new_jobs)
        totals.add_enriched(len(enriched_jobs))
        print(f"   Enriched jobs: {len(enriched_jobs)}")

        if enriched_jobs:
            affected_for_role = 0
            for batch in _batched(enriched_jobs, batch_size):
                affected_for_role += int(supabase.bulk_insert_jobs(batch) or 0)
            totals.add_db_upserts(affected_for_role)
            print(f"   DB upserts (batched): {affected_for_role}")

        return True

    except Exception as exc:
        totals.add_failed_role(role)
        print(f"   Role failed: {exc}")
        return False


def run_bulk_pipeline():
    """Run scrape + enrichment for all permitted roles and upsert in batches."""
    settings = get_settings()
    roles = settings.permitted_roles
    batch_size = 200
    supabase = get_supabase_service()
    redis = get_redis_service()
    max_workers = settings.job_scraping_workers

    # Pre-load the enricher singleton before threads start (avoids lazy-init race)
    from pipeline.enricher import get_enricher
    get_enricher()

    supabase.delete_stale_jobs(days=settings.job_stale_after_days)

    print("\n" + "=" * 78)
    print(f"RUNNING BULK PIPELINE FOR {len(roles)} ROLES ({max_workers} worker(s))")
    print("=" * 78 + "\n")

    totals = _TotalsAccumulator()

    # Main pass
    if max_workers > 1:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(
                    _process_single_role,
                    role, idx, len(roles),
                    settings, redis, supabase, totals, batch_size,
                ): role
                for idx, role in enumerate(roles, 1)
            }
            for future in as_completed(futures):
                role = futures[future]
                try:
                    future.result()
                except Exception as exc:
                    print(f"   Unexpected worker error for '{role}': {exc}")
                    totals.add_failed_role(role)
    else:
        for idx, role in enumerate(roles, 1):
            _process_single_role(
                role, idx, len(roles),
                settings, redis, supabase, totals, batch_size,
            )

    # Retry pass (sequential — parallel retry would worsen anti-bot pressure)
    failed = totals.failed_roles[:]
    if failed:
        print("\n" + "=" * 78)
        print(f"RETRYING {len(failed)} FAILED ROLES (sequential)")
        print("=" * 78 + "\n")

        totals.failed_roles.clear()

        for idx, role in enumerate(failed, 1):
            _process_single_role(
                role, idx, len(failed),
                settings, redis, supabase, totals, batch_size,
            )

    # Summary
    print("\n" + "=" * 78)
    print("BULK PIPELINE SUMMARY")
    print(f"Roles processed: {len(roles)}")
    print(f"Roles failed (after retry): {len(totals.failed_roles)}")
    if totals.failed_roles:
        print(f"Failed roles: {', '.join(totals.failed_roles)}")
    print(f"Jobs scraped: {totals.scraped}")
    print(f"Jobs enriched: {totals.enriched}")
    print(f"DB upserts: {totals.db_upserts}")
    print("=" * 78 + "\n")

    return {
        "roles": len(roles),
        "scraped": totals.scraped,
        "enriched": totals.enriched,
        "vetted": 0,
        "db_upserts": totals.db_upserts,
        "failed_roles": len(totals.failed_roles),
    }


if __name__ == "__main__":
    with _suppress_scrapling_logs():
        run_bulk_pipeline()
