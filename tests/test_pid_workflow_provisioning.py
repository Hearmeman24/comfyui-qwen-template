import json
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class PiDWorkflowProvisioningTest(unittest.TestCase):
    def test_pid_workflow_is_default_qwen_workflow_with_required_models_registered(self):
        workflows = load_json(REPO_ROOT / "src" / "workflows_registry.json")
        models = load_json(REPO_ROOT / "src" / "models_registry.json")
        workflow_text = (REPO_ROOT / "workflows" / "QwenImage_2512_PiD_Workflow.json").read_text(
            encoding="utf-8"
        )

        self.assertIn(
            "QwenImage_2512_PiD_Workflow.json",
            workflows["DOWNLOAD_QWEN_IMAGE"]["workflows"],
        )
        self.assertIs(workflows["DOWNLOAD_QWEN_IMAGE"]["default"], True)

        expected = {
            "gemma_2_2b_it_elm_bf16.safetensors": {
                "url": "https://huggingface.co/Comfy-Org/PixelDiT/resolve/main/text_encoders/gemma_2_2b_it_elm_bf16.safetensors",
                "dest_subdir": "models/text_encoders",
            },
            "model_ema_bf16.pth": {
                "url": "https://huggingface.co/nvidia/PiD/resolve/main/checkpoints/PiD_res2kto4k_sr4x_official_qwenimage_distill_4step/model_ema_bf16.pth",
                "dest_subdir": "models/diffusion_models",
            },
        }

        for basename, registry_entry in expected.items():
            self.assertIn(basename, workflow_text)
            self.assertEqual(models[basename], registry_entry)


if __name__ == "__main__":
    unittest.main()
