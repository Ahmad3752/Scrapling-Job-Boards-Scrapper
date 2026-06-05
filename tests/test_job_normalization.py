import unittest

from scraper.normalization import (
    compute_job_hash,
    merge_supabase_job,
    normalize_job_for_supabase,
)


class TestJobNormalization(unittest.TestCase):
    def test_normalizes_required_devlens_fields_for_pakistan(self):
        record = normalize_job_for_supabase(
            {
                "job_id": "job_1",
                "title": "Backend Developer Intern",
                "company": "Acme",
                "location": "Lahore, Pakistan",
                "board": "indeed",
                "job_url": "https://pk.indeed.com/viewjob?jk=abc123",
                "description": "Build APIs with Python and PostgreSQL.",
                "skills": ["Python", "PostgreSQL", "Python"],
                "employment_type": "Internship",
                "salary_normalized": {
                    "min": 50000,
                    "max": 80000,
                    "currency": "PKR",
                    "period": "month",
                    "raw": "PKR 50,000 - 80,000 per month",
                },
                "experience_parsed": {"min_years": 0, "max_years": 1, "level": "entry"},
            },
            "backend",
            "Backend Developer Intern",
        )

        self.assertEqual(record["country"], "Pakistan")
        self.assertEqual(record["city"], "Lahore")
        self.assertEqual(record["role_keys"], ["backend"])
        self.assertEqual(record["role_labels"], ["Backend Developer"])
        self.assertEqual(record["employment_type"], "internship")
        self.assertEqual(record["experience_level"], "junior")
        self.assertTrue(record["is_internship"])
        self.assertEqual(record["source_job_id"], "abc123")
        self.assertEqual(record["tech_stack"], ["Python", "PostgreSQL"])
        self.assertEqual(record["salary_currency"], "PKR")
        self.assertNotIn("raw_html", record["raw_payload"])

    def test_job_hash_dedupes_across_platforms(self):
        first = {
            "title": "Frontend Developer",
            "company": "Acme",
            "location": "Karachi, Pakistan",
            "board": "linkedin",
        }
        second = {
            "title": "Frontend Developer",
            "company": "Acme",
            "location": "Karachi, Pakistan",
            "board": "indeed",
        }

        self.assertEqual(compute_job_hash(first), compute_job_hash(second))

    def test_merge_preserves_roles_platforms_and_source_refs(self):
        existing = {
            "id": "row_1",
            "created_at": "2026-06-05T00:00:00+00:00",
            "role_keys": ["backend"],
            "role_labels": ["Backend Developer"],
            "role_queries": ["Backend Developer"],
            "platforms": ["indeed"],
            "source_refs": [{"platform": "indeed", "source_job_id": "abc", "url": "https://indeed.test"}],
        }
        incoming = {
            "role_keys": ["full_stack"],
            "role_labels": ["Full Stack Developer"],
            "role_queries": ["MERN Stack Developer"],
            "platforms": ["linkedin"],
            "source_refs": [{"platform": "linkedin", "source_job_id": "123", "url": "https://linkedin.test"}],
            "title": "Full Stack Developer",
        }

        merged = merge_supabase_job(existing, incoming)

        self.assertEqual(merged["role_keys"], ["backend", "full_stack"])
        self.assertEqual(merged["platforms"], ["indeed", "linkedin"])
        self.assertEqual(len(merged["source_refs"]), 2)
        self.assertNotIn("id", merged)
        self.assertEqual(merged["created_at"], existing["created_at"])


if __name__ == "__main__":
    unittest.main()
