#!/usr/bin/env python3
"""Self-check: a provisioned pod must be internally consistent, per flag
combination and per precision profile.

Drives the shared runtime's provisioner (comfyui-runtime/src/provisioner.py,
pinned by pins.json) against this repo's REAL template.json,
models_registry.json and workflows/. Unlike minimax (one swap group, one
quant), qwen carries TWO independent swap groups on two independent envs
(QWEN_IMAGE_PRECISION driving DOWNLOAD_QWEN_IMAGE + DOWNLOAD_QWEN_IMAGE_EDIT,
BOOGU_PRECISION driving download_boogu only), so the highest-risk gate here
is that each group's rewrite stays scoped to its own flags and never leaks
into the other's workflows (spec section 4, hazard 1: the fp8 registry
entries are reachable ONLY through the swap, so a manifest built from raw
workflow text would silently never download them).

For every case, the workflows copied to the user's ComfyUI must declare
exactly the model files the download manifest pulled: in the loader widgets
AND in each node's `properties.models`, which is what the ComfyUI frontend's
"Missing Models" dialog reads. A mismatch there tells the customer a file is
missing and offers to download it to their own PC.

This is also the ONLY gate on template.json's `extra_models` key (krea2's
three unreferenced files plus the shared VAE Utils model): the runtime
validator ignores the key and the provisioner only prints an error line at
boot, so a typo there is invisible everywhere else. It is also the gate that
DOWNLOAD_HMFEMME, retired via deprecated_flags, truly enables and queues
nothing.

Run: python3 tools/test_provisioner.py
Stdlib only, no pytest. Needs template.json + pins.json in the repo root.
"""
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from validate_models import runtime_dir  # noqa: E402

# (env value or None for unset) -> expected outcome. Replicates the
# provisioner's resolve rule: exact profile name, else lowercased, else warn
# and fall back to the group's default.
CASES = [None, "bf16", "fp8", "FP8", "not-a-precision"]

PLACEHOLDER = "Your_Character_LoRA_Here.safetensors"

EXPECTED_WORKFLOW_COUNTS = {
    "DOWNLOAD_QWEN_IMAGE": 4,
    "DOWNLOAD_QWEN_IMAGE_EDIT": 3,
    "DOWNLOAD_Z_IMAGE": 3,
    "download_boogu": 3,
    "download_krea2": 2,
}
KREA2_EXTRA_MODELS = [
    "krea2_raw_bf16.safetensors",
    "krea2_turbo_lora_rank_64_bf16.safetensors",
    "krea2_identity_edit_v1_2_r128.safetensors",
]
VAE_UTILS_MODEL = "Wan2.1_VAE_upscale2x_imageonly_real_v1.safetensors"
VAE_UTILS_REPO = "https://github.com/spacepxl/ComfyUI-VAE-Utils.git"


def load_json(path: Path, hint: str) -> dict:
    try:
        return json.loads(path.read_text())
    except OSError as e:
        raise SystemExit(f"FATAL: cannot read {path.name} ({hint}): {e}")
    except ValueError as e:
        raise SystemExit(f"FATAL: {path.name} is not valid JSON: {e}")


def expected_profile(group: dict, raw) -> str:
    if raw is None:
        return group["default"]
    if raw in group["profiles"]:
        return raw
    low = raw.strip().lower()
    if low in group["profiles"]:
        return low
    return group["default"]


def declared(workflow_dir: Path, managed: set, registry: dict) -> set:
    """Every managed (swap-group-controlled) basename the copied workflows
    claim to load, from widgets and properties.models, top level and
    subgraphs."""
    names = set()
    for wf in workflow_dir.rglob("*.json"):
        doc = json.loads(wf.read_text())
        groups = [doc.get("nodes", [])] + [
            sg.get("nodes", [])
            for sg in doc.get("definitions", {}).get("subgraphs", [])
        ]
        for group in groups:
            for n in group:
                for v in n.get("widgets_values") or []:
                    if isinstance(v, str) and v in managed:
                        names.add(v)
                for m in (n.get("properties") or {}).get("models") or []:
                    if m.get("name") in managed:
                        names.add(m["name"])
                        assert m.get("url") == registry[m["name"]]["url"], (
                            f"{wf.name}: {m['name']} declares url "
                            f"{m.get('url')}, registry says "
                            f"{registry[m['name']]['url']}"
                        )
    return names


