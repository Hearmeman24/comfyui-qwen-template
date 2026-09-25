#!/usr/bin/env python3
"""Dependency-only opt-in checks; no premium graph or prompt fixtures."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from validate_models import runtime_dir

REPO = Path(__file__).resolve().parents[1]
FLAG = "influencer_maxxing"
MODELS = {
    "krea2_turbo_bf16.safetensors": "diffusion_models",
    "qwen3vl_4b_bf16.safetensors": "text_encoders",
    "qwen3vl_4b_fp8_scaled.safetensors": "text_encoders",
    "qwen3.5_9b_qwen_image_2.1_pe_t2i.int8_convrot.safetensors": "text_encoders",
    "Wan2_1_VAE_fp32.safetensors": "vae",
    "Krea2_TextFusion_Refusal_Reduction.safetensors": "loras",
    "seedvr2_ema_7b_fp16.safetensors": "SEEDVR2",
    "ema_vae_fp16.safetensors": "SEEDVR2",
}
NODE_URLS = {
    "https://github.com/numz/ComfyUI-SeedVR2_VideoUpscaler.git",
    "https://github.com/Jonseed/ComfyUI-Detail-Daemon.git",
}


def main():
    template = json.loads((REPO / "template.json").read_text())
    registry = json.loads((REPO / "src/models_registry.json").read_text())
    cfg = template["flags"][FLAG]
    assert cfg.get("default") is False
    assert not any(cfg.get(key) for key in ("folders", "workflows", "copy")), (
        "The dependency flag must never distribute premium workflows"
    )
    assert set(cfg["extra_models"]) == set(MODELS)
    assert template["models_symlink"] is True, "SeedVR2 must see the persistent model tree"
    assert "SEEDVR2" in template.get("extra_model_paths", [])
    for name, category in MODELS.items():
        assert registry[name]["subdir"] == category, name
    entries = template["custom_nodes"]["flag_repos"][FLAG]
    assert {entry.split("|", 1)[0] for entry in entries} == NODE_URLS
    assert not NODE_URLS.intersection(template["custom_nodes"]["repos"])
    for path in (REPO / "workflows").rglob("*.json"):
        assert "influencermaxxing" not in path.name.lower().replace("-", "").replace("_", "")

    runtime = runtime_dir()
    provisioner = runtime / "src/provisioner.py"
    spec = importlib.util.spec_from_file_location("dependency_provisioner", provisioner)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    env = dict(os.environ)
    for flag in template["flags"]:
        env[flag] = "false"
    for group in template.get("swap_groups", []):
        env.pop(group["env"], None)

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        models_root = root / "models"
        dst = root / "workflows"
        manifest = root / "manifest.tsv"

        def run(overrides):
            selected_env = {**env, **overrides}
            selected_env = {k: v for k, v in selected_env.items() if v is not None}
            proc = subprocess.run([
                sys.executable, str(provisioner),
                "--template", str(REPO / "template.json"),
                "--registry", str(REPO / "src/models_registry.json"),
                "--workflows-src", str(REPO / "workflows"),
                "--workflows-dst", str(dst),
                "--models-root", str(models_root),
                "--manifest", str(manifest),
            ], env=selected_env, capture_output=True, text=True)
            assert proc.returncode == 0, proc.stdout + proc.stderr
            assert "[provisioner] error:" not in proc.stdout, proc.stdout
            rows = [line.split("\t") for line in manifest.read_text().splitlines() if line]
            assert len({row[1] for row in rows}) == len(rows), "Duplicate model destinations"
            nodes = {entry.split("|", 1)[0] for entry in module.select_custom_node_repos(template, selected_env)}
            return {Path(row[1]).relative_to(models_root).as_posix(): row[0] for row in rows}, nodes

        expected = {f"{category}/{name}": registry[name]["url"] for name, category in MODELS.items()}
        for raw in (None, "false", " False ", "0", "no", "", "typo", "true", " TRUE ", "1", "yes", "on"):
            rows, nodes = run({FLAG: raw})
            enabled = raw in ("true", " TRUE ", "1", "yes", "on")
            assert rows == (expected if enabled else {}), (raw, rows)
            assert nodes == (NODE_URLS if enabled else set()), (raw, nodes)
            assert not list(dst.rglob("*.json")), "Dependency-only setup copied a graph"
        print("OK: premium flag truth values gate exactly eight models and two node packs, zero graphs")

        for other in template["flags"]:
            if other == FLAG:
                continue
            baseline, _ = run({other: "true"})
            before = {p.relative_to(dst): p.read_bytes() for p in dst.rglob("*.json")}
            combined, nodes = run({other: "true", FLAG: "true"})
            assert combined == {**baseline, **expected}, other
            assert nodes == NODE_URLS
            assert before == {p.relative_to(dst): p.read_bytes() for p in dst.rglob("*.json")}, other
        print("OK: every existing flag composes without extra graph copies or duplicate downloads")

        all_workflow_flags = {flag: "true" for flag in template["flags"] if flag != FLAG}
        baseline, _ = run(all_workflow_flags)
        before = {p.relative_to(dst): p.read_bytes() for p in dst.rglob("*.json")}
        combined, nodes = run({**all_workflow_flags, FLAG: "true"})
        assert combined == {**baseline, **expected}
        assert nodes == NODE_URLS
        assert before == {p.relative_to(dst): p.read_bytes() for p in dst.rglob("*.json")}

        # Keep user-supplied graphs and cached weights when the opt-in is disabled.
        dst.mkdir(parents=True, exist_ok=True)
        sentinel = dst / "customer-upload.json"
        sentinel.write_text('{"nodes": []}')
        rows, _ = run({FLAG: "true"})
        assert rows == expected
        # Sparse files exercise the provisioner's existing-file skip at real destinations.
        for relative in expected:
            target = models_root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("wb") as handle:
                handle.truncate(11 * 1024 * 1024)
        rows, _ = run({FLAG: "true"})
        assert rows == {}, "Repeated provisioning must reuse existing weights"
        rows, nodes = run({FLAG: "false"})
        assert not rows and not nodes
        assert sentinel.read_text() == '{"nodes": []}'
        assert all((models_root / relative).is_file() for relative in expected)
        print("OK: repeated setup reuses weights; disabling retains customer uploads and cached models")
    return 0


if __name__ == "__main__":
    sys.exit(main())
