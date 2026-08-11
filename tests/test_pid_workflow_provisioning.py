import json
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class PiDWorkflowProvisioningTest(unittest.TestCase):
    def test_pid_workflows_are_registered_with_workflow_specific_model_filenames(self):
        workflows = load_json(REPO_ROOT / "src" / "workflows_registry.json")
        models = load_json(REPO_ROOT / "src" / "models_registry.json")
        qwen_workflow_text = (REPO_ROOT / "workflows" / "QwenImage_2512_Workflow_PiD.json").read_text(
            encoding="utf-8"
        )
        z_workflow_text = (REPO_ROOT / "workflows" / "Z_Image_Workflow_PiD.json").read_text(
            encoding="utf-8"
        )

        self.assertIn(
            "QwenImage_2512_Workflow_PiD.json",
            workflows["DOWNLOAD_QWEN_IMAGE"]["workflows"],
        )
        self.assertIs(workflows["DOWNLOAD_QWEN_IMAGE"]["default"], True)
        self.assertIn("Z_Image_Workflow_PiD.json", workflows["DOWNLOAD_Z_IMAGE"]["workflows"])

        expected = {
            "gemma_2_2b_it_elm_bf16.safetensors": {
                "url": "https://huggingface.co/Comfy-Org/PixelDiT/resolve/main/text_encoders/gemma_2_2b_it_elm_bf16.safetensors",
                "dest_subdir": "models/text_encoders",
            },
            # Upstream deprecated the plain 2kto4k FLUX / Qwen-Image checkpoints and
            # moved them to checkpoints_deprecated/; v1pt5 is the replacement.
            "qwen_image_pid.pth": {
                "url": "https://huggingface.co/nvidia/PiD/resolve/main/checkpoints/PiD_v1pt5_res2kto4k_sr4x_official_qwenimage_distill_4step/model_ema_bf16.pth",
                "dest_subdir": "models/diffusion_models",
            },
            # Z-Image has no PiD checkpoint of its own — it shares FLUX's latent space.
            "z_image_pid.pth": {
                "url": "https://huggingface.co/nvidia/PiD/resolve/main/checkpoints/PiD_v1pt5_res2kto4k_sr4x_official_flux_distill_4step/model_ema_bf16.pth",
                "dest_subdir": "models/diffusion_models",
            },
        }

        for basename, registry_entry in expected.items():
            self.assertEqual(models[basename], registry_entry)

        self.assertIn("gemma_2_2b_it_elm_bf16.safetensors", qwen_workflow_text)
        self.assertIn("gemma_2_2b_it_elm_bf16.safetensors", z_workflow_text)
        self.assertIn("qwen_image_pid.pth", qwen_workflow_text)
        self.assertIn("z_image_pid.pth", z_workflow_text)
        self.assertNotIn("model_ema_bf16.pth", qwen_workflow_text)
        self.assertNotIn("model_ema_bf16.pth", z_workflow_text)


if __name__ == "__main__":
    unittest.main()