def run_provisioner(template_path: Path, registry_path: Path, env: dict,
                     dst: Path, manifest: Path, models_root: Path):
    proc = subprocess.run(
        [sys.executable, str(PROVISIONER),
         "--template", str(template_path),
         "--registry", str(registry_path),
         "--workflows-src", str(REPO / "workflows"),
         "--workflows-dst", str(dst),
         "--models-root", str(models_root),
         "--manifest", str(manifest)],
        env=env, capture_output=True, text=True,
    )
    return proc


def base_env(**overrides) -> dict:
    env = dict(os.environ)
    for f in EXPECTED_WORKFLOW_COUNTS:
        env.pop(f, None)
    env.pop("QWEN_IMAGE_PRECISION", None)
    env.pop("BOOGU_PRECISION", None)
    env.pop("DOWNLOAD_HMFEMME", None)
    env.update(overrides)
    return env


def main() -> int:
    global PROVISIONER
    template = load_json(REPO / "template.json",
                         "written by the migration's config slice; this test "
                         "only goes green once the slices are integrated")
    registry = load_json(REPO / "src" / "models_registry.json", "registry")

    groups = template.get("swap_groups") or []
    assert len(groups) == 2, f"expected exactly two swap groups, got {len(groups)}"
    by_env = {g["env"]: g for g in groups}
    assert set(by_env) == {"QWEN_IMAGE_PRECISION", "BOOGU_PRECISION"}, by_env
    qwen_group = by_env["QWEN_IMAGE_PRECISION"]
    boogu_group = by_env["BOOGU_PRECISION"]
    assert set(qwen_group["flags"]) == {"DOWNLOAD_QWEN_IMAGE"}, qwen_group
    assert boogu_group["flags"] == ["download_boogu"], boogu_group
    for g in groups:
        assert g["default"] == "bf16", g

    all_managed = {f for g in groups for p in g["profiles"].values() for f in p.values()}
    qwen_managed = {f for p in qwen_group["profiles"].values() for f in p.values()}
    boogu_managed = {f for p in boogu_group["profiles"].values() for f in p.values()}
    assert qwen_managed.isdisjoint(boogu_managed), "the two swap groups must not share a filename"
    for name in all_managed:
        assert name in registry, f"swap profile file missing from registry: {name}"
    print(f"✅ two independent swap groups, {len(all_managed)} managed files total, no overlap")

    assert "DOWNLOAD_HMFEMME" in (template.get("deprecated_flags") or {}), \
        "DOWNLOAD_HMFEMME must be retired via deprecated_flags, not deleted"
    assert template["custom_nodes"]["repos"] == [VAE_UTILS_REPO], (
        "VAE Utils must be cloned at boot from its upstream repository"
    )
    assert registry[VAE_UTILS_MODEL] == {
        "url": (
            "https://huggingface.co/spacepxl/Wan2.1-VAE-upscale2x/resolve/main/"
            "Wan2.1_VAE_upscale2x_imageonly_real_v1.safetensors"
        ),
        "subdir": "vae",
    }, "VAE Utils model must land in ComfyUI's native models/vae directory"
    for flag, count in EXPECTED_WORKFLOW_COUNTS.items():
        assert flag in template["flags"], f"missing flag: {flag}"
        # Flags carry "folders" since the per-model regrouping; the invariant
        # worth holding is still the WORKFLOW count, so count the files under
        # them rather than the folders (every flag has exactly one folder, so
        # comparing folder counts would assert 4 == 1).
        shipped = [w for d in template["flags"][flag]["folders"]
                   for w in (REPO / "workflows" / d).rglob("*.json")]
        assert len(shipped) == count, (
            f"{flag}: expected {count} workflows, got {len(shipped)} "
            f"under {template['flags'][flag]['folders']}"
        )
        extras = set(template["flags"][flag].get("extra_models") or [])
        expected_extras = {VAE_UTILS_MODEL}
        if flag == "download_krea2":
            expected_extras.update(KREA2_EXTRA_MODELS)
        assert extras == expected_extras, (
            f"{flag}: expected extra_models {sorted(expected_extras)}, got {sorted(extras)}"
        )
    print(f"✅ flag map matches expected shape "
          f"({sum(EXPECTED_WORKFLOW_COUNTS.values())} workflows across "
          f"{len(EXPECTED_WORKFLOW_COUNTS)} live flags, 1 shared utility model, "
          "1 deprecated)")

    runtime = runtime_dir()
    PROVISIONER = runtime / "src" / "provisioner.py"
    assert PROVISIONER.is_file(), f"no provisioner at {PROVISIONER}"

    manifests: dict = {}
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)

        # --- Precision profiles: QWEN_IMAGE_PRECISION, boogu off ---
        for raw in CASES:
            key = expected_profile(qwen_group, raw)
            label = "unset" if raw is None else raw
            slug = re.sub(r"[^A-Za-z0-9]", "_", f"qwen-{label}")
            dst = tmp / f"wf-{slug}"
            manifest = tmp / f"manifest-{slug}.tsv"
            env = base_env(DOWNLOAD_QWEN_IMAGE="true", DOWNLOAD_QWEN_IMAGE_EDIT="true")
            if raw is not None:
                env["QWEN_IMAGE_PRECISION"] = raw
            proc = run_provisioner(REPO / "template.json", REPO / "src" / "models_registry.json",
                                   env, dst, manifest, tmp / f"models-{slug}")
            assert proc.returncode == 0, (
                f"qwen/{label}: provisioner exited {proc.returncode}\n{proc.stdout}\n{proc.stderr}"
            )
            lines = [l for l in manifest.read_text().splitlines() if l]
            downloaded = {l.split("\t")[1].rsplit("/", 1)[1] for l in lines}
            manifests[f"qwen-{label}"] = {l.split("\t", 1)[0] for l in lines}

            wanted = set(qwen_group["profiles"][key].values())
            got = declared(dst, all_managed, registry)
            assert got == wanted, (
                f"qwen/{label}: workflows declare {sorted(got)}, "
                f"selected profile {key!r} is {sorted(wanted)}"
            )
            assert wanted <= downloaded, (
                f"qwen/{label}: profile files missing from manifest: {sorted(wanted - downloaded)}"
            )
            assert PLACEHOLDER not in downloaded, (
                f"qwen/{label}: the scrubbed LoRA placeholder must never be queued for download"
            )
            if raw is not None and key != raw and key != raw.strip().lower():
                assert "warning: unknown" in proc.stdout, (
                    f"qwen/{label}: expected an unknown-precision warning, got:\n{proc.stdout}"
                )
            print(f"✅ QWEN_IMAGE_PRECISION={label} -> {key}: workflows and manifest agree on "
                  f"{len(wanted)} files, boogu untouched")

        # --- Precision profiles: BOOGU_PRECISION, independent of qwen ---
        for raw in CASES:
            key = expected_profile(boogu_group, raw)
            label = "unset" if raw is None else raw
            slug = re.sub(r"[^A-Za-z0-9]", "_", f"boogu-{label}")
            dst = tmp / f"wf-{slug}"
            manifest = tmp / f"manifest-{slug}.tsv"
            # Qwen family pinned to bf16 throughout, to prove the two groups
            # never cross-swap each other's files. DOWNLOAD_QWEN_IMAGE must be
            # ON for that to mean anything: a swap group is gated on its flags
            # (provisioner.py:142), so with qwen off there is no qwen file in
            # the manifest to cross-swap and the assertion below is vacuous.
            env = base_env(download_boogu="true", DOWNLOAD_QWEN_IMAGE="true",
                           QWEN_IMAGE_PRECISION="bf16")
            if raw is not None:
                env["BOOGU_PRECISION"] = raw
            proc = run_provisioner(REPO / "template.json", REPO / "src" / "models_registry.json",
                                   env, dst, manifest, tmp / f"models-{slug}")
            assert proc.returncode == 0, (
                f"boogu/{label}: provisioner exited {proc.returncode}\n{proc.stdout}\n{proc.stderr}"
            )
            lines = [l for l in manifest.read_text().splitlines() if l]
            downloaded = {l.split("\t")[1].rsplit("/", 1)[1] for l in lines}
            manifests[f"boogu-{label}"] = {l.split("\t", 1)[0] for l in lines}

            wanted = set(boogu_group["profiles"][key].values())
            got = declared(dst, boogu_managed, registry)
            assert got == wanted, (
                f"boogu/{label}: workflows declare {sorted(got)}, "
                f"selected profile {key!r} is {sorted(wanted)}"
            )
            assert wanted <= downloaded, (
                f"boogu/{label}: profile files missing from manifest: {sorted(wanted - downloaded)}"
            )
            assert "qwen_image_2512_bf16.safetensors" in downloaded, (
                f"boogu/{label}: qwen family must stay bf16 regardless of BOOGU_PRECISION"
            )
            print(f"✅ BOOGU_PRECISION={label} -> {key}: workflows and manifest agree on "
                  f"{len(wanted)} files, qwen family untouched")

        assert manifests["qwen-not-a-precision"] == manifests["qwen-bf16"] == manifests["qwen-unset"], (
            "qwen: unset / bf16 / garbage must queue the same URLs"
        )
        assert manifests["boogu-not-a-precision"] == manifests["boogu-bf16"] == manifests["boogu-unset"], (
            "boogu: unset / bf16 / garbage must queue the same URLs"
        )
        print("✅ all precision profiles consistent; garbage falls back to bf16 in both groups")

        # --- DOWNLOAD_HMFEMME: retired, must enable and queue nothing ---
        dst = tmp / "wf-hmfemme"
        manifest = tmp / "manifest-hmfemme.tsv"
        env = base_env(DOWNLOAD_QWEN_IMAGE="true", DOWNLOAD_QWEN_IMAGE_EDIT="true",
                       DOWNLOAD_HMFEMME="true")
        proc = run_provisioner(REPO / "template.json", REPO / "src" / "models_registry.json",
                               env, dst, manifest, tmp / "models-hmfemme")
        assert proc.returncode == 0, f"HMFemme case: exited {proc.returncode}\n{proc.stdout}"
        assert "RETIRED" in proc.stdout, f"expected a RETIRED announcement, got:\n{proc.stdout}"
        assert not list(dst.rglob("HMFemme*")), "DOWNLOAD_HMFEMME must copy no workflow"
        default_files = {p.name for p in (tmp / "wf-qwen_unset").rglob("*.json")}
        hmfemme_files = {p.name for p in dst.rglob("*.json")}
        assert hmfemme_files == default_files, (
            "a retired flag must not change what the live flags already copy: "
            f"{hmfemme_files.symmetric_difference(default_files)}"
        )
        print("✅ DOWNLOAD_HMFEMME=true: announced RETIRED, enables and queues nothing")

        # --- Flag combinations: workflow + manifest counts ---
        # Turn every live flag off explicitly for singleton cases so a future
        # default change cannot leak another family's workflows or models into
        # the case under test.
        defaults_off = {flag: "false" for flag in EXPECTED_WORKFLOW_COUNTS}
        combos = {
            "none": dict(defaults_off),
            "default": {},  # every flag is now default:false (README:15), so this
                            # is the same as "none": an unset pod boots empty
            "all": {f: "true" for f in EXPECTED_WORKFLOW_COUNTS},
        }
        for flag in EXPECTED_WORKFLOW_COUNTS:
            combos[f"{flag}_only"] = {**defaults_off, flag: "true"}

        for combo_name, flags in combos.items():
            slug = re.sub(r"[^A-Za-z0-9]", "_", combo_name)
            dst = tmp / f"wf-combo-{slug}"
            manifest = tmp / f"manifest-combo-{slug}.tsv"
            env = base_env(**flags)
            proc = run_provisioner(REPO / "template.json", REPO / "src" / "models_registry.json",
                                   env, dst, manifest, tmp / f"models-combo-{slug}")
            assert proc.returncode == 0, f"{combo_name}: exited {proc.returncode}\n{proc.stdout}"
            wf_count = len(list(dst.rglob("*.json"))) if dst.exists() else 0
            lines = [l for l in manifest.read_text().splitlines() if l] if manifest.exists() else []
            print(f"✅ flag combo {combo_name!r}: {wf_count} workflow(s) copied, "
                  f"{len(lines)} model(s) queued")
            if combo_name == "none":
                assert wf_count == 0 and len(lines) == 0, (combo_name, wf_count, len(lines))
            elif combo_name == "default":
                assert wf_count == 0 and len(lines) == 0, (combo_name, wf_count, len(lines))
            elif combo_name == "all":
                assert wf_count == 15, (combo_name, wf_count)
            elif combo_name.endswith("_only"):
                flag = combo_name.removesuffix("_only")
                assert wf_count == EXPECTED_WORKFLOW_COUNTS[flag], (
                    combo_name, wf_count
                )
                downloaded = {l.split("\t")[1].rsplit("/", 1)[1] for l in lines}
                assert VAE_UTILS_MODEL in downloaded, (
                    f"{flag}: shared VAE Utils model missing from manifest"
                )
                if flag == "download_krea2":
                    missing = set(KREA2_EXTRA_MODELS) - downloaded
                    assert not missing, (
                        "krea2 extra_models missing from manifest: "
                        f"{sorted(missing)}"
                    )

    print("✅ every flag combination produces the expected workflow/manifest counts")
    return 0


if __name__ == "__main__":
    sys.exit(main())
