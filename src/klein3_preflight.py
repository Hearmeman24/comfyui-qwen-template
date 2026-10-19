"""Bounded, metadata-only HF checks. Never log tokens or remote error bodies."""
import json
import os
from pathlib import Path
import urllib.error
import urllib.request

REPO = "https://huggingface.co/black-forest-labs/flux-3-image-klein-comfy"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def check(root, env, opener=None):
    token = (env.get("HF_TOKEN") or "").strip()
    if not token:
        return "HF_TOKEN is missing. Set an explicit Hugging Face read token."
    if any(c.isspace() or ord(c) < 32 or ord(c) > 126 for c in token):
        return "HF_TOKEN is malformed. Replace it with a valid Hugging Face read token."
    opener = opener or urllib.request.build_opener(NoRedirect())
    headers = {"Authorization": "Bearer " + token}
    template = json.loads((root / "template.json").read_text())
    registry = json.loads((root / "src/models_registry.json").read_text())
    # All weights are explicit so access checks and provisioning use the same set.
    models = template["flags"]["DOWNLOAD_KLEIN3"]["extra_models"]
    probes = [("HF_TOKEN", "https://huggingface.co/api/whoami-v2", "GET")]
    probes += [(name, registry[name]["url"], "HEAD") for name in models]
    for name, url, method in probes:
        try:
            with opener.open(urllib.request.Request(url, headers=headers, method=method), timeout=10) as response:
                if method == "GET":
                    identity = json.load(response)
                    if not isinstance(identity, dict) or not identity.get("name"):
                        return "HF_TOKEN validity could not be confirmed (unexpected identity response)."
        except urllib.error.HTTPError as exc:
            # HF resolve HEAD redirects to signed storage only after checking access.
            # Do not follow it or forward our Authorization header to another host.
            if method == "HEAD" and exc.code in (302, 303, 307, 308):
                continue
            if exc.code == 401:
                if name == "HF_TOKEN":
                    return "HF_TOKEN is invalid or expired (HTTP 401). Replace the token."
                return f"Access denied for {name} (HTTP 401). Check token permissions and model access."
            if exc.code == 403:
                return f"Access denied for {name} (HTTP 403). Accept the model license and enable gated-repository read access on your token."
            return f"Could not verify {name} (HTTP {exc.code}); retry after checking Hugging Face availability and file access."
        except (OSError, ValueError, urllib.error.URLError):
            return f"Could not verify {name}: network/TLS timeout or invalid Hugging Face response. Retry on the next boot."
    comfy = Path(env.get("COMFYUI_DIR", "/ComfyUI"))
    if not (comfy / "comfy/ldm/flux3/model.py").is_file():
        return "Installed ComfyUI lacks FLUX.3 support. Redeploy with the updated Qwen image (ComfyUI v0.42.1) and use COMFYUI_VERSION=approved."
    return None


def main():
    try:
        error = check(Path(__file__).resolve().parents[1], os.environ)
    except Exception:
        # Fail closed for this model, but never leak credentials via a traceback.
        error = "Klein 3 preflight failed unexpectedly; check template configuration and retry."
    if error:
        print(f"ERROR [Klein 3]: {error}")
        print(f"[Klein 3] Model access: {REPO}")
        return 1
    print("[Klein 3] HF_TOKEN is valid and access to all four model files is confirmed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
