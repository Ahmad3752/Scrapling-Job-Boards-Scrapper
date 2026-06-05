"""
Redis service for job queue management with deduplication.

Handles job enqueueing, dequeueing, and tracking processed jobs to prevent duplicates.
"""

import json
import hashlib
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from typing import Dict, List, Optional
from redis import Redis
from redis.exceptions import RedisError, ConnectionError
from core.settings import get_settings


class RedisService:
    """Redis-based job queue with deduplication support."""
    
    def __init__(self):
        """Initialize Redis connection."""
        self.settings = get_settings()
        self.client: Optional[Redis] = None
        self._connect()
    
    def _connect(self) -> None:
        """Establish Redis connection with retry logic."""
        for attempt in range(self.settings.redis_max_retries):
            try:
                self.client = Redis.from_url(
                    self.settings.redis_url,
                    decode_responses=True,
                    socket_connect_timeout=5,
                    socket_keepalive=True
                )
                # Test connection
                self.client.ping()
                print(f"Redis connected: {self.settings.redis_url}")
                return
            except (RedisError, ConnectionError) as e:
                if attempt == self.settings.redis_max_retries - 1:
                    print(f"Redis connection failed after {self.settings.redis_max_retries} attempts: {e}")
                    raise
                print(f"Redis connection attempt {attempt + 1} failed, retrying...")
    
    def _get_queue_key(self) -> str:
        """Get Redis key for job queue."""
        return f"{self.settings.redis_job_queue_prefix}:queue"
    
    def _get_processed_key(self) -> str:
        """Get Redis key for processed jobs set."""
        return f"{self.settings.redis_job_queue_prefix}:processed"

    def seen_job_key(self, job_id: str) -> str:
        return f"scraper:seen:job:{job_id}"

    def stats_key(self, platform: str) -> str:
        platform_slug = (platform or "unknown").strip().lower()
        return f"scraper:stats:{platform_slug}:today"

    def scraper_trigger_lock_key(self) -> str:
        return "scraper:trigger:lock"

    def scraper_trigger_status_key(self) -> str:
        return "scraper:trigger:status"

    def _pakistan_today(self) -> str:
        return datetime.now(ZoneInfo("Asia/Karachi")).date().isoformat()

    def _ensure_stats_date(self, key: str) -> None:
        today = self._pakistan_today()
        current = self.client.hget(key, "date")
        if current and current != today:
            self.client.delete(key)
        self.client.hset(key, "date", today)
        self.client.expire(key, self.settings.scraper_stats_ttl)
    
    def _generate_job_id(self, job_data: Dict) -> str:
        """
        Generate unique job ID from job data.
        
        Args:
            job_data: Job dictionary with title, company, location
            
        Returns:
            SHA256 hash (16 chars)
        """
        # Create deterministic string from key fields
        id_string = f"{job_data.get('title', '')}|{job_data.get('company', '')}|{job_data.get('location', '')}"
        return hashlib.sha256(id_string.encode()).hexdigest()[:16]
    
    def is_job_processed(self, job_id: str) -> bool:
        """
        Check if job has already been processed.
        
        Args:
            job_id: Unique job identifier
            
        Returns:
            True if job was previously processed
        """
        try:
            return bool(self.client.exists(self.seen_job_key(job_id)))
        except RedisError as e:
            print(f"Redis error checking processed job: {e}")
            return False

    def reserve_job(self, job_id: str) -> bool:
        """
        Reserve a scraped job for processing using the scraper dedupe contract.

        Redis command: SET scraper:seen:job:{job_id} 1 NX EX 86400
        """
        try:
            return bool(
                self.client.set(
                    self.seen_job_key(job_id),
                    "1",
                    nx=True,
                    ex=self.settings.scraper_seen_ttl,
                )
            )
        except RedisError as e:
            print(f"Failed to reserve job in Redis: {e}")
            return False

    def release_job_reservation(self, job_id: str) -> bool:
        """Release a reservation after a failed database write so it can retry."""
        try:
            self.client.delete(self.seen_job_key(job_id))
            return True
        except RedisError as e:
            print(f"Failed to release job reservation: {e}")
            return False

    def increment_scrape_stat(self, platform: str, field: str, amount: int = 1) -> int:
        """Increment today's per-platform scraper stats hash."""
        if field not in {"scraped", "inserted", "updated", "skipped", "failed"}:
            raise ValueError(f"Unsupported scraper stats field: {field}")

        key = self.stats_key(platform)
        try:
            self._ensure_stats_date(key)
            value = self.client.hincrby(key, field, amount)
            self.client.expire(key, self.settings.scraper_stats_ttl)
            return int(value)
        except RedisError as e:
            print(f"Failed to increment scrape stat {key}.{field}: {e}")
            return 0

    def get_scrape_stats(self, platform: str) -> Dict[str, int | str]:
        key = self.stats_key(platform)
        try:
            raw = self.client.hgetall(key)
        except RedisError as e:
            print(f"Failed to get scrape stats for {platform}: {e}")
            raw = {}

        stats: Dict[str, int | str] = {"date": raw.get("date") or self._pakistan_today()}
        for field in ("scraped", "inserted", "updated", "skipped", "failed"):
            stats[field] = int(raw.get(field, 0) or 0)
        return stats

    def acquire_scraper_trigger_lock(self, trigger_id: str) -> bool:
        """Reserve the cron-triggered scraper slot for one long-running run."""
        try:
            return bool(
                self.client.set(
                    self.scraper_trigger_lock_key(),
                    trigger_id,
                    nx=True,
                    ex=self.settings.scraper_trigger_lock_ttl_seconds,
                )
            )
        except RedisError as e:
            print(f"Failed to acquire scraper trigger lock: {e}")
            return False

    def release_scraper_trigger_lock(self, trigger_id: str | None = None) -> bool:
        """Release the scraper trigger lock, preserving a newer owner's lock."""
        try:
            if trigger_id:
                current = self.client.get(self.scraper_trigger_lock_key())
                if current and current != trigger_id:
                    return False
            self.client.delete(self.scraper_trigger_lock_key())
            return True
        except RedisError as e:
            print(f"Failed to release scraper trigger lock: {e}")
            return False

    def get_scraper_trigger_lock(self) -> str | None:
        try:
            return self.client.get(self.scraper_trigger_lock_key())
        except RedisError as e:
            print(f"Failed to read scraper trigger lock: {e}")
            return None

    def set_scraper_trigger_status(self, payload: Dict) -> bool:
        status = {
            **payload,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        ttl = max(self.settings.scraper_trigger_lock_ttl_seconds * 2, 86400)
        try:
            self.client.set(self.scraper_trigger_status_key(), json.dumps(status), ex=ttl)
            return True
        except (RedisError, TypeError) as e:
            print(f"Failed to set scraper trigger status: {e}")
            return False

    def get_scraper_trigger_status(self) -> Dict:
        try:
            raw = self.client.get(self.scraper_trigger_status_key())
            if not raw:
                return {"status": "idle"}
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                return {"status": "idle"}
            return payload
        except (RedisError, json.JSONDecodeError) as e:
            print(f"Failed to get scraper trigger status: {e}")
            return {"status": "idle"}
    
    def enqueue_job(self, job_data: Dict) -> bool:
        """
        Add job to queue if not already processed.
        
        Args:
            job_data: Job dictionary to enqueue
            
        Returns:
            True if job was enqueued, False if duplicate
        """
        try:
            job_id = job_data.get('job_id')
            if not job_id:
                job_id = self._generate_job_id(job_data)
                job_data['job_id'] = job_id
            
            # Check if already processed
            if self.is_job_processed(job_id):
                return False
            
            # Add to queue
            job_json = json.dumps(job_data)
            self.client.rpush(self._get_queue_key(), job_json)
            return True
            
        except (RedisError, json.JSONDecodeError) as e:
            print(f"Failed to enqueue job: {e}")
            return False
    
    def enqueue_jobs_batch(self, jobs: List[Dict]) -> int:
        """
        Enqueue multiple jobs in a batch.
        
        Args:
            jobs: List of job dictionaries
            
        Returns:
            Number of jobs successfully enqueued
        """
        enqueued_count = 0
        
        try:
            pipeline = self.client.pipeline()
            processed_set = self._get_processed_key()
            queue_key = self._get_queue_key()
            
            for job_data in jobs:
                job_id = job_data.get('job_id')
                if not job_id:
                    job_id = self._generate_job_id(job_data)
                    job_data['job_id'] = job_id
                
                # Check if processed (outside pipeline for efficiency)
                if not self.is_job_processed(job_id):
                    job_json = json.dumps(job_data)
                    pipeline.rpush(queue_key, job_json)
                    enqueued_count += 1
            
            pipeline.execute()
            return enqueued_count
            
        except (RedisError, json.JSONDecodeError) as e:
            print(f"Batch enqueue failed: {e}")
            return 0
    
    def dequeue_job(self, timeout: int = 0) -> Optional[Dict]:
        """
        Remove and return job from queue.
        
        Args:
            timeout: Block for N seconds if queue empty (0 = non-blocking)
            
        Returns:
            Job dictionary or None if queue empty
        """
        try:
            if timeout > 0:
                result = self.client.blpop(self._get_queue_key(), timeout=timeout)
                if result:
                    _, job_json = result
                    return json.loads(job_json)
            else:
                job_json = self.client.lpop(self._get_queue_key())
                if job_json:
                    return json.loads(job_json)
            return None
            
        except (RedisError, json.JSONDecodeError) as e:
            print(f"Failed to dequeue job: {e}")
            return None
    
    def mark_job_processed(self, job_id: str) -> bool:
        """
        Mark job as processed with TTL.
        
        Args:
            job_id: Unique job identifier
            
        Returns:
            True if marked successfully
        """
        try:
            return bool(
                self.client.set(
                    self.seen_job_key(job_id),
                    "1",
                    ex=self.settings.scraper_seen_ttl,
                )
            )
        except RedisError as e:
            print(f"Failed to mark job as processed: {e}")
            return False
    
    def get_queue_length(self) -> int:
        """
        Get number of jobs in queue.
        
        Returns:
            Queue length
        """
        try:
            return self.client.llen(self._get_queue_key())
        except RedisError as e:
            print(f"Failed to get queue length: {e}")
            return 0
    
    def get_processed_count(self) -> int:
        """
        Get number of processed jobs.
        
        Returns:
            Processed job count
        """
        try:
            keys = self.client.keys("scraper:seen:job:*")
            return len(keys)
        except RedisError as e:
            print(f"Failed to get processed count: {e}")
            return 0
    
    def clear_queue(self) -> bool:
        """
        Clear all jobs from queue (use with caution).
        
        Returns:
            True if cleared successfully
        """
        try:
            self.client.delete(self._get_queue_key())
            return True
        except RedisError as e:
            print(f"Failed to clear queue: {e}")
            return False
    
    def get_stats(self) -> Dict:
        """
        Get queue statistics.
        
        Returns:
            Dictionary with queue_length and processed_count
        """
        return {
            "queue_length": self.get_queue_length(),
            "processed_count": self.get_processed_count()
        }
    
    def close(self) -> None:
        """Close Redis connection."""
        if self.client:
            self.client.close()
            print("Redis connection closed")

    # ==================== Vetting Stream Support ====================

    def _vetting_key(self, user_id: str, suffix: str) -> str:
        return f"vetting:{user_id}:{suffix}"

    def push_vetted_job(self, user_id: str, job: dict) -> bool:
        """Append a vetted job JSON to the user's Redis list."""
        try:
            key = self._vetting_key(user_id, "jobs")
            self.client.rpush(key, json.dumps(job))
            self.client.expire(key, 3600)  # 1-hour TTL on the whole list
            return True
        except (RedisError, json.JSONDecodeError) as e:
            print(f"push_vetted_job failed: {e}")
            return False

    def get_vetted_jobs(self, user_id: str, since: int = 0) -> list:
        """Return vetted jobs from index `since` onwards (inclusive)."""
        try:
            key = self._vetting_key(user_id, "jobs")
            raw = self.client.lrange(key, since, -1)
            return [json.loads(r) for r in raw]
        except (RedisError, json.JSONDecodeError) as e:
            print(f"get_vetted_jobs failed: {e}")
            return []

    def get_vetted_job_count(self, user_id: str) -> int:
        """Return total number of vetted jobs currently stored."""
        try:
            return self.client.llen(self._vetting_key(user_id, "jobs"))
        except RedisError:
            return 0

    def add_seen_job(self, user_id: str, job_id: str) -> None:
        """Mark a job as seen so it won't be processed again this session."""
        try:
            key = self._vetting_key(user_id, "seen")
            self.client.sadd(key, job_id)
            self.client.expire(key, 3600)
        except RedisError as e:
            print(f"add_seen_job failed: {e}")

    def is_job_seen(self, user_id: str, job_id: str) -> bool:
        """Check if a job was already processed in this session."""
        try:
            return bool(self.client.sismember(self._vetting_key(user_id, "seen"), job_id))
        except RedisError:
            return False

    def set_vetting_status(self, user_id: str, status: str) -> None:
        """Set the vetting pipeline status: 'processing' | 'done' | 'idle'."""
        try:
            key = self._vetting_key(user_id, "status")
            self.client.set(key, status, ex=3600)
        except RedisError as e:
            print(f"set_vetting_status failed: {e}")

    def get_vetting_status(self, user_id: str) -> str:
        """Return current vetting status string, or 'idle' if not set."""
        try:
            val = self.client.get(self._vetting_key(user_id, "status"))
            return val if val else "idle"
        except RedisError:
            return "idle"

    def update_last_poll(self, user_id: str) -> None:
        """Record the current timestamp as the last poll time (for TTL logic)."""
        try:
            import time
            key = self._vetting_key(user_id, "last_poll")
            self.client.set(key, str(time.time()), ex=120)
        except RedisError as e:
            print(f"update_last_poll failed: {e}")

    def get_last_poll(self, user_id: str) -> float:
        """Return timestamp of last poll, or 0.0 if never polled."""
        try:
            val = self.client.get(self._vetting_key(user_id, "last_poll"))
            return float(val) if val else 0.0
        except (RedisError, ValueError):
            return 0.0

    def clear_vetting_session(self, user_id: str) -> None:
        """Delete all vetting state for a user (call before starting a new session)."""
        try:
            keys = [
                self._vetting_key(user_id, "jobs"),
                self._vetting_key(user_id, "seen"),
                self._vetting_key(user_id, "status"),
                self._vetting_key(user_id, "last_poll"),
            ]
            self.client.delete(*keys)
        except RedisError as e:
            print(f"clear_vetting_session failed: {e}")


# Global service instance
_redis_service: Optional[RedisService] = None


def get_redis_service() -> RedisService:
    """
    Get or create global Redis service instance.
    
    Returns:
        RedisService instance
    """
    global _redis_service
    if _redis_service is None:
        _redis_service = RedisService()
    return _redis_service
