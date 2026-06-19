import importlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))


def run_provision(env: dict, tmpdir: Path):
    """Run provision_models.main() under a patched env; return (manifest, workflow_dir)."""
    import provision_models as pm
    importlib.reload(pm)
    manifest = tmpdir / "manifest.json"
    wf_dir = tmpdir / "workflows"
    with mock.patch.dict(os.environ, env, clear=False), \
            mock.patch.object(pm, "MANIFEST_PATH", manifest), \
            mock.patch.object(pm, "WORKFLOW_DEST_DIR", wf_dir):
        pm.main()
    return json.loads(manifest.read_text()), wf_dir


class BooguProvisioningTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def test_registry_has_boogu_entries(self):
        models = json.loads((REPO_ROOT / "src" / "models_registry.json").read_text())
        for name in [
            "boogu_image_base_bf16.safetensors",
            "boogu_image_base_fp8_scaled.safetensors",
            "boogu_image_edit_bf16.safetensors",
            "boogu_image_edit_fp8_scaled.safetensors",
            "boogu_image_turbo_bf16.safetensors",
            "boogu_image_turbo_fp8_scaled.safetensors",
        ]:
            self.assertIn(name, models)
            self.assertTrue(
                models[name]["url"].startswith("https://huggingface.co/Comfy-Org/Boogu-Image")
            )

    def test_flag_registered_with_three_workflows(self):
        wf = json.loads((REPO_ROOT / "src" / "workflows_registry.json").read_text())
        self.assertIn("download_boogu", wf)
        self.assertEqual(wf["download_boogu"]["precision_env"], "BOOGU_PRECISION")
        self.assertEqual(
            sorted(wf["download_boogu"]["workflows"]),
            ["Boogu_Base.json", "Boogu_Edit.json", "Boogu_Turbo.json"],
        )

    def test_disabled_by_default(self):
        manifest, _ = run_provision({}, self.tmp)
        self.assertFalse(any(k.startswith("boogu_image") for k in manifest))

    def test_bf16_keeps_bf16_diffusion(self):
        manifest, _ = run_provision(
            {"download_boogu": "true", "BOOGU_PRECISION": "bf16"}, self.tmp
        )
        self.assertIn("boogu_image_base_bf16.safetensors", manifest)
        self.assertIn("boogu_image_edit_bf16.safetensors", manifest)
        self.assertIn("boogu_image_turbo_bf16.safetensors", manifest)
        self.assertNotIn("boogu_image_base_fp8_scaled.safetensors", manifest)
        # shared models pulled in by the workflows
        self.assertIn("flux1_vae_bf16.safetensors", manifest)
        self.assertIn("qwen3vl_8b_fp8_scaled.safetensors", manifest)

    def test_fp8_swaps_diffusion_in_manifest_and_workflow_json(self):
        manifest, wf_dir = run_provision(
            {"download_boogu": "true", "BOOGU_PRECISION": "fp8"}, self.tmp
        )
        self.assertIn("boogu_image_base_fp8_scaled.safetensors", manifest)
        self.assertIn("boogu_image_edit_fp8_scaled.safetensors", manifest)
        self.assertIn("boogu_image_turbo_fp8_scaled.safetensors", manifest)
        self.assertNotIn("boogu_image_base_bf16.safetensors", manifest)
        # the copied workflow JSON itself must reference the fp8 filename
        turbo = (wf_dir / "Boogu_Turbo.json").read_text()
        self.assertIn("boogu_image_turbo_fp8_scaled.safetensors", turbo)
        self.assertNotIn("boogu_image_turbo_bf16.safetensors", turbo)

    def test_boogu_precision_independent_of_qwen(self):
        # Qwen bf16, Boogu fp8 — Boogu must swap, Qwen must not.
        manifest, _ = run_provision(
            {"download_boogu": "true", "BOOGU_PRECISION": "fp8", "QWEN_IMAGE_PRECISION": "bf16"},
            self.tmp,
        )
        self.assertIn("boogu_image_base_fp8_scaled.safetensors", manifest)
        self.assertIn("qwen_image_2512_bf16.safetensors", manifest)
        self.assertNotIn("qwen_image_2512_fp8_e4m3fn.safetensors", manifest)


if __name__ == "__main__":
    unittest.main()
