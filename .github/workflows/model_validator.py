#!/usr/bin/env python3
"""Validate workflow JSONs against models_registry.json.

- WARN: workflow references a basename not in the registry (user-supplied / external).
- FAIL: registry URL doesn't return 200/302 on HEAD.
- FAIL: workflow JSON isn't valid JSON.
- FAIL: workflows_registry.json references a workflow file that doesn't exist.
"""
from __future__ import annotations

import json
import re
import sys
import urllib.request
from pathlib import Path
from urllib.error import HTTPError, URLError

REPO = Path(__file__).resolve().parent.parent.parent
SRC = REPO / "src"
WORKFLOWS = REPO / "workflows"

MODEL_REF_RE = re.compile(r'"([A-Za-z0-9._/-]+\.(?:safetensors|pth|pt|ckpt|gguf|onnx|bin))"')


def head_ok(url: str) -> tuple[bool, str]:
    req = urllib.request.Request(url, method="HEAD")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return 200 <= resp.status < 400, f"HTTP {resp.status}"
    except HTTPError as e:
        if e.code in (301, 302, 303, 307, 308):
            return True, f"HTTP {e.code}"
        return False, f"HTTP {e.code}"
    except URLError as e:
        return False, f"URLError: {e.reason}"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def main() -> int:
    errors: list[str] = []
    warnings: list[str] = []

    models = json.loads((SRC / "models_registry.json").read_text())
    workflows_reg = json.loads((SRC / "workflows_registry.json").read_text())

    referenced_workflows: set[str] = set()
    for flag, cfg in workflows_reg.items():
        for wf in cfg["workflows"]:
            referenced_workflows.add(wf)
            if not (WORKFLOWS / wf).is_file():
                errors.append(f"workflows_registry.json: flag {flag} references missing workflow {wf}")

    for wf_path in sorted(WORKFLOWS.glob("*.json")):
        if wf_path.name not in referenced_workflows:
            warnings.append(f"orphan workflow (not in any flag): {wf_path.name}")
        try:
            content = wf_path.read_text(encoding="utf-8")
            json.loads(content)
        except json.JSONDecodeError as e:
            errors.append(f"{wf_path.name}: invalid JSON: {e}")
            continue
        for basename in sorted(set(MODEL_REF_RE.findall(content))):
            if basename in models:
                continue
            warnings.append(f"{wf_path.name}: user-supplied (not in registry): {basename}")

    print("Validating registry URLs (HEAD)...")
    for name, entry in models.items():
        if entry.get("baked"):
            continue
        ok, info = head_ok(entry["url"])
        status = "OK" if ok else "FAIL"
        print(f"  [{status}] {name}: {info}")
        if not ok:
            errors.append(f"{name}: {entry['url']} -> {info}")

    if warnings:
        print("\nWARNINGS:")
        for w in warnings:
            print(f"  - {w}")
    if errors:
        print("\nERRORS:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("\n✅ Model validator passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
