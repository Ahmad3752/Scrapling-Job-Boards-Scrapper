"""Normalize scraped jobs into the DevLens-ready Supabase jobs contract."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qs, urlparse

from core.devlens_roles import role_label_for_key


PAKISTAN_COUNTRY = "Pakistan"

PAKISTAN_CITIES = [
    "Lahore",
    "Karachi",
    "Islamabad",
    "Rawalpindi",
    "Faisalabad",
    "Multan",
    "Peshawar",
    "Quetta",
    "Hyderabad",
    "Sialkot",
    "Gujranwala",
    "Gujrat",
    "Bahawalpur",
    "Sargodha",
    "Abbottabad",
    "Wah",
    "Remote",
]


def _compact(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _normalize_for_hash(value: Any) -> str:
    text = _compact(value).lower()
    text = re.sub(r"[^a-z0-9+#.]+", " ", text)
    return " ".join(text.split())


def _unique_strings(values: Any) -> list[str]:
    if values is None:
        return []
    if isinstance(values, dict):
        flattened: list[Any] = []
        for item in values.values():
            if isinstance(item, list):
                flattened.extend(item)
        values = flattened
    if not isinstance(values, list):
        values = [values]

    unique: list[str] = []
    seen: set[str] = set()
    for item in values:
        text = _compact(item)
        key = text.lower()
        if text and key not in seen:
            seen.add(key)
            unique.append(text)
    return unique


def _split_section_text(value: Any) -> list[str]:
    text = _compact(value)
    if not text:
        return []
    parts = re.split(r"(?:\s*[;•]\s*|\s+-\s+|(?<=[.!?])\s+)", text)
    return [part.strip(" :-") for part in parts if len(part.strip(" :-")) >= 3]


def _parse_datetime(value: Any) -> str | None:
    text = _compact(value)
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).isoformat()
    except ValueError:
        return None


def _extract_source_job_id(platform: str, url: str, fallback: str) -> str:
    parsed = urlparse(url or "")
    query = parse_qs(parsed.query)

    if platform == "indeed" and query.get("jk"):
        return query["jk"][0]
    if platform == "linkedin":
        match = re.search(r"/jobs/view/(\d+)", parsed.path)
        if match:
            return match.group(1)
    if platform == "mustakbil":
        match = re.search(r"/jobs/job/([^/?#]+)", parsed.path)
        if match:
            return match.group(1)
    if platform == "rozee":
        slug = parsed.path.strip("/").split("/")[-1]
        if slug:
            return slug
    return fallback


def _normalize_employment_type(value: Any, title: str, description: str) -> str:
    haystack = f"{value or ''} {title} {description}".lower()
    if "intern" in haystack or "trainee" in haystack:
        return "internship"
    if "freelance" in haystack:
        return "freelance"
    if "contract" in haystack or "temporary" in haystack:
        return "contract"
    if "part-time" in haystack or "part time" in haystack or "parttime" in haystack:
        return "part-time"
    if "full-time" in haystack or "full time" in haystack or "fulltime" in haystack or "permanent" in haystack:
        return "full-time"
    return "unknown"


def _normalize_experience_level(value: Any, title: str, description: str) -> str:
    text = f"{value or ''} {title} {description}".lower()
    if any(signal in text for signal in ("lead", "principal", "architect", "10+ years")):
        return "lead"
    if any(signal in text for signal in ("senior", "sr.", "5+ years", "6+ years", "7+ years")):
        return "senior"
    if any(signal in text for signal in ("mid", "intermediate", "3-5 years", "4-6 years")):
        return "mid"
    if any(signal in text for signal in ("junior", "entry", "fresher", "fresh graduate", "0-1 years", "1-2 years")):
        return "junior"
    return "unknown"


def _normalize_location(value: Any) -> dict[str, Any]:
    raw = _compact(value) or PAKISTAN_COUNTRY
    lower = raw.lower()
    is_remote = "remote" in lower or "work from home" in lower or "wfh" in lower
    workplace_type = "remote" if is_remote else "onsite"
    if "hybrid" in lower:
        workplace_type = "hybrid"

    city = None
    for candidate in PAKISTAN_CITIES:
        if candidate.lower() in lower:
            city = None if candidate == "Remote" else candidate
            break

    if city is None and raw and PAKISTAN_COUNTRY.lower() not in lower and not is_remote:
        first_part = raw.split(",")[0].strip()
        city = first_part or None

    return {
        "city": city,
        "country": PAKISTAN_COUNTRY,
        "location_raw": raw,
        "is_remote": is_remote,
        "workplace_type": workplace_type,
    }


def _salary_fields(job: dict[str, Any]) -> dict[str, Any]:
    salary = job.get("salary_normalized") or {}
    if not isinstance(salary, dict):
        salary = {}
    return {
        "salary_min": salary.get("min"),
        "salary_max": salary.get("max"),
        "salary_currency": salary.get("currency"),
        "salary_period": salary.get("period") or "unknown",
        "salary_raw": salary.get("raw") or job.get("salary"),
    }


def compute_job_hash(job: dict[str, Any]) -> str:
    parts = [
        _normalize_for_hash(job.get("title")),
        _normalize_for_hash(job.get("company")),
        _normalize_for_hash(job.get("location")),
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def normalize_job_for_supabase(
    job: dict[str, Any],
    role_key: str,
    role_query: str | None = None,
) -> dict[str, Any]:
    role_label = role_label_for_key(role_key)
    platform = _compact(job.get("board") or job.get("job_source") or job.get("platform")).lower() or "unknown"
    title = _compact(job.get("title")) or "Untitled role"
    company = _compact(job.get("company")) or "Unknown company"
    description = _compact(job.get("description"))
    url = _compact(job.get("job_url") or job.get("url"))
    source_job_id = _extract_source_job_id(platform, url, _compact(job.get("source_job_id") or job.get("job_id")))
    job_hash = compute_job_hash(job)
    job_id = _compact(job.get("job_id")) or hashlib.sha256(f"{platform}|{source_job_id}|{job_hash}".encode("utf-8")).hexdigest()[:16]
    now = datetime.now(timezone.utc).isoformat()

    location = _normalize_location(job.get("location") or job.get("location_raw"))
    employment_type = _normalize_employment_type(job.get("employment_type") or job.get("job_type"), title, description)
    experience = job.get("experience_parsed") if isinstance(job.get("experience_parsed"), dict) else {}
    experience_level = _normalize_experience_level(experience.get("level") or job.get("experience_level"), title, description)
    sections = job.get("description_sections") if isinstance(job.get("description_sections"), dict) else {}
    skills_categorized = job.get("skills_categorized") if isinstance(job.get("skills_categorized"), dict) else {}
    tech_stack = _unique_strings(job.get("skills"))
    salary = _salary_fields(job)
    is_internship = employment_type == "internship"

    raw_payload = {key: value for key, value in job.items() if key != "raw_html"}

    record = {
        "job_id": job_id,
        "job_hash": job_hash,
        "platform": platform,
        "platforms": [platform],
        "url": url,
        "source_job_id": source_job_id,
        "source_refs": [
            {
                "platform": platform,
                "source_job_id": source_job_id,
                "url": url,
                "scraped_at": now,
            }
        ],
        "role_keys": [role_key],
        "role_labels": [role_label],
        "role_queries": [role_query or role_label],
        "title": title,
        "company": company,
        "company_website": job.get("company_website"),
        "company_logo_url": job.get("company_logo_url"),
        "industry": job.get("industry"),
        **location,
        "employment_type": employment_type,
        "experience_level": experience_level,
        "is_internship": is_internship,
        "experience_min_years": experience.get("min_years"),
        "experience_max_years": experience.get("max_years"),
        "education_required": job.get("education_required"),
        "description": description,
        "requirements": _split_section_text(sections.get("requirements")),
        "responsibilities": _split_section_text(sections.get("responsibilities")),
        "tech_stack": tech_stack,
        "benefits": _split_section_text(sections.get("benefits")),
        "skills_categorized": skills_categorized,
        **salary,
        "posted_at": _parse_datetime(job.get("posted_at") or job.get("posted_date")),
        "scraped_at": now,
        "last_seen_at": now,
        "expires_at": _parse_datetime(job.get("expires_at")),
        "is_active": True,
        "is_enriched": bool(job.get("enrichment_timestamp") or skills_categorized or tech_stack),
        "enrichment_confidence": job.get("enrichment_confidence"),
        "enriched_at": _parse_datetime(job.get("enrichment_timestamp")),
        "raw_payload": raw_payload,
        "updated_at": now,
    }

    return {key: value for key, value in record.items() if value is not None}


def merge_supabase_job(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    merged = dict(incoming)
    for field in ("role_keys", "role_labels", "role_queries", "platforms"):
        merged[field] = _unique_strings((existing.get(field) or []) + (incoming.get(field) or []))

    source_refs = existing.get("source_refs") or []
    if not isinstance(source_refs, list):
        source_refs = []
    seen_refs = {
        (
            _compact(item.get("platform")).lower(),
            _compact(item.get("source_job_id")),
            _compact(item.get("url")),
        )
        for item in source_refs
        if isinstance(item, dict)
    }
    merged_refs = list(source_refs)
    for item in incoming.get("source_refs") or []:
        ref_key = (
            _compact(item.get("platform")).lower(),
            _compact(item.get("source_job_id")),
            _compact(item.get("url")),
        )
        if ref_key not in seen_refs:
            seen_refs.add(ref_key)
            merged_refs.append(item)
    merged["source_refs"] = merged_refs

    merged["created_at"] = existing.get("created_at")
    return {key: value for key, value in merged.items() if key != "id"}
