"""Canonical DevLens developer roles used by the scraper corpus."""

from __future__ import annotations

from typing import Iterable


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


def canonical_role_keys() -> list[str]:
    return list(DEVELOPER_ROLES.keys())


def canonical_role_labels() -> list[str]:
    return list(DEVELOPER_ROLES.values())


def role_label_for_key(role_key: str) -> str:
    return DEVELOPER_ROLES[role_key]


def queries_for_role(role_key: str) -> list[str]:
    return ROLE_QUERIES.get(role_key, [role_label_for_key(role_key)])


def role_key_from_label(label: str) -> str | None:
    normalized = " ".join((label or "").lower().replace("-", " ").split())
    for key, value in DEVELOPER_ROLES.items():
        role_normalized = " ".join(value.lower().replace("-", " ").split())
        if normalized == role_normalized:
            return key
    return None


def filter_role_keys(values: Iterable[str]) -> list[str]:
    role_keys: list[str] = []
    for value in values:
        normalized = str(value or "").strip()
        if not normalized:
            continue
        if normalized in DEVELOPER_ROLES and normalized not in role_keys:
            role_keys.append(normalized)
            continue
        key = role_key_from_label(normalized)
        if key and key not in role_keys:
            role_keys.append(key)
    return role_keys
