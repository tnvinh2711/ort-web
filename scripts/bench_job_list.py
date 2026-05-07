"""Benchmark the job list rendering path on Windows.

Run from project root:
    .venv\\Scripts\\python.exe scripts\\bench_job_list.py

Measures, in isolation:
  1. SQLite list_jobs_paged (first call vs subsequent calls)
  2. parse_vuln_summary cold (lru_cache cleared) and warm
  3. Full render_jobs_list_html cold (server cold start) and warm
  4. Full render with vuln_summary_json pre-cached in DB (the "fast path"
     the post-analyze pipeline writes for new jobs)
  5. End-to-end HTTP /partials/jobs via the FastAPI TestClient (cold + warm)
"""
from __future__ import annotations

import json
import os
import statistics
import sys
import time
from pathlib import Path

# Make the project importable when running this script directly.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from app.features.dashboard.router import render_jobs_list_html  # noqa: E402
from app.features.jobs.store import job_store  # noqa: E402
from app.features.analysis.vuln_summary import (  # noqa: E402
    parse_vuln_summary,
    get_vuln_summary,
)


def _ms(seconds: float) -> str:
    return f"{seconds * 1000:8.2f} ms"


def _stats(label: str, samples: list[float], n: int) -> None:
    avg = statistics.mean(samples)
    p50 = statistics.median(samples)
    p95 = sorted(samples)[max(0, int(len(samples) * 0.95) - 1)]
    mn, mx = min(samples), max(samples)
    print(
        f"  {label:<48} runs={n:<3} "
        f"avg={_ms(avg)}  p50={_ms(p50)}  p95={_ms(p95)}  "
        f"min={_ms(mn)}  max={_ms(mx)}"
    )


def _bench(fn, *, n: int = 5, warmup: int = 0) -> list[float]:
    for _ in range(warmup):
        fn()
    samples: list[float] = []
    for _ in range(n):
        t = time.perf_counter()
        fn()
        samples.append(time.perf_counter() - t)
    return samples


def section(title: str) -> None:
    bar = "=" * 78
    print(f"\n{bar}\n{title}\n{bar}")


def main() -> None:
    print(f"Python : {sys.version.split()[0]}  ({sys.platform})")
    print(f"OS     : {os.name}")
    print(f"CWD    : {os.getcwd()}")
    print(f"DB     : {job_store._db_path}  size={job_store._db_path.stat().st_size:,} bytes")

    jobs = job_store.list_jobs(limit=200)
    success_jobs = [j for j in jobs if j.status.value == "success"]
    cached = sum(1 for j in jobs if j.vuln_summary_json is not None)
    print(f"Jobs   : total={len(jobs)}  success={len(success_jobs)}  vuln_cached_in_db={cached}")
    print()

    # ---------------------------------------------------------------- #
    section("1) SQLite list_jobs_paged(page=1, per_page=10)")
    samples = _bench(lambda: job_store.list_jobs_paged(page=1, per_page=10), n=10)
    _stats("list_jobs_paged", samples, 10)

    # ---------------------------------------------------------------- #
    section("2) parse_vuln_summary (advisor-result.yml YAML parsing)")
    if not success_jobs:
        print("  (no successful jobs — skipped)")
    else:
        # Cold (cache cleared each iteration)
        cold_samples: list[float] = []
        for _ in range(5):
            parse_vuln_summary.cache_clear()
            t = time.perf_counter()
            for j in success_jobs:
                parse_vuln_summary(j.job_id)
            cold_samples.append(time.perf_counter() - t)
        _stats(f"parse {len(success_jobs)} files COLD (cache cleared)", cold_samples, 5)

        # Warm (lru_cache hits)
        warm_samples = _bench(
            lambda: [parse_vuln_summary(j.job_id) for j in success_jobs], n=10
        )
        _stats(f"parse {len(success_jobs)} files WARM (lru_cache hit)", warm_samples, 10)

        # Single-file cost
        sample_id = success_jobs[0].job_id
        single_cold: list[float] = []
        for _ in range(5):
            parse_vuln_summary.cache_clear()
            t = time.perf_counter()
            parse_vuln_summary(sample_id)
            single_cold.append(time.perf_counter() - t)
        _stats("parse 1 file COLD (per-file cost)", single_cold, 5)

    # ---------------------------------------------------------------- #
    section("3) Full render_jobs_list_html (what the route handler does)")

    # 3a) COLD — clear vuln cache each run, simulating a fresh process.
    def cold_render() -> None:
        parse_vuln_summary.cache_clear()
        render_jobs_list_html("vi", page=1, per_page=10)

    _stats("render COLD (parse cache cleared)", _bench(cold_render, n=5), 5)

    # 3b) WARM — vuln cache populated, only SQLite + Jinja work.
    parse_vuln_summary.cache_clear()
    render_jobs_list_html("vi", page=1, per_page=10)  # prime cache
    _stats(
        "render WARM (parse cache hit)",
        _bench(lambda: render_jobs_list_html("vi", page=1, per_page=10), n=10),
        10,
    )

    # ---------------------------------------------------------------- #
    section("4) Render with vuln_summary_json pre-cached in DB (fast path)")
    # Backfill in memory only — write JSON copies, then restore originals.
    originals: dict[str, str | None] = {}
    backfilled = 0
    for job in success_jobs:
        if job.vuln_summary_json is None:
            originals[job.job_id] = None
            try:
                summary = parse_vuln_summary(job.job_id)
                job.vuln_summary_json = json.dumps(summary)
                job_store.update_job(job)
                backfilled += 1
            except Exception as exc:
                print(f"  (skip {job.job_id[:8]}: {exc})")
    print(f"  backfilled vuln_summary_json for {backfilled} job(s)")

    parse_vuln_summary.cache_clear()
    _stats(
        "render with DB-cached vuln_summary",
        _bench(lambda: render_jobs_list_html("vi", page=1, per_page=10), n=10),
        10,
    )

    # Restore: only revert rows we backfilled in this script run.
    for job_id in originals:
        job = job_store.get_job(job_id)
        if job is not None:
            job.vuln_summary_json = None
            job_store.update_job(job)
    print(f"  restored {len(originals)} row(s) to vuln_summary_json=NULL")

    # ---------------------------------------------------------------- #
    section("5) End-to-end HTTP /partials/jobs (FastAPI TestClient)")
    try:
        from fastapi.testclient import TestClient
        from app.main import app

        with TestClient(app) as client:
            parse_vuln_summary.cache_clear()
            t = time.perf_counter()
            r = client.get("/partials/jobs?lang=vi")
            cold_total = time.perf_counter() - t
            print(f"  cold  status={r.status_code} bytes={len(r.content):,} time={_ms(cold_total)}")

            warm: list[float] = []
            for _ in range(5):
                t = time.perf_counter()
                r = client.get("/partials/jobs?lang=vi")
                warm.append(time.perf_counter() - t)
            _stats("warm /partials/jobs", warm, 5)
    except Exception as exc:
        print(f"  HTTP bench failed: {exc!r}")

    print("\nDone.")


if __name__ == "__main__":
    main()
