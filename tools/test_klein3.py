"""Offline auth failure, hook continuation and provisioning regression checks."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import urllib.error
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("klein3", ROOT / "src/klein3_preflight.py")
preflight = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preflight)


class FakeHF:
    def __init__(self, fail_at=None, code=401, network=False):
        self.requests = []
        self.fail_at, self.code, self.network = fail_at, code, network

    def open(self, request, timeout):
        self.requests.append(request)
        assert timeout == 10
        if len(self.requests) == self.fail_at:
            if self.network:
                raise urllib.error.URLError("sensitive response must not be logged")
            raise urllib.error.HTTPError(request.full_url, self.code, "secret", {}, None)
        return contextlib.closing(io.StringIO('{"name":"test-user"}'))


class KleinTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.comfy = Path(self.tmp.name)
        support = self.comfy / "comfy/ldm/flux3/model.py"
        support.parent.mkdir(parents=True)
        support.touch()
        self.env = {"HF_TOKEN": "hf_test_secret", "COMFYUI_DIR": str(self.comfy)}

    def test_missing_and_malformed_make_no_requests(self):
        for token in ("", "   ", "hf_bad\nheader", "hf_bad token", "hf_\u2603"):
            hf = FakeHF()
            self.assertIsNotNone(preflight.check(ROOT, {**self.env, "HF_TOKEN": token}, hf))
            self.assertEqual(hf.requests, [])

    def test_success_checks_identity_and_all_required_files(self):
        hf = FakeHF()
        self.assertIsNone(preflight.check(ROOT, self.env, hf))
        self.assertEqual([r.method for r in hf.requests], ["GET"] + ["HEAD"] * 4)
        self.assertTrue(all(r.get_header("Authorization") == "Bearer hf_test_secret" for r in hf.requests))
        registry = json.loads((ROOT / "src/models_registry.json").read_text())
        cfg = json.loads((ROOT / "template.json").read_text())["flags"]["DOWNLOAD_KLEIN3"]
        self.assertEqual({r.full_url for r in hf.requests[1:]}, {registry[n]["url"] for n in cfg["extra_models"]})

    def test_failures_are_specific_and_stop_before_remaining_probes(self):
        cases = [(1, 401, "invalid or expired"), (1, 403, "Access denied"),
                 (2, 401, "Access denied"), (3, 403, "Accept the model license"),
                 (4, 429, "HTTP 429"), (5, 404, "HTTP 404"), (2, 503, "HTTP 503")]
        for position, code, message in cases:
            with self.subTest(position=position, code=code):
                hf = FakeHF(position, code)
                error = preflight.check(ROOT, self.env, hf)
                self.assertIn(message, error)
                self.assertNotIn(self.env["HF_TOKEN"], error)
                self.assertEqual(len(hf.requests), position)

    def test_network_failure_is_not_reported_as_invalid_token(self):
        error = preflight.check(ROOT, self.env, FakeHF(1, network=True))
        self.assertIn("network/TLS", error)
        self.assertNotIn("secret", error)

    def test_head_redirect_confirms_access_without_following_cdn(self):
        self.assertIsNone(preflight.check(ROOT, self.env, FakeHF(2, 302)))
        self.assertIsNone(preflight.NoRedirect().redirect_request(None, None, 302, "", {}, "https://cdn.example"))

    def test_old_comfy_skips_model(self):
        (self.comfy / "comfy/ldm/flux3/model.py").unlink()
        self.assertIn("lacks FLUX.3", preflight.check(ROOT, self.env, FakeHF()))

    def test_unexpected_error_is_sanitized(self):
        output = io.StringIO()
        with patch.object(preflight, "check", side_effect=RuntimeError("hf_test_secret")), contextlib.redirect_stdout(output):
            self.assertEqual(preflight.main(), 1)
        self.assertNotIn("hf_test_secret", output.getvalue())

    def test_hook_continues_and_disables_only_klein(self):
        # A helper failure (including a broken/missing Python helper) must not abort boot.
        script = '''
set -eu
python3() { return 1; }
report_off() { echo "REPORT: $1"; }
source "$TEMPLATE_DIR/src/hooks/pre_download.sh"
printf 'CONTINUED:%s:%s' "$DOWNLOAD_KLEIN3" "$DOWNLOAD_QWEN_IMAGE"
'''
        result = subprocess.run(["bash", "-c", script], env={**os.environ, "TEMPLATE_DIR": str(ROOT), "DOWNLOAD_KLEIN3": " TRUE ", "DOWNLOAD_QWEN_IMAGE": "true", "HF_TOKEN": ""}, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("CONTINUED:false:true", result.stdout)
        self.assertIn("Continuing template setup", result.stdout)
        self.assertIn("REPORT: Flux Klein 3", result.stdout)

    def test_hook_success_and_disabled_flags(self):
        for flag, expected in [("true", "true"), ("1", "1"), ("yes", "yes"), ("on", "on"), ("false", "false"), ("typo", "typo"), ("", "")]:
            script = 'python3() { echo CHECKED; return 0; }; source "$TEMPLATE_DIR/src/hooks/pre_download.sh"; printf "FLAG:%s" "$DOWNLOAD_KLEIN3"'
            result = subprocess.run(["bash", "-c", script], env={**os.environ, "TEMPLATE_DIR": str(ROOT), "DOWNLOAD_KLEIN3": flag, "HF_TOKEN": "hf_test"}, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0)
            self.assertIn("FLAG:" + expected, result.stdout)
            self.assertEqual("CHECKED" in result.stdout, flag in ("true", "1", "yes", "on"))

    def test_failed_preflight_keeps_other_family_provisioning(self):
        from validate_models import runtime_dir
        runtime = runtime_dir()
        dst = self.comfy / "workflows"
        manifest = self.comfy / "queue.tsv"
        env = {**os.environ, "TEMPLATE_DIR": str(ROOT), "HF_TOKEN": ""}
        template = json.loads((ROOT / "template.json").read_text())
        env.update({flag: "false" for flag in template["flags"]})
        env.update(DOWNLOAD_KLEIN3="true", DOWNLOAD_Z_IMAGE="true")
        script = '''
source "$TEMPLATE_DIR/src/hooks/pre_download.sh"
python3 "$1/src/provisioner.py" --template "$TEMPLATE_DIR/template.json" \\
    --registry "$TEMPLATE_DIR/src/models_registry.json" \\
    --workflows-src "$TEMPLATE_DIR/workflows" --workflows-dst "$2" \\
    --models-root "$3" --manifest "$4"
echo SETUP_CONTINUED
'''
        result = subprocess.run(["bash", "-c", script, "test", str(runtime), str(dst), str(self.comfy / "models"), str(manifest)], env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("HF_TOKEN is missing", result.stdout)
        self.assertIn("SETUP_CONTINUED", result.stdout)
        self.assertEqual(len(list(dst.rglob("*.json"))), 3)
        queue = manifest.read_text()
        self.assertIn("z_image_turbo_bf16", queue)
        self.assertNotIn("flux-3-image-klein-comfy", queue)
        self.assertFalse((dst / "Flux Klein 3").exists())



if __name__ == "__main__":
    unittest.main()
