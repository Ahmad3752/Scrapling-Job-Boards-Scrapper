<div align="center">

# Job Board Scraper

**Multi-board job scraper for Pakistan**

[![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)](https://python.org)
[![Scrapling](https://img.shields.io/badge/Scrapling-0.4.7-FF6B35)](https://github.com/D4Vinci/Scrapling)
[![Supabase](https://img.shields.io/badge/Supabase-2.30-3ECF8E?logo=supabase&logoColor=white)](https://supabase.com)
[![Redis](https://img.shields.io/badge/Redis-7.4-DC382D?logo=redis&logoColor=white)](https://redis.io)
[![uv](https://img.shields.io/badge/uv-package%20manager-7C3AED)](https://github.com/astral-sh/uv)

Scrape LinkedIn and Indeed for job listings in Pakistan. Cleans and enriches each posting, deduplicates via Redis and upserts everything to Supabase.

</div>

---

## Table of Contents

- [Overview](#overview)
- [Pipeline](#pipeline)
- [Features](#features)
- [Tech Stack](#tech-stack)
- [Prerequisites](#prerequisites)
- [Getting Started](#getting-started)
- [Deployment](#deployment)
- [Roles Covered](#roles-covered)
- [Project Structure](#project-structure)

---

## Overview

`main.py` iterates over a configured list of permitted roles and runs the full pipeline for each one using a configurable number of parallel workers (default: sequential). The spider fetches listing pages and individual job postings using Scrapling's `StealthyFetcher` which handles Cloudflare challenges and anti-bot detection. Each parser extracts structured fields from the board's HTML. Roles that fail during the main pass are retried once sequentially after all other roles complete.

New jobs are checked against a Redis processed set so duplicates are never written twice. Unique jobs pass through the enricher which cleans the description, matches skills against a master Excel list, parses experience level and year ranges, normalises salary strings and detects education and job type. Enriched records are upserted to Supabase in batches of 200.

A separate `digital_scout_node` in `pipeline/scout.py` handles interactive, query-driven scraping with role-allowlist enforcement. It is not called by `main.py` but is available for integration into a wider agent workflow.

---

## Pipeline

```
┌─────────────────────────────────────────────────────────┐
│  Permitted roles (PERMITTED_ROLES_1 / _2 env var)       │
│  e.g. 30 roles per set                                  │
└──────────────────────────┬──────────────────────────────┘
                           │
                    ┌──────┴──────┐
                    │ Worker Pool │
                    └──────┬──────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│  Spider  (scraper/spider.py)                            │
│  StealthyFetcher with Cloudflare bypass                 │
│  One parser per board - LinkedIn and Indeed              │
│  Each with adaptive CSS selectors                       │
└──────────────────────────┬──────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│  Redis Deduplication  (services/redis.py)               │
│  SHA-256 job ID checked against processed set           │
│  TTL-based expiry (default 24 h)                        │
└──────────────────────────┬──────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│  Enricher  (pipeline/enricher.py)                       │
│  Description cleaning + section splitting               │
│  Skill extraction from master Excel list                │
│  Experience level + year-range parsing                  │
│  Salary normalisation + education/job-type detection    │
│  Enrichment confidence score per job                    │
└──────────────────────────┬──────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│  Supabase Upsert  (services/supabase.py)                │
│  Batched upsert on conflict (job_id)                    │
│  200 records per batch                                  │
└─────────────────────────────────────────────────────────┘
```

---

## Features

| Feature | Description |
|:---|:---|
| **Multi-board scraping** | LinkedIn and Indeed with two alternating role sets |
| **Anti-bot bypass** | Scrapling `StealthyFetcher` with Cloudflare solver and headless/headful fallback |
| **Role allowlist** | Only scrapes roles listed in `PERMITTED_ROLES` - rejects everything else |
| **Redis deduplication** | SHA-256 job IDs tracked in a TTL-based Redis set; duplicates never re-processed |
| **Description cleaning** | HTML entity decoding, whitespace normalisation, section splitting, sentence deduplication |
| **Skill extraction** | Word-boundary regex matching against a configurable master Excel skill list |
| **Experience parsing** | Detects level (entry/junior/mid/senior/lead) and min/max year ranges |
| **Salary normalisation** | Parses currency, amount range and period from free-text salary strings |
| **Parallel workers** | Configurable thread pool for scraping multiple roles simultaneously |
| **Failed role retry** | Roles that fail during the main pass are retried once sequentially after all others complete |
| **Batched upsert** | Supabase upsert in configurable batches with conflict resolution on `job_id` |
| **Enrichment confidence** | Scores each job 0–1 based on how much structured data was extracted |
| **Stale job cleanup** | Deletes jobs older than a configurable number of days at the start of each run |

---

## Tech Stack

| Layer | Technology |
|:---|:---|
| Scraping | Scrapling 0.4.7 (`StealthyFetcher`) |
| Parsers | Per-board CSS selector parsers with adaptive fallback chains |
| Enrichment | pandas, regex, openpyxl |
| Deduplication / Queue | Redis 7.4 |
| Database | Supabase (PostgreSQL via `supabase-py` 2.30) |
| State | LangChain Core (message types) |
| Runtime | Python 3.12, uv |

---

## Prerequisites

- Python 3.12+
- Redis (local or remote)
- Supabase project with service role key
- Scrapling fetcher extras (installs Playwright/Camoufox automatically via `scrapling[fetchers]`)
- Master skill list Excel file (default: `data/skills_master.xlsx`)

---

## Getting Started

```bash
git clone <repo-url>
cd Scrapling-Job-Board-Scrapper

# Install dependencies
uv sync

# Download Playwright browser binaries (required for StealthyFetcher)
uv run playwright install

# Copy and fill in environment variables
cp .env.example .env
```

Edit `.env` with your Supabase credentials and Redis URL (see [Environment Variables](#environment-variables)), then run:

```bash
uv run python main.py
```

---

## Deployment

The scraper is deployed via **GitHub Actions** with 8 scheduled runs per day - LinkedIn and Indeed alternate every 3 hours with each role set scraped twice. No server required.

| Time (PKT) | Board | Role Set |
|:---|:---|:---|
| 1:00 AM | LinkedIn | Set 1 |
| 4:00 AM | Indeed | Set 1 |
| 7:00 AM | LinkedIn | Set 2 |
| 10:00 AM | Indeed | Set 2 |
| 1:00 PM | LinkedIn | Set 1 |
| 4:00 PM | Indeed | Set 1 |
| 7:00 PM | LinkedIn | Set 2 |
| 10:00 PM | Indeed | Set 2 |

### Setup

1. Push the repo to GitHub
2. Go to **Settings → Secrets and variables → Actions** and add the following secrets:

| Secret | Description |
|:---|:---|
| `SUPABASE_URL` | Your Supabase project URL |
| `SUPABASE_SERVICE_ROLE_KEY` | Your Supabase service role key |
| `REDIS_URL` | Upstash Redis URL (`rediss://...`) |
| `PERMITTED_ROLES_1` | JSON array of roles for the first daily pass |
| `PERMITTED_ROLES_2` | JSON array of roles for the second daily pass |
| `JOB_SCRAPING_WORKERS` | Number of parallel workers (default: 1) |
| `REDIS_MAX_RETRIES` | Number of Redis retry attempts |
| `REDIS_JOB_QUEUE_PREFIX` | Redis key prefix for job queue |
| `REDIS_PROCESSED_TTL` | TTL in seconds for processed job IDs |
| `JOB_SCRAPING_MAX_PAGES_PER_BOARD` | Max listing pages to scrape per board |
| `JOB_SCRAPING_MAX_JOBS_PER_BOARD` | Max jobs to scrape per board |
| `JOB_SCRAPING_DOWNLOAD_DELAY` | Delay in seconds between requests |
| `JOB_STALE_AFTER_DAYS` | Days after which scraped jobs are deleted |

3. Go to **Actions → Daily Job Scrape → Run workflow** to trigger a manual run - use the dropdowns to select a specific board and role set, or leave as "all" for both

The workflow file is at `.github/workflows/scrape.yml`.

---

## Roles Covered

60 roles across two sets, each scraped twice daily on both LinkedIn and Indeed.

**Set 1 (30 roles)**

Software Engineer, Data Engineer, UI/UX Designer, DevOps Engineer, Java Developer, Data Analyst, React Developer, MERN Stack Developer, Mobile App Developer, Backend Developer, Associate Software Engineer, Node.js Developer, Flutter Developer, Cybersecurity Analyst, LLM Engineer, NLP Engineer, Information Security Analyst, MLOps Engineer, BI Developer, AWS Cloud Engineer, QA Automation Engineer, iOS Developer, Salesforce Developer, Ethical Hacker, SOC Analyst, DevSecOps Engineer, AI Research Engineer, Conversational AI Developer, Game Developer, AI Product Developer

**Set 2 (30 roles)**

Full-Stack Developer, Machine Learning Engineer, AI Engineer, Frontend Developer, SQA Engineer, Data Scientist, Python Developer, Blockchain Developer, Generative AI Engineer, Business Analyst, Product Manager, AI Automation Engineer, Cybersecurity Engineer, Android Developer, Agentic AI Developer, Cloud Engineer, Computer Vision Engineer, Business Intelligence Analyst, Analytics Engineer, Network Security Engineer, Azure Engineer, Solutions Architect, Penetration Tester, Web3 Developer, Application Security Engineer, Cloud Security Engineer, SIEM Engineer, Technical Project Manager, Big Data Engineer, Polyglot Engineer

---

## Project Structure

```
main.py                    <- entry point: runs full pipeline for all permitted roles
pyproject.toml             <- dependencies (managed with uv)
.env.example               <- environment variable template
data/
  skills_master.xlsx       <- master skill list used by the enricher
core/
  settings.py              <- env-backed settings singleton
  state.py                 <- AgentState and JobData TypedDicts
  role_filters.py          <- role allowlist enforcement helpers
scraper/
  spider.py                <- multi-board scrape coordinator (JobScraperSpider)
  boards/
    base.py                <- BaseJobParser ABC with shared utilities
    linkedin.py            <- LinkedIn parser
    indeed.py              <- Indeed parser
pipeline/
  enricher.py              <- JobEnricher: description cleaning, skill/experience/salary extraction
  enricher_node.py         <- LangChain node wrapper around JobEnricher
  scout.py                 <- digital_scout_node: query-driven scraping with role guard
services/
  redis.py                 <- Redis queue and deduplication service
  supabase.py              <- Supabase CRUD operations
tests/
  test_scout.py            <- query-intent validation tests for digital_scout_node
```
