# syntax=docker/dockerfile:1
# ============================================================================
# comfyui-qwen-template image, built FROM the shared base
# (hearmeman/comfyui-base, comfyui-runtime/base/Dockerfile).
#
# The base owns: python 3.12 + /opt/venv (on PATH), the pinned torch trio +
# /torch-constraint.txt applied via ENV PIP_CONSTRAINT, pip tooling, pyyaml/
# gdown/triton/jupyterlab, huggingface_hub + hf_xet, opencv-python, ComfyUI
# pinned at COMFYUI_REF (v0.32.0, which ships TextEncodeBooguEdit,
# TextEncodeQwenImageEditPlus and PiDConditioning as core nodes) with
# /comfyui-approved-ref, ComfyUI-Manager, both SageAttention wheels under
# /opt/sage/, the CivitAI downloader, and ENV ORT_INDEX_ARGS (the
# per-CUDA-variant onnxruntime index nuance).
#
# This layer adds ONLY the qwen node set, the onnxruntime-gpu reassert, and
# the entrypoint. BASE_IMAGE is passed by CI from pins.json's "base_image";
# the default below mirrors that pin so a plain build stays coherent.
# ============================================================================
ARG BASE_IMAGE=hearmeman/comfyui-base:cu130-comfy0.34.0-torch2.11.0
FROM ${BASE_IMAGE}

# The qwen node set, culled 2026-08-14 to the packs the 15 shipped workflows
# actually resolve nodes from, plus ComfyUI-Easy-Use, kept as a Tier 1 pack
# family-wide even though none of the 15 surviving workflows resolve a node
# from it. ComfyUI-Manager is base-owned, not repeated here.
#
# Node-type gate (52 distinct types across the 15 surviving workflows, incl.
# 2 subgraph-UUID types, verified against ComfyUI v0.32.0 core + these packs
# at each pack's current HEAD, zero unresolved): rgthree-comfy registers
# "Fast Bypasser (rgthree)", "Lora Loader Stack (rgthree)" and "Image
# Comparer (rgthree)"; ComfyUI-KJNodes registers GetNode/SetNode,
# ImageResizeKJv2 and ModelPassThrough; ComfyUI_essentials registers
# "SimpleMath+"; ComfyUI_Comfyroll_CustomNodes registers "CR Prompt List"
# and "CR Image Grid Panel"; ComfyUI-Impact-Pack registers ToBasicPipe,
# FromBasicPipe_v2 and ImageListToImageBatch; RES4LYF registers
# ClownsharKSampler_Beta (used by Qwen_Workflow_Slower_Higher_Quality only,
# not the Film Grain node that motivated the original recheck);
# ComfyUI_JPS-Nodes registers "Text Prompt (JPS)"; ComfyUI_UltimateSDUpscale
# registers UltimateSDUpscale; ComfyLiterals registers "Float". Dropped:
# ComfyUI-FSampler, ComfyUI-VAE-Utils and
# ComfyUI-Boogu (all boot-cloned today; their only consumer is either
# deleted with HMFemme_Workflow.json or, for Boogu, now a core v0.32.0
# node), ComfyUI-HMNodes (private repo behind GITHUB_PAT, never belonged in
# a public template), comfy-plasma, was-node-suite-comfyui, ComfyUI-Logic,
# cg-image-picker, ComfyUI_LayerStyle(+Advance), ComfyUI-Impact-Subpack,
# ComfyUI-Detail-Daemon, comfyui-mixlab-nodes, mikey_nodes and
# cg-use-everywhere (referenced by nothing in the surviving workflows).
# Cache-busters, one per pack (CLAUDE.md section 8; qwen-image had none).
# docker_layer_caching serves the cached clone layer forever otherwise, so a
# rebuild silently reships whatever HEAD the FIRST build happened to resolve.
# Each ADD re-reads the GitHub API every build; any pack moving invalidates the
# whole loop below. Branches resolved from the API, not guessed: Impact-Pack is
# 'Main' with a capital M and ComfyLiterals is 'master'.

