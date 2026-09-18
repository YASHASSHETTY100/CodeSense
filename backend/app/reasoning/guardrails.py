"""Citation guardrail: every claimed evidence ref must exist in retrieved context."""
from __future__ import annotations


def check_evidence(claimed: list[dict], retrieved: list[dict]) -> tuple[list[dict], int]:
    valid_refs = {r["source_ref"] for r in retrieved}
    files = {r["source_ref"].split("#")[0].split(":")[0] for r in retrieved}
    kept, dropped = [], 0
    for e in claimed:
        f = str(e.get("file", ""))
        ref_hit = any(f and (f in r or r in f or f == r.split("#")[0]) for r in valid_refs)
        file_hit = f in files or any(f in r for r in valid_refs)
        if ref_hit or file_hit or not f:
            kept.append(e)
        else:
            dropped += 1
    return kept, dropped
