#!/usr/bin/env python3
"""Manifest-driven model downloader (§5 + §6 of the refactor playbook).

Reads /tmp/qwen_manifest.json (produced by provision_models.py) and downloads
each entry to $PERSIST_ROOT/<dest_subdir>/<basename>.

- HF URLs go through huggingface_hub (hf_xet acceleration via HF_XET_HIGH_PERFORMANCE=1)
- Non-HF URLs fall back to aria2c with 16-way parallel connections
- Pool size 3 — RunPod NFS aggregate caps around 150 MB/s, more streams don't help
- Skip-if-on-disk at >= 10 MB (catches corrupted partial downloads)
- Per-download progress watcher polls the staging dir every PROGRESS_INTERVAL seconds
  and prints a line so non-TTY logs (nohup) show forward motion.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urlparse

PERSIST_ROOT = Path(os.environ.get("PERSIST_ROOT", "/workspace/ComfyUI"))
MANIFEST_PATH = Path("/tmp/qwen_manifest.json")
STAGING_ROOT = Path("/tmp/qwen_dl")
MIN_VALID_BYTES = 10 * 1024 * 1024  # 10 MB
POOL_SIZE = 3
PROGRESS_INTERVAL = 20  # seconds


def log(msg: str) -> None:
    print(msg, flush=True)


def is_hf_url(url: str) -> bool:
    return urlparse(url).netloc == "huggingface.co"


def parse_hf_url(url: str) -> tuple[str, str, str]:
    """Split `.../{owner}/{repo}/resolve/{revision}/{path}` into (repo_id, revision, filename)."""
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
        log(f"🗑️  Deleting suspiciously small file: {dest}")
        dest.unlink()
        return False
    return True


def dir_size(path: Path) -> int:
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


def progress_watcher(basename: str, staging: Path, stop_event: threading.Event) -> None:
    start = time.monotonic()
    last_size = 0
    while not stop_event.wait(PROGRESS_INTERVAL):
        if not staging.exists():
            continue
        size = dir_size(staging)
        if size == last_size:
            continue
        mb = size / (1024 * 1024)
        rate = (size - last_size) / PROGRESS_INTERVAL / (1024 * 1024)
        elapsed = int(time.monotonic() - start)
        log(f"⏳ {basename}: {mb:.0f} MB downloaded ({rate:.1f} MB/s, {elapsed}s elapsed)")
        last_size = size


def download_hf(url: str, staging: Path, final_dest: Path) -> None:
    from huggingface_hub import hf_hub_download

    repo_id, revision, filename = parse_hf_url(url)
    token = os.environ.get("HF_TOKEN") or None
    log(f"📥 [hf]    {final_dest.name}  ({repo_id} @ {revision})")
    hf_hub_download(
        repo_id=repo_id,
        filename=filename,
        revision=revision,
        local_dir=str(staging),
        token=token,
    )
    downloaded = staging / filename
    if not downloaded.is_file():
        raise RuntimeError(f"hf_hub_download claimed success but no file at {downloaded}")
    final_dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(downloaded), str(final_dest))


def download_aria(url: str, staging: Path, final_dest: Path) -> None:
    log(f"📥 [aria2] {final_dest.name}")
    cmd = [
        "aria2c", "-x", "16", "-s", "16", "-k", "1M",
        "--continue=true", "--summary-interval=0", "--console-log-level=warn",
        "-d", str(staging), "-o", final_dest.name, url,
    ]
    subprocess.run(cmd, check=True)
    final_dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(staging / final_dest.name), str(final_dest))


def download_one(basename: str, entry: dict) -> tuple[str, bool, str]:
    url = entry["url"]
    final_dest = PERSIST_ROOT / entry["dest_subdir"] / basename
    final_dest.parent.mkdir(parents=True, exist_ok=True)

    if already_on_disk(final_dest):
        size_mb = final_dest.stat().st_size // (1024 * 1024)
        return basename, True, f"skip ({size_mb} MB on disk)"

    # Each download gets its own staging dir so the watcher can poll cleanly.
    staging = STAGING_ROOT / basename
    if staging.exists():
        shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True, exist_ok=True)

    stop_event = threading.Event()
    watcher = threading.Thread(
        target=progress_watcher,
        args=(basename, staging, stop_event),
        daemon=True,
    )
    watcher.start()

    try:
        start = time.monotonic()
        if is_hf_url(url):
            download_hf(url, staging, final_dest)
        else:
            download_aria(url, staging, final_dest)
        elapsed = time.monotonic() - start
        size_mb = final_dest.stat().st_size // (1024 * 1024) if final_dest.is_file() else 0
        return basename, True, f"ok ({size_mb} MB in {elapsed:.0f}s)"
    except Exception as exc:
        return basename, False, f"failed: {exc}"
    finally:
        stop_event.set()
        watcher.join(timeout=2)
        shutil.rmtree(staging, ignore_errors=True)


def main() -> int:
    if not MANIFEST_PATH.is_file():
        log(f"❌ Manifest not found at {MANIFEST_PATH} — did provision_models.py run?")
        return 1

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    if not manifest:
        log("📭 Manifest is empty — nothing to download.")
        return 0

    STAGING_ROOT.mkdir(parents=True, exist_ok=True)
    log(f"⬇️  Downloading {len(manifest)} model(s) with pool size {POOL_SIZE}...")
    log(f"   PERSIST_ROOT = {PERSIST_ROOT}")
    log(f"   Progress lines emitted every {PROGRESS_INTERVAL}s per in-flight download.")
    if not os.environ.get("HF_TOKEN"):
        log("   ⚠️  HF_TOKEN unset — downloads may be rate-limited. Set it on the template.")

    failures = []
    with ThreadPoolExecutor(max_workers=POOL_SIZE) as pool:
        futures = {
            pool.submit(download_one, name, entry): name
            for name, entry in manifest.items()
        }
        for fut in as_completed(futures):
            basename, ok, msg = fut.result()
            sym = "✅" if ok else "❌"
            log(f"{sym} {basename}: {msg}")
            if not ok:
                failures.append(basename)

    if failures:
        log(f"\n❌ {len(failures)} download(s) failed: {', '.join(failures)}")
        return 1
    log("\n✅ All downloads complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