ADD https://api.github.com/repos/kijai/ComfyUI-KJNodes/git/refs/heads/main /pack-refs/ComfyUI-KJNodes.json
ADD https://api.github.com/repos/rgthree/rgthree-comfy/git/refs/heads/main /pack-refs/rgthree-comfy.json
ADD https://api.github.com/repos/JPS-GER/ComfyUI_JPS-Nodes/git/refs/heads/main /pack-refs/ComfyUI_JPS-Nodes.json
ADD https://api.github.com/repos/Suzie1/ComfyUI_Comfyroll_CustomNodes/git/refs/heads/main /pack-refs/ComfyUI_Comfyroll_CustomNodes.json
ADD https://api.github.com/repos/ltdrdata/ComfyUI-Impact-Pack/git/refs/heads/Main /pack-refs/ComfyUI-Impact-Pack.json
ADD https://api.github.com/repos/ClownsharkBatwing/RES4LYF/git/refs/heads/main /pack-refs/RES4LYF.json
ADD https://api.github.com/repos/yolain/ComfyUI-Easy-Use/git/refs/heads/main /pack-refs/ComfyUI-Easy-Use.json
ADD https://api.github.com/repos/cubiq/ComfyUI_essentials/git/refs/heads/main /pack-refs/ComfyUI_essentials.json
ADD https://api.github.com/repos/M1kep/ComfyLiterals/git/refs/heads/master /pack-refs/ComfyLiterals.json
ADD https://api.github.com/repos/ssitu/ComfyUI_UltimateSDUpscale/git/refs/heads/main /pack-refs/ComfyUI_UltimateSDUpscale.json
# PIP_CONSTRAINT (base-owned) applies to every requirements install below.
RUN for repo in \
    https://github.com/kijai/ComfyUI-KJNodes.git \
    https://github.com/rgthree/rgthree-comfy.git \
    https://github.com/JPS-GER/ComfyUI_JPS-Nodes.git \
    https://github.com/Suzie1/ComfyUI_Comfyroll_CustomNodes.git \
    https://github.com/ltdrdata/ComfyUI-Impact-Pack.git \
    https://github.com/ClownsharkBatwing/RES4LYF.git \
    https://github.com/yolain/ComfyUI-Easy-Use.git \
    https://github.com/cubiq/ComfyUI_essentials.git \
    https://github.com/M1kep/ComfyLiterals.git \
    https://github.com/ssitu/ComfyUI_UltimateSDUpscale.git; \
    do \
        cd /ComfyUI/custom_nodes; \
        repo_dir=$(basename "$repo" .git); \
        if [ "$repo" = "https://github.com/ssitu/ComfyUI_UltimateSDUpscale.git" ]; then \
            git clone --recursive "$repo"; \
        else \
            git clone "$repo"; \
        fi; \
        if [ -f "/ComfyUI/custom_nodes/$repo_dir/requirements.txt" ]; then \
            pip install -r "/ComfyUI/custom_nodes/$repo_dir/requirements.txt"; \
        fi; \
        if [ -f "/ComfyUI/custom_nodes/$repo_dir/install.py" ]; then \
            python "/ComfyUI/custom_nodes/$repo_dir/install.py"; \
        fi; \
    done

# Force GPU onnxruntime. Several node requirements pull in plain
# `onnxruntime` (CPU), which shadows the GPU install because both provide the
# same `onnxruntime` module and last install wins. This reassert therefore
# comes AFTER the clone loop, and no later RUN may pip install anything
# (comfyui-runtime base Dockerfile, onnxruntime ordering trap). ORT_INDEX_ARGS
# is base-owned data: the Azure onnxruntime-cuda-12 index on cu128, empty on
# cu130 where PyPI's onnxruntime-gpu links CUDA 13.
RUN --mount=type=cache,target=/root/.cache/pip \
    pip uninstall -y onnxruntime onnxruntime-gpu 2>/dev/null || true; \
    pip install onnxruntime-gpu $ORT_INDEX_ARGS

# Build-time gate: the shipped image must expose the CUDA provider. Provider
# enumeration is import-only and works with no GPU present, so this fails the
# CI build, not a customer pod. CI greps this Dockerfile for the
# CUDAExecutionProvider assertion and for the no-pip-install-after-it rule.
RUN python3 -c "import onnxruntime; p = onnxruntime.get_available_providers(); assert 'CUDAExecutionProvider' in p, p; print('onnxruntime providers OK:', p)"

COPY src/start_script.sh /start_script.sh
RUN chmod +x /start_script.sh

CMD ["/start_script.sh"]
