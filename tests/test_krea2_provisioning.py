import json
import tempfile
import unittest
from pathlib import Path

from .test_boogu_provisioning import run_provision

REPO_ROOT = Path(__file__).resolve().parents[1]

RAW = "krea2_raw_bf16.safetensors"
TURBO_LORA = "krea2_turbo_lora_rank_64_bf16.safetensors"


class Krea2ProvisioningTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def test_registry_has_krea2_raw_bf16(self):
        models = json.loads((REPO_ROOT / "src" / "models_registry.json").read_text())
        self.assertIn(RAW, models)
        self.assertEqual(models[RAW]["dest_subdir"], "models/diffusion_models")

    def test_registry_has_krea2_turbo_lora(self):
        models = json.loads((REPO_ROOT / "src" / "models_registry.json").read_text())
        self.assertIn(TURBO_LORA, models)
        self.assertEqual(models[TURBO_LORA]["dest_subdir"], "models/loras")

    def test_krea2_enabled_downloads_raw_bf16(self):
        manifest, _ = run_provision({"download_krea2": "true"}, self.tmp)
        self.assertIn(RAW, manifest)
        self.assertIn(TURBO_LORA, manifest)
        self.assertIn("krea2_turbo_mxfp8.safetensors", manifest)

    def test_krea2_disabled_downloads_nothing_krea2(self):
        manifest, _ = run_provision({"download_krea2": "false"}, self.tmp)
        self.assertNotIn(RAW, manifest)
        self.assertNotIn(TURBO_LORA, manifest)


if __name__ == "__main__":
    unittest.main()
