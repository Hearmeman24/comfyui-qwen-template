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


def run_provision(env: dict, tmpdir: Path) -> dict:
    """Run provision_models.main() under a patched env; return the emitted manifest."""
    import provision_models as pm
    importlib.reload(pm)
    manifest = tmpdir / "manifest.json"
    with mock.patch.dict(os.environ, env, clear=False), \
            mock.patch.object(pm, "MANIFEST_PATH", manifest), \
            mock.patch.object(pm, "WORKFLOW_DEST_DIR", tmpdir / "workflows"):
        pm.main()
    return json.loads(manifest.read_text())


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
            "boogu_image_turbo_lora_rank_128_bf16.safetensors",
            "qwen3vl_8b_fp8_scaled.safetensors",
            "flux1_vae_bf16.safetensors",
        ]:
            self.assertIn(name, models)
            self.assertTrue(
                models[name]["url"].startswith("https://huggingface.co/Comfy-Org/Boogu-Image")
            )

    def test_disabled_by_default(self):
        manifest = run_provision({}, self.tmp)
        self.assertFalse(any(k.startswith("boogu_") for k in manifest))

    def test_bf16_selects_bf16_diffusion(self):
        manifest = run_provision({"download_boogu": "true", "BOOGU_PRECISION": "BF16"}, self.tmp)
        self.assertIn("boogu_image_base_bf16.safetensors", manifest)
        self.assertIn("boogu_image_turbo_bf16.safetensors", manifest)
        self.assertNotIn("boogu_image_base_fp8_scaled.safetensors", manifest)
        # shared models are precision-independent and always present
        self.assertIn("flux1_vae_bf16.safetensors", manifest)
        self.assertIn("qwen3vl_8b_fp8_scaled.safetensors", manifest)
        self.assertIn("boogu_image_turbo_lora_rank_128_bf16.safetensors", manifest)

    def test_fp8_selects_fp8_and_edit_falls_back_to_bf16(self):
        manifest = run_provision({"download_boogu": "true", "BOOGU_PRECISION": "FP8"}, self.tmp)
        self.assertIn("boogu_image_base_fp8_scaled.safetensors", manifest)
        self.assertIn("boogu_image_edit_fp8_scaled.safetensors", manifest)
        self.assertIn("boogu_image_turbo_fp8_scaled.safetensors", manifest)
        self.assertNotIn("boogu_image_base_bf16.safetensors", manifest)


if __name__ == "__main__":
    unittest.main()
