## What is in this template

This template runs Qwen-Image (base + Edit), Z-Image Turbo, Boogu-Image and
Krea-2 on ComfyUI. Each family ships behind its own `DOWNLOAD_*` flag, so a
pod only downloads what you ask for.

- Qwen-Image base and Qwen-Image-Edit download by default on every new pod.
- Z-Image Turbo, Boogu-Image and Krea-2 are off by default; set the
  matching flag to `true` to pull them in.

Every workflow ships with `Your_Character_LoRA_Here.safetensors` in its
LoRA loader slots. That is a placeholder, not a real file: drop your own
LoRA into `models/loras/` and point the loader at it. Turbo and Lightning
distillation LoRAs are the exception: those ARE shipped and load by
default, since the workflow needs them to run at all.

## Settings you can change

Set these in the environment variables tab. Click Edit Template before
you deploy, or edit the variables on this pod and restart it.

| Variable | Default | What it does |
|---|---|---|
| DOWNLOAD_QWEN_IMAGE | false | Qwen-Image base: downloads the models and copies the four base workflows. |
| DOWNLOAD_QWEN_IMAGE_EDIT | false | Qwen-Image-Edit: downloads the models and copies the three edit workflows. |
| QWEN_IMAGE_PRECISION | bf16 | bf16 or fp8 for the Qwen-Image base model. It repoints the model and rewrites every copied workflow that references it, at boot. Qwen-Image-Edit is not affected: it ships as a single int8 build. |
| DOWNLOAD_Z_IMAGE | false | Z-Image Turbo: downloads the models and copies the three Z-Image workflows. |
| download_boogu | false | Boogu-Image: downloads the models and copies the three Boogu workflows (base / edit / turbo). |
| BOOGU_PRECISION | bf16 | bf16 or fp8. Same idea as QWEN_IMAGE_PRECISION, scoped to Boogu only: the two switches are independent. |
| download_krea2 | false | Krea-2: downloads the Turbo checkpoint, the raw base, both Krea-2 LoRAs and the text encoder, and copies the two Krea-2 workflows. |
| CIVITAI_LORAS | unset | Comma-separated CivitAI model version IDs to download into models/loras/. |
| CIVITAI_CHECKPOINTS | unset | Comma-separated CivitAI model version IDs to download into models/checkpoints/. |
| civitai_token | unset | Your CivitAI API token. CIVITAI_TOKEN and CIVITAI_API_KEY are also accepted. |
| HF_TOKEN | unset | Your Hugging Face token. Recommended: unauthenticated downloads get rate-limited on a fresh pod. |

## Picking a precision

You can skip this. bf16 is the default and runs everywhere.

| Precision | What you get |
|---|---|
| bf16 (default) | Full-precision weights. Larger download, works on every GPU. |
| fp8 | Scaled fp8 weights. Smaller download, faster on cards with native fp8 support (4090, L40, H100, H200, RTX 50xx). |

Only the precision you ask for is downloaded, and the workflows are
pointed at those files automatically, so you never touch a dropdown. If
you set a value that is not bf16 or fp8, the pod tells you and uses bf16.

## Krea-2 extras

`download_krea2` also pulls in the raw (undistilled) Krea-2 base and two
LoRAs: the Turbo distillation as a rank-64 LoRA, and Krea-2 Identity Edit
v1.2, into `models/loras/`. No workflow ships for these; they are there
so you can wire your own graph instead of the baked-in Turbo checkpoint
the two shipped Krea-2 workflows use.

## Missing models

If a workflow references a model that is not in the registry (a private
LoRA, for example), the boot log prints a warning listing the missing
basenames. Supply those via `CIVITAI_LORAS` / `CIVITAI_CHECKPOINTS`, or
upload them to `models/loras/` directly.
