# Qwen-Image, Z-Image, Boogu and Krea-2, ComfyUI on RunPod

Created by HearmemanAI. Something not working, or a question about a workflow? Ask in
help-and-support on [my Discord](https://discord.gg/ZVWVhT43GW). That is the only place I do
support, and it is also where new releases are announced.

Four image model families on one pod, each behind its own flag, so you only download the ones you
want.

## Before you deploy

Set all of this on the template before you click Deploy, not after.

Click Edit Template and open the environment variables tab. Set at least one download flag to
true. They are all off by default. A pod with no flag set boots a working but empty ComfyUI, so the
workflows open with blank loader dropdowns and look broken. The full list is in the next section.

If you want your own CivitAI LoRAs or checkpoints on the pod, set `civitai_token` and the ID
variables below. The steps are
[written up on my Discord](https://discord.com/channels/1359855405613715495/1536707221788950708),
and in
[this article](https://civitai.red/articles/12333/how-to-use-hearmemans-civitai-downloader-when-deploying-a-runpod-template).

Then deploy. The first boot takes 5 to 30 minutes depending on which flags you set. ComfyUI comes
up while the models are still downloading, so you can look around before it finishes. Later deploys
on the same network volume are much faster.

FYI: this template is built for CUDA 13.0 and above.

## Environment variables

| Variable | Default | What it does |
|---|---|---|
| `DOWNLOAD_QWEN_IMAGE` | false | Qwen-Image base, with its four workflows |
| `DOWNLOAD_QWEN_IMAGE_EDIT` | false | Qwen-Image-Edit, with its three workflows |
| `DOWNLOAD_Z_IMAGE` | false | Z-Image Turbo, with its three workflows |
| `download_boogu` | false | Boogu-Image, with its three workflows: base, edit and turbo |
| `download_krea2` | false | Krea-2, with its two workflows |
| `QWEN_IMAGE_PRECISION` | bf16 | bf16 or fp8 for the Qwen-Image base model. Qwen-Image-Edit is not affected, it ships as a single build. |
| `BOOGU_PRECISION` | bf16 | bf16 or fp8 for the Boogu models. Independent of the one above. |
| `civitai_token` | empty | Your CivitAI API token |
| `CIVITAI_LORAS` | empty | Comma-separated CivitAI version IDs. They go to `models/loras`. |
| `CIVITAI_CHECKPOINTS` | empty | Comma-separated CivitAI version IDs. They go to `models/checkpoints`. |
| `HF_TOKEN` | empty | Optional. Raises your Hugging Face rate limit, which makes a first boot less likely to stall. |
| `GITHUB_PAT` | empty | Only for my paid workflows. It installs the extra node packs those graphs need. Everything in this template works without it. |

Turn on as many download flags as you want. A model that two of them share is only downloaded once.
Only the workflows belonging to the flags you enabled are installed, so the menu shows you what your
models can actually run.

About the precision switches: bf16 is the default and runs everywhere. fp8 is a smaller download and
is faster on cards with native fp8 support, which is the 4090, L40, H100, H200 and RTX 50xx. Only
the precision you ask for is downloaded, and the copied workflows are pointed at those files for
you, so you never touch a dropdown.

## Once it is up

Click Connect, then open port 8188 for ComfyUI or port 8888 for JupyterLab. The boot log is at
`/workspace/comfyui.log`.

Open the Workflows tab in ComfyUI. Workflows are grouped in a folder per model family, and each one
carries notes in the graph telling you what it does and which settings matter, which is a better
place to read than this page. The pod also writes three notes into the top of that same list on
first boot: Welcome, Adding Models, and Troubleshooting.

[My other templates](https://docs.google.com/spreadsheets/d/1NfbfZLzE9GIAD5B_y6xjK1IdW95c14oS1JuIG9QihL8/edit)
