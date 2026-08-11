# ComfyUI + Qwen Image — RunPod template

One-click deployment for **ComfyUI** with **Qwen-Image** (base + Edit) and **Z-Image Turbo**, including pre-configured workflows and on-boot model provisioning.

---

## Getting Started

### CivitAI token

Downloading LoRAs and checkpoints from CivitAI requires an API token.

1. Log into [CivitAI](https://civitai.com/) → **Manage Account** → **API Keys**.
2. Click **+ Add API key**, name it, save.
3. Set the token via the `civitai_token` env var on the template.

> **Important:** `CIVITAI_LORAS` and `CIVITAI_CHECKPOINTS` take **model version IDs**, not model IDs. On a model page, the version ID is in the URL after `?modelVersionId=` (or shown next to each version in the right-hand sidebar). Passing model IDs will fail to resolve.

### Deploy

1. Click **Deploy**.
2. Wait for the setup to complete (initial setup is **5–30 minutes** depending on network and selected models).
3. Subsequent deployments from the same network volume are much faster — models persist and the symlink layer skips re-copying.

---

## Environment variables

| Variable | Default | Required | Description |
|---|---|---|---|
| `QWEN_IMAGE_PRECISION` | `bf16` | no | `bf16` or `fp8`. Switches the downloaded Qwen-Image / Qwen-Image-Edit variants AND rewrites workflow references at boot so the swap is seamless. |
| `DOWNLOAD_QWEN_IMAGE` | `true` | no | Downloads Qwen-Image base models and copies the three base workflows. Set `false` only if you don't need base text-to-image. |
| `DOWNLOAD_QWEN_IMAGE_EDIT` | `true` | no | Downloads Qwen-Image-Edit 2511 and copies the three edit workflows. |
| `DOWNLOAD_Z_IMAGE` | `false` | no | Downloads Z-Image Turbo + `qwen_3_4b` text encoder + `ae` VAE and copies the two Z-Image workflows. |
| `DOWNLOAD_HMFEMME` | `false` | no | Downloads the Qwen-Image 2512 base (honouring `QWEN_IMAGE_PRECISION`) + text encoder + VAE, and copies the HMFemme workflow into the user dir. **Note:** the base model now ships with the template; only the private HearmemanAI LoRAs the workflow references must be supplied by you — see warnings printed at boot. |
| `download_boogu` | `false` | no | Downloads Boogu-Image models and copies the three Boogu workflows (base / edit / turbo). |
| `BOOGU_PRECISION` | `bf16` | no | `bf16` or `fp8`. Switches the Boogu diffusion variant AND rewrites the Boogu workflow references at boot. Independent of `QWEN_IMAGE_PRECISION`. |
| `download_krea2` | `false` | no | Downloads Krea-2 Turbo (`krea2_turbo_mxfp8`) + the raw Krea-2 base (`krea2_raw_bf16`, 26 GB — no workflow ships for it, build your own graph) + the Turbo distill LoRA (`krea2_turbo_lora_rank_64_bf16`, into `models/loras/`) + the Krea-2 Identity Edit LoRA (`krea2_identity_edit_v1_2_r128`, into `models/loras/`) + `qwen3vl_4b_fp8_scaled` text encoder, and copies the Krea-2 PiD workflow. Reuses the shared Qwen-Image PiD upscaler + VAE. The two `SummerVibesHM*` LoRAs it references are private — supply them yourself (see boot warnings). |
| `CIVITAI_LORAS` | — | no | Comma-separated CivitAI **model version IDs** to download into `models/loras/`. |
| `CIVITAI_CHECKPOINTS` | — | no | Comma-separated CivitAI **model version IDs** to download into `models/checkpoints/`. |
| `civitai_token` | — | only if using `CIVITAI_*` | CivitAI API token. Accepts `CIVITAI_TOKEN` as well. |
| `HF_TOKEN` | — | recommended | Hugging Face token. Unauthenticated downloads get rate-limited; setting this avoids stalled downloads on a fresh pod. |
| `GITHUB_PAT` | — | optional | GitHub PAT used to clone the private `Hearmeman24/ComfyUI-HMNodes` custom-node repo. Skipped silently if unset. |

All model downloads run in parallel through a 3-thread pool. Hugging Face URLs use `hf_hub_download` (with `hf_xet` acceleration enabled); non-HF URLs use `aria2c -x 16`.

---

## Included workflows

Workflows are only copied into the user's workflow dir if their owning `DOWNLOAD_*` flag is true.

**Qwen-Image base** (`DOWNLOAD_QWEN_IMAGE=true`)
- `QwenImage_2512_Workflow.json` — text-to-image on Qwen-Image 2512 (the recommended starting point)
- `Qwen_Workflow.json` — standard text-to-image
- `Qwen_Workflow_Slower_Higher_Quality.json` — same model, higher step count + 4× upscale pass

**Qwen-Image-Edit** (`DOWNLOAD_QWEN_IMAGE_EDIT=true`)
- `Qwen_image_edit.json` — single-image edit
- `Qwen_MultiAngle_image_edit.json` — uses the MultiAngle LoRA to generate alternative camera angles of an input image
- `Qwen_Image_To_Dateset_Workflow.json` — generate a small training dataset from a reference image (Lightning 8-step + skin-detail upscaler)

**Z-Image Turbo** (`DOWNLOAD_Z_IMAGE=true`)
- `Z_Image_Turbo.json` — fast text-to-image (turbo distillation)
- `Z_Image_Turbo_Upscale.json` — same plus 4× upscale pass

**HMFemme** (`DOWNLOAD_HMFEMME=true`, advanced)
- `HMFemme_Workflow.json` — runs on the Qwen-Image 2512 base, which the template downloads for you, plus several private HearmemanAI LoRAs. **You must supply the LoRAs yourself.**

**Boogu** (`download_boogu=true`)
- `Boogu_Base.json` — text-to-image
- `Boogu_Edit.json` — image editing (uses the `ComfyUI-Boogu` custom node)
- `Boogu_Turbo.json` — fast text-to-image

**Krea-2** (`download_krea2=true`)
- `Krea2_Workflow.json` — Krea-2 Turbo text-to-image. References the private `SummerVibesHM_krea2` LoRA you must supply yourself.
- `Krea2_PiD_Workflow.json` — same plus the shared Qwen-Image PiD 4× upscaler. References two private `SummerVibesHM*` LoRAs you must supply yourself.

The flag also pulls `krea2_raw_bf16.safetensors` (the undistilled Krea-2 base, 26 GB) into `models/diffusion_models/`, and two LoRAs into `models/loras/`: `krea2_turbo_lora_rank_64_bf16.safetensors` (the Turbo distillation as a rank-64 LoRA) and `krea2_identity_edit_v1_2_r128.safetensors` (Krea-2 Identity Edit v1.2, rank 128, ~0.9 GB — character-identity editing). No workflow ships for any of them — they're there so you can wire your own graph: the raw base alone with normal step counts and CFG, or the raw base plus the Turbo LoRA at a strength you choose, instead of the baked-in Turbo checkpoint the two workflows above use.

---

## Workflow → model mapping is automatic

When you set `QWEN_IMAGE_PRECISION=fp8`, workflows are patched at boot to reference the fp8 filenames (`qwen_image_2512_fp8_e4m3fn.safetensors`, `qwen_image_edit_2511_fp8mixed.safetensors`) — no manual edits needed.

If a workflow references a model that isn't in the registry (e.g. a private LoRA), the boot log prints a warning listing the missing basenames. You're expected to supply those via `CIVITAI_LORAS` / `CIVITAI_CHECKPOINTS` or by uploading them to `models/loras/` directly.

---

## SageAttention

SageAttention is built in the background on every boot (the build takes a few minutes; ComfyUI launches with `--use-sage-attention` if the build succeeds). There is currently no env var to disable it — if the build fails, ComfyUI still launches, just without sage attention.
