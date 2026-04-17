from __future__ import annotations

from pathlib import Path

import yaml

from app.config import settings

_SEVERITY_RANK = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1}


def parse_vuln_summary(job_id: str) -> dict | None:
    """Parse advisor-result.yml and return vulnerability counts by severity.

    Returns a dict like ``{"critical": 2, "high": 5, "medium": 3, "low": 1, "total": 11}``
    or ``None`` when no advisor result exists or no vulnerabilities were found.
    """
    advisor_result = settings.artifacts_dir / job_id / "advisor-result.yml"
    if not advisor_result.exists():
        return None
    try:
        with advisor_result.open(encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except Exception:
        return None

    results = (data.get("advisor") or {}).get("results") or {}
    counts: dict[str, int] = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    seen: set[str] = set()

    for entries in results.values():
        for entry in (entries or []):
            for vuln in (entry.get("vulnerabilities") or []):
                vuln_id = vuln.get("id", "")
                if vuln_id in seen:
                    continue
                seen.add(vuln_id)

                max_rank = 0
                max_sev = ""
                for ref in (vuln.get("references") or []):
                    sev = (ref.get("severity") or "").upper()
                    if _SEVERITY_RANK.get(sev, 0) > max_rank:
                        max_rank = _SEVERITY_RANK[sev]
                        max_sev = sev

                key = max_sev.lower()
                if key in counts:
                    counts[key] += 1

    total = sum(counts.values())
    return {**counts, "total": total} if total > 0 else None
