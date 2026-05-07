"""One-time backfill: parse advisor-result.yml for old jobs and cache JSON in DB.

New jobs get vuln_summary_json populated by the post-analyze pipeline
(see app/features/jobs/queue.py). Run this script once after upgrading to
catch jobs created before that change.

Usage (from project root):
    .venv\\Scripts\\python.exe scripts\\backfill_vuln_summary.py
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from app.features.analysis.vuln_summary import parse_vuln_summary  # noqa: E402
from app.features.jobs.store import job_store  # noqa: E402


def main() -> None:
    jobs = job_store.list_jobs(limit=10_000)
    targets = [
        j for j in jobs
        if j.status.value == "success" and j.vuln_summary_json is None
    ]

    print(f"Total jobs in DB: {len(jobs)}")
    print(f"Needing backfill: {len(targets)}")
    if not targets:
        print("Nothing to do.")
        return

    ok = 0
    failed = 0
    started = time.perf_counter()
    for i, job in enumerate(targets, 1):
        try:
            summary = parse_vuln_summary(job.job_id)
            job.vuln_summary_json = json.dumps(summary)
            job_store.update_job(job)
            ok += 1
            label = "no-vulns" if summary is None else f"{summary.get('total', 0)} vulns"
            print(f"  [{i}/{len(targets)}] {job.job_id[:12]}... -> {label}")
        except Exception as exc:
            failed += 1
            print(f"  [{i}/{len(targets)}] {job.job_id[:12]}... FAILED: {exc!r}")

    elapsed = time.perf_counter() - started
    print(f"\nDone in {elapsed:.2f}s. ok={ok}, failed={failed}.")


if __name__ == "__main__":
    main()
