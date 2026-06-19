#!/usr/bin/env python3
"""Workflow-driven model provisioner (§5 of the refactor playbook).

For each enabled DOWNLOAD_* flag:
  - copy the listed workflow files into the user-visible workflows dir
  - apply precision swaps (bf16 <-> fp8) at copy time
  - scan the (post-swap) workflow content for model basenames
  - resolve via models_registry.json -> manifest of files to download
  - warn (don't fail) on basenames not in the registry (user-supplied)

Output: /tmp/qwen_manifest.json consumed by download_models.py.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"
WORKFLOWS_SRC_DIR = REPO_ROOT / "workflows"

PERSIST_ROOT = Path(os.environ.get("PERSIST_ROOT", "/workspace/ComfyUI"))
WORKFLOW_DEST_DIR = PERSIST_ROOT / "user" / "default" / "workflows"
MANIFEST_PATH = Path("/tmp/qwen_manifest.json")

MODEL_REF_RE = re.compile(r'"([A-Za-z0-9._/-]+\.(?:safetensors|pth|pt|ckpt|gguf|onnx|bin))"')

PRECISION_VARIANTS = {
    "fp8": {
        "qwen_image_2512_bf16.safetensors": "qwen_image_2512_fp8_e4m3fn.safetensors",
        "qwen_image_edit_2511_bf16.safetensors": "qwen_image_edit_2511_fp8mixed.safetensors",
    },
}

# Boogu is a model *category*, not a workflow — it has no workflow JSON to scan, so it
# resolves directly to a fixed model set gated by `download_boogu`. BOOGU_PRECISION picks
# the base/edit/turbo diffusion variant.
BOOGU_DIFFUSION = {
    "bf16": [
        "boogu_image_base_bf16.safetensors",
        "boogu_image_edit_bf16.safetensors",
        "boogu_image_turbo_bf16.safetensors",
    ],
    "fp8": [
        "boogu_image_base_fp8_scaled.safetensors",
        "boogu_image_edit_fp8_scaled.safetensors",
        "boogu_image_turbo_fp8_scaled.safetensors",
    ],
}
BOOGU_SHARED = [
    "boogu_image_turbo_lora_rank_128_bf16.safetensors",
    "qwen3vl_8b_fp8_scaled.safetensors",
    "flux1_vae_bf16.safetensors",
]


def env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def apply_precision_swap(content: str, precision: str) -> str:
    swap_map = PRECISION_VARIANTS.get(precision, {})
    for src, dst in swap_map.items():
        content = content.replace(src, dst)
    return content


def main() -> int:
    models_registry = load_json(SRC_DIR / "models_registry.json")
    workflows_registry = load_json(SRC_DIR / "workflows_registry.json")
    precision = os.environ.get("QWEN_IMAGE_PRECISION", "bf16").strip().lower()
    if precision not in {"bf16", "fp8"}:
        print(f"⚠️  Unknown QWEN_IMAGE_PRECISION={precision!r}; defaulting to bf16")
        precision = "bf16"

    WORKFLOW_DEST_DIR.mkdir(parents=True, exist_ok=True)

    manifest: dict[str, dict] = {}
    user_supplied: set[str] = set()
    enabled_flags: list[str] = []

    for flag, cfg in workflows_registry.items():
        enabled = env_bool(flag, cfg.get("default", False))
        if not enabled:
            print(f"⏭️  {flag}=false — skipping {len(cfg['workflows'])} workflow(s)")
            continue
        enabled_flags.append(flag)
        print(f"✅ {flag}=true — provisioning {len(cfg['workflows'])} workflow(s)")

        for wf_name in cfg["workflows"]:
            src = WORKFLOWS_SRC_DIR / wf_name
            if not src.is_file():
                print(f"❌ {flag}: workflow file missing in repo: {wf_name}")
                continue

            content = src.read_text(encoding="utf-8")
            content = apply_precision_swap(content, precision)

            dest = WORKFLOW_DEST_DIR / wf_name
            dest.write_text(content, encoding="utf-8")

            for basename in set(MODEL_REF_RE.findall(content)):
                if basename in models_registry:
                    entry = models_registry[basename]
                    if entry.get("baked"):
                        continue
                    manifest[basename] = {
                        "url": entry["url"],
                        "dest_subdir": entry["dest_subdir"],
                    }
                else:
                    user_supplied.add(basename)

    if env_bool("download_boogu", False):
        boogu_precision = os.environ.get("BOOGU_PRECISION", "bf16").strip().lower()
        if boogu_precision not in BOOGU_DIFFUSION:
            print(f"⚠️  Unknown BOOGU_PRECISION={boogu_precision!r}; defaulting to bf16")
            boogu_precision = "bf16"
        enabled_flags.append("download_boogu")
        boogu_models = BOOGU_DIFFUSION[boogu_precision] + BOOGU_SHARED
        print(f"✅ download_boogu=true ({boogu_precision}) — adding {len(boogu_models)} Boogu model(s)")
        for basename in boogu_models:
            entry = models_registry[basename]
            manifest[basename] = {"url": entry["url"], "dest_subdir": entry["dest_subdir"]}
    else:
        print("⏭️  download_boogu=false — skipping Boogu models")

    if user_supplied:
        print()
        print("⚠️  The following model basenames are referenced in enabled workflows "
              "but are NOT in the registry. They must be supplied by the user "
              "(e.g. via CIVITAI_LORAS / CIVITAI_CHECKPOINTS) or the workflow will "
              "fail to load:")
        for name in sorted(user_supplied):
            print(f"      - {name}")
        print()

    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"📋 Manifest: {len(manifest)} download(s) -> {MANIFEST_PATH}")
    print(f"📂 Workflows copied to: {WORKFLOW_DEST_DIR}")
    print(f"🏁 Enabled flags: {', '.join(enabled_flags) or '(none)'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
