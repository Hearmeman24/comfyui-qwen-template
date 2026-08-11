"""The boot-time DNS preflight in src/start_script.sh.

RunPod's "global networking" pod option blocks outbound DNS. Without a preflight
the pod dies on the first git clone with `Could not resolve host: github.com`,
which sends the user to look at GitHub instead of at the pod setting.
"""

import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
START_SCRIPT = REPO_ROOT / "src" / "start_script.sh"


def make_stub(bin_dir: Path, name: str, body: str):
    path = bin_dir / name
    path.write_text("#!/usr/bin/env bash\n" + body + "\n")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def run_start_script(bin_dir: Path):
    """Run start_script.sh with bin_dir prepended to PATH."""
    env = dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}")
    return subprocess.run(
        ["bash", str(START_SCRIPT)],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


class NetworkPreflightTest(unittest.TestCase):
    def setUp(self):
        self.bin = Path(tempfile.mkdtemp()) / "bin"
        self.bin.mkdir(parents=True)
        # Never let the test touch the real filesystem or network past the preflight.
        make_stub(self.bin, "rm", 'exit 0')
        make_stub(self.bin, "git", 'exit 99')

    def test_dns_failure_stops_the_boot_before_the_repo_sync(self):
        make_stub(self.bin, "curl", 'exit 6')  # 6 = could not resolve host
        result = run_start_script(self.bin)

        self.assertNotEqual(result.returncode, 0)
        self.assertNotEqual(result.returncode, 99, "reached the git sync despite dead DNS")

    def test_dns_failure_names_runpod_global_networking(self):
        make_stub(self.bin, "curl", 'exit 6')  # 6 = could not resolve host
        output = run_start_script(self.bin).stdout + run_start_script(self.bin).stderr

        self.assertIn("Global Networking", output)
        self.assertIn("github.com", output)
        self.assertIn("huggingface.co", output)

    def test_working_dns_falls_through_to_the_repo_sync(self):
        make_stub(self.bin, "curl", 'exit 0')
        result = run_start_script(self.bin)

        self.assertEqual(result.returncode, 99, "preflight blocked a pod with working DNS")
        self.assertNotIn("Global Networking", result.stdout + result.stderr)

    def test_second_host_answering_is_enough(self):
        make_stub(self.bin, "curl", '[[ "$*" == *huggingface.co* ]] && exit 0 || exit 6')
        result = run_start_script(self.bin)

        self.assertEqual(result.returncode, 99, "one unreachable host blocked a healthy pod")

    def test_preflight_runs_before_the_repo_clone(self):
        text = START_SCRIPT.read_text()
        self.assertLess(
            text.index("curl"),
            text.index("git clone"),
            "the preflight must run before the clone it is diagnosing",
        )


if __name__ == "__main__":
    sys.exit(0 if unittest.main(exit=False).result.wasSuccessful() else 1)
