-- DevLens Scraper Service schema.
-- Apply this in Supabase SQL editor or through the Supabase CLI before running main.py.

create extension if not exists pgcrypto;

create table if not exists public.jobs (
    id uuid primary key default gen_random_uuid(),
    job_id text unique not null,
    job_hash text unique not null,
    platform text not null,
    platforms text[] not null default array[]::text[],
    url text not null,
    source_job_id text,
    source_refs jsonb not null default '[]'::jsonb,
    role_keys text[] not null,
    role_labels text[] not null,
    role_queries text[] not null default array[]::text[],
    title text not null,
    company text not null,
    company_website text,
    company_logo_url text,
    industry text,
    city text,
    country text not null default 'Pakistan',
    location_raw text,
    is_remote boolean not null default false,
    workplace_type text not null default 'unknown',
    employment_type text not null default 'unknown',
    experience_level text not null default 'unknown',
    is_internship boolean not null default false,
    experience_min_years integer,
    experience_max_years integer,
    education_required text,
    description text,
    requirements text[] not null default array[]::text[],
    responsibilities text[] not null default array[]::text[],
    tech_stack text[] not null default array[]::text[],
    benefits text[] not null default array[]::text[],
    skills_categorized jsonb not null default '{}'::jsonb,
    salary_min numeric,
    salary_max numeric,
    salary_currency char(3),
    salary_period text not null default 'unknown',
    salary_raw text,
    posted_at timestamptz,
    scraped_at timestamptz not null default now(),
    last_seen_at timestamptz not null default now(),
    expires_at timestamptz,
    is_active boolean not null default true,
    is_enriched boolean not null default false,
    enrichment_confidence numeric(4,3),
    enriched_at timestamptz,
    raw_payload jsonb not null default '{}'::jsonb,
    search_vector tsvector,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

alter table public.jobs add column if not exists id uuid default gen_random_uuid();
alter table public.jobs add column if not exists job_id text;
alter table public.jobs add column if not exists job_hash text;
alter table public.jobs add column if not exists platform text default 'unknown';
alter table public.jobs add column if not exists platforms text[] not null default array[]::text[];
alter table public.jobs add column if not exists url text default '';
alter table public.jobs add column if not exists source_job_id text;
alter table public.jobs add column if not exists source_refs jsonb not null default '[]'::jsonb;
alter table public.jobs add column if not exists role_keys text[] not null default array[]::text[];
alter table public.jobs add column if not exists role_labels text[] not null default array[]::text[];
alter table public.jobs add column if not exists role_queries text[] not null default array[]::text[];
alter table public.jobs add column if not exists title text default '';
alter table public.jobs add column if not exists company text default '';
alter table public.jobs add column if not exists company_website text;
alter table public.jobs add column if not exists company_logo_url text;
alter table public.jobs add column if not exists industry text;
alter table public.jobs add column if not exists city text;
alter table public.jobs add column if not exists country text not null default 'Pakistan';
alter table public.jobs add column if not exists location_raw text;
alter table public.jobs add column if not exists is_remote boolean not null default false;
alter table public.jobs add column if not exists workplace_type text not null default 'unknown';
alter table public.jobs add column if not exists employment_type text not null default 'unknown';
alter table public.jobs add column if not exists experience_level text not null default 'unknown';
alter table public.jobs add column if not exists is_internship boolean not null default false;
alter table public.jobs add column if not exists experience_min_years integer;
alter table public.jobs add column if not exists experience_max_years integer;
alter table public.jobs add column if not exists education_required text;
alter table public.jobs add column if not exists description text;
alter table public.jobs add column if not exists requirements text[] not null default array[]::text[];
alter table public.jobs add column if not exists responsibilities text[] not null default array[]::text[];
alter table public.jobs add column if not exists tech_stack text[] not null default array[]::text[];
alter table public.jobs add column if not exists benefits text[] not null default array[]::text[];
alter table public.jobs add column if not exists skills_categorized jsonb not null default '{}'::jsonb;
alter table public.jobs add column if not exists salary_min numeric;
alter table public.jobs add column if not exists salary_max numeric;
alter table public.jobs add column if not exists salary_currency char(3);
alter table public.jobs add column if not exists salary_period text not null default 'unknown';
alter table public.jobs add column if not exists salary_raw text;
alter table public.jobs add column if not exists posted_at timestamptz;
alter table public.jobs add column if not exists scraped_at timestamptz not null default now();
alter table public.jobs add column if not exists last_seen_at timestamptz not null default now();
alter table public.jobs add column if not exists expires_at timestamptz;
alter table public.jobs add column if not exists is_active boolean not null default true;
alter table public.jobs add column if not exists is_enriched boolean not null default false;
alter table public.jobs add column if not exists enrichment_confidence numeric(4,3);
alter table public.jobs add column if not exists enriched_at timestamptz;
alter table public.jobs add column if not exists raw_payload jsonb not null default '{}'::jsonb;
alter table public.jobs add column if not exists created_at timestamptz not null default now();
alter table public.jobs add column if not exists updated_at timestamptz not null default now();

do $$
begin
    if exists (
        select 1 from information_schema.columns
        where table_schema = 'public' and table_name = 'jobs' and column_name = 'job_title'
    ) then
        execute 'update public.jobs set title = job_title where (title is null or title = '''') and job_title is not null';
    end if;

    if exists (
        select 1 from information_schema.columns
        where table_schema = 'public' and table_name = 'jobs' and column_name = 'job_description'
    ) then
        execute 'update public.jobs set description = job_description where description is null and job_description is not null';
    end if;

    if exists (
        select 1 from information_schema.columns
        where table_schema = 'public' and table_name = 'jobs' and column_name = 'skills_required'
    ) then
        execute 'update public.jobs set tech_stack = skills_required where cardinality(tech_stack) = 0 and skills_required is not null';
    end if;

    if exists (
        select 1 from information_schema.columns
        where table_schema = 'public' and table_name = 'jobs' and column_name = 'job_source'
    ) then
        execute 'update public.jobs set platform = lower(job_source) where (platform is null or platform = ''unknown'') and job_source is not null';
    end if;

    if exists (
        select 1 from information_schema.columns
        where table_schema = 'public' and table_name = 'jobs' and column_name = 'job_type'
    ) then
        execute 'update public.jobs set employment_type = lower(job_type) where employment_type = ''unknown'' and job_type is not null';
    end if;

    if exists (
        select 1 from information_schema.columns
        where table_schema = 'public' and table_name = 'jobs' and column_name = 'location'
    ) then
        execute 'update public.jobs set location_raw = location where location_raw is null and location is not null';
    end if;

    if exists (
        select 1 from information_schema.columns
        where table_schema = 'public' and table_name = 'jobs' and column_name = 'date_scrapped'
    ) then
        execute 'update public.jobs set scraped_at = date_scrapped where scraped_at is null and date_scrapped is not null';
    end if;
end $$;

alter table public.jobs add column if not exists search_vector tsvector;

update public.jobs
set job_id = encode(digest(id::text, 'sha256'), 'hex')
where job_id is null;

update public.jobs
set job_hash = encode(digest(coalesce(job_id, id::text), 'sha256'), 'hex')
where job_hash is null;

update public.jobs set platform = 'unknown' where platform is null or platform = '';
update public.jobs set url = coalesce(url, '') where url is null;
update public.jobs set title = coalesce(title, '') where title is null;
update public.jobs set company = coalesce(company, '') where company is null;
update public.jobs set last_seen_at = coalesce(last_seen_at, scraped_at, now()) where last_seen_at is null;

alter table public.jobs alter column id set default gen_random_uuid();
alter table public.jobs alter column job_id set not null;
alter table public.jobs alter column job_hash set not null;
alter table public.jobs alter column platform set not null;
alter table public.jobs alter column url set not null;
alter table public.jobs alter column title set not null;
alter table public.jobs alter column company set not null;

do $$
begin
    if not exists (
        select 1 from pg_constraint
        where conname = 'jobs_job_id_key' and conrelid = 'public.jobs'::regclass
    ) then
        alter table public.jobs add constraint jobs_job_id_key unique (job_id);
    end if;

    if not exists (
        select 1 from pg_constraint
        where conname = 'jobs_job_hash_key' and conrelid = 'public.jobs'::regclass
    ) then
        alter table public.jobs add constraint jobs_job_hash_key unique (job_hash);
    end if;
end $$;

do $$
begin
    if not exists (select 1 from pg_constraint where conname = 'jobs_workplace_type_check') then
        alter table public.jobs add constraint jobs_workplace_type_check
            check (workplace_type in ('onsite', 'remote', 'hybrid', 'unknown')) not valid;
    end if;
    if not exists (select 1 from pg_constraint where conname = 'jobs_employment_type_check') then
        alter table public.jobs add constraint jobs_employment_type_check
            check (employment_type in ('full-time', 'part-time', 'internship', 'contract', 'freelance', 'unknown')) not valid;
    end if;
    if not exists (select 1 from pg_constraint where conname = 'jobs_experience_level_check') then
        alter table public.jobs add constraint jobs_experience_level_check
            check (experience_level in ('junior', 'mid', 'senior', 'lead', 'unknown')) not valid;
    end if;
    if not exists (select 1 from pg_constraint where conname = 'jobs_salary_period_check') then
        alter table public.jobs add constraint jobs_salary_period_check
            check (salary_period in ('hour', 'day', 'week', 'month', 'year', 'unknown')) not valid;
    end if;
end $$;

create table if not exists public.scrape_logs (
    id uuid primary key default gen_random_uuid(),
    run_id uuid not null,
    started_at timestamptz,
    finished_at timestamptz,
    status text not null check (status in ('running', 'success', 'partial_failed', 'failed')),
    platform text,
    role_key text,
    role_label text,
    query text,
    location text,
    scraped_count integer not null default 0,
    inserted_count integer not null default 0,
    updated_count integer not null default 0,
    skipped_count integer not null default 0,
    failed_count integer not null default 0,
    redis_stats_key text,
    error_message text,
    metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);

create table if not exists public.users (
    id uuid primary key default gen_random_uuid(),
    email text unique,
    full_name text,
    role_preferences text[] not null default array[]::text[],
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists public.cv_scores (
    id uuid primary key default gen_random_uuid(),
    user_id uuid references public.users(id),
    cv_hash text not null,
    role_key text not null,
    role_label text,
    score numeric(5,2),
    matched_skills text[] not null default array[]::text[],
    missing_skills text[] not null default array[]::text[],
    recommendations jsonb not null default '{}'::jsonb,
    scored_at timestamptz not null default now(),
    unique (user_id, cv_hash, role_key)
);

create index if not exists jobs_role_keys_gin_idx on public.jobs using gin (role_keys);
create index if not exists jobs_tech_stack_gin_idx on public.jobs using gin (tech_stack);
create index if not exists jobs_requirements_gin_idx on public.jobs using gin (requirements);
create index if not exists jobs_active_scraped_idx on public.jobs (is_active, scraped_at desc);
create index if not exists jobs_platform_scraped_idx on public.jobs (platform, scraped_at desc);
create index if not exists jobs_city_country_idx on public.jobs (city, country);
create index if not exists jobs_type_level_idx on public.jobs (employment_type, experience_level);
create index if not exists jobs_posted_at_idx on public.jobs (posted_at desc);
create index if not exists jobs_search_vector_idx on public.jobs using gin (search_vector);
create index if not exists scrape_logs_run_idx on public.scrape_logs (run_id, role_key, platform, query);
create index if not exists cv_scores_lookup_idx on public.cv_scores (user_id, cv_hash, role_key);

create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
    new.updated_at = now();
    return new;
end;
$$;

create or replace function public.set_jobs_search_vector()
returns trigger
language plpgsql
as $$
begin
    new.search_vector :=
        to_tsvector(
            'english',
            coalesce(new.title, '') || ' ' ||
            coalesce(new.company, '') || ' ' ||
            coalesce(new.description, '') || ' ' ||
            coalesce(array_to_string(new.tech_stack, ' '), '') || ' ' ||
            coalesce(array_to_string(new.requirements, ' '), '')
        );
    return new;
end;
$$;

update public.jobs
set search_vector =
    to_tsvector(
        'english',
        coalesce(title, '') || ' ' ||
        coalesce(company, '') || ' ' ||
        coalesce(description, '') || ' ' ||
        coalesce(array_to_string(tech_stack, ' '), '') || ' ' ||
        coalesce(array_to_string(requirements, ' '), '')
    );

drop trigger if exists jobs_set_updated_at on public.jobs;
create trigger jobs_set_updated_at
before update on public.jobs
for each row execute function public.set_updated_at();

drop trigger if exists jobs_set_search_vector on public.jobs;
create trigger jobs_set_search_vector
before insert or update of title, company, description, tech_stack, requirements on public.jobs
for each row execute function public.set_jobs_search_vector();

drop trigger if exists users_set_updated_at on public.users;
create trigger users_set_updated_at
before update on public.users
for each row execute function public.set_updated_at();
