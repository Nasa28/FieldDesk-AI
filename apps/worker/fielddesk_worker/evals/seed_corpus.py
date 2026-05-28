"""Upload the Phase 4c golden corpus to a tenant via the documents API.

The 5 documents under infra/seed_corpus/ map 1:1 to the titles in
golden.SEED_DOCUMENT_TITLES — the rag eval scores recall against those
titles. Run this once after seeding the tenant, then wait a few seconds
for the embed jobs to finish before running the eval.

Usage:
    python -m fielddesk_worker.evals.seed_corpus \\
        --tenant <uuid> \\
        --api-url http://localhost:8080 \\
        [--corpus-dir infra/seed_corpus]

Why this lives in the worker package: it leans on httpx (already a worker
dep) and the SEED_DOCUMENT_TITLES list of canonical titles, so colocating
keeps the source of truth in one place. A bash + curl version would
duplicate the title→filename mapping.
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

import httpx

from fielddesk_worker.evals.golden import SEED_DOCUMENT_TITLES


# Filename → expected document title. The repository root contains
# infra/seed_corpus/01_*.md … 05_*.md; the order matches the title list so
# the bookkeeping is dead-obvious.
CORPUS_FILES: list[str] = [
    "01_hydraulic_pump_7000.md",
    "02_tankless_water_heater.md",
    "03_confined_space_entry.md",
    "04_warranty_policy.md",
    "05_plumbing_parts_catalog.md",
]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="fielddesk_worker.evals.seed_corpus")
    parser.add_argument("--tenant", required=True, help="Tenant UUID")
    parser.add_argument(
        "--api-url",
        default="http://localhost:8080",
        help="API base URL (default: http://localhost:8080)",
    )
    parser.add_argument(
        "--corpus-dir",
        default=None,
        help="Path to the markdown corpus directory. Defaults to "
             "<repo>/infra/seed_corpus relative to this file.",
    )
    parser.add_argument(
        "--wait-seconds",
        type=int,
        default=0,
        help="If > 0, poll until every uploaded doc reaches status='ready' "
             "(or fail). Pair with --wait-seconds 60 in CI.",
    )
    args = parser.parse_args(argv)

    corpus_dir = (
        Path(args.corpus_dir)
        if args.corpus_dir
        else _default_corpus_dir()
    )
    if not corpus_dir.is_dir():
        print(f"corpus dir not found: {corpus_dir}", file=sys.stderr)
        return 64
    if len(CORPUS_FILES) != len(SEED_DOCUMENT_TITLES):
        print(
            f"CORPUS_FILES ({len(CORPUS_FILES)}) and SEED_DOCUMENT_TITLES "
            f"({len(SEED_DOCUMENT_TITLES)}) must stay 1:1",
            file=sys.stderr,
        )
        return 70

    base = args.api_url.rstrip("/")
    headers = {"X-Tenant-ID": args.tenant}
    uploaded_ids: list[str] = []

    with httpx.Client(timeout=30.0, headers=headers) as client:
        for filename, title in zip(CORPUS_FILES, SEED_DOCUMENT_TITLES):
            path = corpus_dir / filename
            if not path.is_file():
                print(f"missing seed file: {path}", file=sys.stderr)
                return 66
            doc_id = _upload_one(client, base, path, title)
            uploaded_ids.append(doc_id)
            print(f"  uploaded: {title} ({doc_id})")

    print(f"\nUploaded {len(uploaded_ids)} documents to tenant {args.tenant}.")

    if args.wait_seconds > 0:
        return _wait_for_ready(args.api_url, args.tenant, uploaded_ids, args.wait_seconds)
    print("Embed jobs are queued; wait ~10-30s before running the eval.")
    return 0


def _default_corpus_dir() -> Path:
    """Repo-relative default. This file lives at
    apps/worker/fielddesk_worker/evals/seed_corpus.py; parents[4] is the
    repo root, then infra/seed_corpus."""
    return Path(__file__).resolve().parents[4] / "infra" / "seed_corpus"


def _upload_one(client: httpx.Client, base: str, path: Path, title: str) -> str:
    """Run the three-step upload handshake for one markdown file:
    POST /v1/documents → POST /upload-url → PUT to MinIO → POST /uploaded.
    Returns the document id on success; raises on any non-2xx."""
    body = path.read_bytes()
    filename = _safe_filename(path.name)
    create_payload = {
        "title": title,
        "filename": filename,
        "mime_type": "text/markdown",
        "size_bytes": len(body),
    }
    r = client.post(f"{base}/v1/documents", json=create_payload)
    r.raise_for_status()
    doc = r.json()
    doc_id = doc["id"]

    r = client.post(f"{base}/v1/documents/{doc_id}/upload-url")
    r.raise_for_status()
    upload_url = r.json()["upload_url"]

    put = httpx.put(
        upload_url,
        content=body,
        headers={"Content-Type": "text/markdown"},
        timeout=60.0,
    )
    if put.status_code >= 300:
        raise RuntimeError(
            f"PUT to presigned URL failed: {put.status_code} {put.text[:200]}"
        )

    r = client.post(f"{base}/v1/documents/{doc_id}/uploaded")
    r.raise_for_status()
    return doc_id


_FILENAME_SAFE = re.compile(r"[^A-Za-z0-9_.\-]")


def _safe_filename(name: str) -> str:
    # The Go upload handler already sanitizes; keep the input conservative
    # so the object key on MinIO matches what we pass.
    return _FILENAME_SAFE.sub("_", name)


def _wait_for_ready(api_url: str, tenant: str, doc_ids: list[str], seconds: int) -> int:
    """Poll GET /v1/documents/{id} until every id is ready or failed.
    Returns 0 if all ready, 1 if any failed, 2 if the timeout fires before
    every doc finishes. Useful in CI so the eval doesn't race the embed
    jobs."""
    base = api_url.rstrip("/")
    headers = {"X-Tenant-ID": tenant}
    deadline = time.time() + seconds
    pending = set(doc_ids)
    failed: list[tuple[str, str]] = []

    with httpx.Client(timeout=10.0, headers=headers) as client:
        while pending and time.time() < deadline:
            for doc_id in list(pending):
                r = client.get(f"{base}/v1/documents/{doc_id}")
                if r.status_code != 200:
                    continue
                d = r.json()
                if d.get("status") == "ready":
                    pending.discard(doc_id)
                elif d.get("status") == "failed":
                    pending.discard(doc_id)
                    failed.append((doc_id, d.get("parse_error") or ""))
            if pending:
                time.sleep(2.0)

    if failed:
        for doc_id, err in failed:
            print(f"  FAILED: {doc_id} — {err}", file=sys.stderr)
        return 1
    if pending:
        print(
            f"  TIMEOUT: {len(pending)} docs still embedding after {seconds}s",
            file=sys.stderr,
        )
        return 2
    print("All documents ready.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
