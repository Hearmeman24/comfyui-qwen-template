#!/usr/bin/env python3
"""Manifest-driven model downloader (§5 + §6 of the refactor playbook).

Reads /tmp/qwen_manifest.json (produced by provision_models.py) and downloads
each entry to $PERSIST_ROOT/<dest_subdir>/<basename>.

- HF URLs go through huggingface_hub (hf_xet acceleration via HF_XET_HIGH_PERFORMANCE=1)
- Non-HF URLs fall back to aria2c with 16-way parallel connections
- Pool size 3 — RunPod NFS aggregate caps around 150 MB/s, more streams don't help
- Skip-if-on-disk at >= 10 MB (catches corrupted partial downloads)
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urlparse

PERSIST_ROOT = Path(os.environ.get("PERSIST_ROOT", "/workspace/ComfyUI"))
MANIFEST_PATH = Path("/tmp/qwen_manifest.json")
MIN_VALID_BYTES = 10 * 1024 * 1024  # 10 MB
POOL_SIZE = 3


def is_hf_url(url: str) -> bool:
    return urlparse(url).netloc == "huggingface.co"


def parse_hf_url(url: str) -> tuple[str, str, str]:
    """Split a `.../{owner}/{repo}/resolve/{revision}/{path}` URL."""
    parts = urlparse(url).path.lstrip("/").split("/")
    if len(parts) < 5 or parts[2] != "resolve":
        raise ValueError(f"Unrecognized HF URL shape: {url}")
    repo_id = f"{parts[0]}/{parts[1]}"
    revision = parts[3]
    filename = "/".join(parts[4:])
    return repo_id, revision, filename


def already_on_disk(dest: Path) -> bool:
    if not dest.is_file():
        return False
    if dest.stat().st_size < MIN_VALID_BYTES:
        print(f"🗑️  Deleting suspiciously small file: {dest}")
        dest.unlink()
        return False
    return True


def remove_aria_partial(dest: Path) -> None:
    aria_marker = dest.with_suffix(dest.suffix + ".aria2")
    if aria_marker.is_file():
        print(f"🗑️  Cleaning .aria2 partial: {aria_marker}")
        aria_marker.unlink()
        if dest.is_file():
            dest.unlink()


def download_hf(url: str, dest: Path) -> None:
    from huggingface_hub import hf_hub_download

    repo_id, revision, filename = parse_hf_url(url)
    token = os.environ.get("HF_TOKEN") or None
    print(f"📥 [hf]    {dest.name}  ({repo_id} @ {revision})")
    hf_hub_download(
        repo_id=repo_id,
        filename=filename,
        revision=revision,
        local_dir=str(dest.parent),
        token=token,
    )
    # hf_hub_download writes to local_dir/<filename>, but `filename` is the
    # full repo-internal path. Move into place if needed.
    written = dest.parent / filename
    if written != dest and written.is_file():
        dest.parent.mkdir(parents=True, exist_ok=True)
        written.rename(dest)
        # clean any now-empty parent dirs created from the repo path
        for parent in written.parents:
            if parent == dest.parent:
                break
            try:
                parent.rmdir()
            except OSError:
                break


def download_aria(url: str, dest: Path) -> None:
    print(f"📥 [aria2] {dest.name}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "aria2c", "-x", "16", "-s", "16", "-k", "1M",
        "--continue=true", "--summary-interval=0", "--console-log-level=warn",
        "-d", str(dest.parent), "-o", dest.name, url,
    ]
    subprocess.run(cmd, check=True)


def download_one(basename: str, entry: dict) -> tuple[str, bool, str]:
    url = entry["url"]
    dest = PERSIST_ROOT / entry["dest_subdir"] / basename
    dest.parent.mkdir(parents=True, exist_ok=True)

    if already_on_disk(dest):
        size_mb = dest.stat().st_size // (1024 * 1024)
        return basename, True, f"skip ({size_mb}MB on disk)"
    remove_aria_partial(dest)

    try:
        if is_hf_url(url):
            download_hf(url, dest)
        else:
            download_aria(url, dest)
        size_mb = dest.stat().st_size // (1024 * 1024) if dest.is_file() else 0
        return basename, True, f"ok ({size_mb}MB)"
    except Exception as exc:
        return basename, False, f"failed: {exc}"


def main() -> int:
    if not MANIFEST_PATH.is_file():
        print(f"❌ Manifest not found at {MANIFEST_PATH} — did provision_models.py run?")
        return 1

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    if not manifest:
        print("📭 Manifest is empty — nothing to download.")
        return 0

    print(f"⬇️  Downloading {len(manifest)} model(s) with pool size {POOL_SIZE}...")
    print(f"   PERSIST_ROOT = {PERSIST_ROOT}")

    failures = []
    with ThreadPoolExecutor(max_workers=POOL_SIZE) as pool:
        futures = {
            pool.submit(download_one, name, entry): name
            for name, entry in manifest.items()
        }
        for fut in as_completed(futures):
            basename, ok, msg = fut.result()
            sym = "✅" if ok else "❌"
            print(f"{sym} {basename}: {msg}")
            if not ok:
                failures.append(basename)

    if failures:
        print(f"\n❌ {len(failures)} download(s) failed: {', '.join(failures)}")
        return 1
    print("\n✅ All downloads complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
