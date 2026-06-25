# Use multi-stage build with caching optimizations
FROM nvidia/cuda:13.0.3-cudnn-devel-ubuntu24.04 AS base

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_PREFER_BINARY=1 \
    PYTHONUNBUFFERED=1 \
    CMAKE_BUILD_PARALLEL_LEVEL=8 \
    HF_XET_HIGH_PERFORMANCE=1

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    apt-get update && \
    apt-get install -y --no-install-recommends \
        software-properties-common && \
    add-apt-repository ppa:deadsnakes/ppa && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
        python3.11 python3.11-venv python3.11-dev \
        python3-pip \
        curl ffmpeg ninja-build git aria2 git-lfs wget vim \
        libgl1 libglib2.0-0 build-essential gcc && \
    \
    ln -sf /usr/bin/python3.11 /usr/bin/python && \
    ln -sf /usr/bin/pip3 /usr/bin/pip && \
    \
    python3.11 -m venv /opt/venv && \
    \
    apt-get clean && rm -rf /var/lib/apt/lists/*

ENV PATH="/opt/venv/bin:$PATH"

RUN --mount=type=cache,target=/root/.cache/pip \
    pip install torch torchvision torchaudio \
        --index-url https://download.pytorch.org/whl/cu130

# Freeze the exact coherent torch trio this build resolved, then apply it as a
# global PIP_CONSTRAINT. Every later pip install — here AND in start.sh's
# custom-node requirements loop (which run with no --index-url) — is now forbidden
# from upgrading/downgrading torch off the cu130 channel. This is the guard that
# stops a custom-node requirements.txt silently pulling a mismatched torch.
RUN pip freeze | grep -E "^(torch|torchvision|torchaudio|torchsde)==" > /torch-constraint.txt
ENV PIP_CONSTRAINT=/torch-constraint.txt

RUN --mount=type=cache,target=/root/.cache/pip \
    pip install packaging setuptools wheel

# Runtime libraries. comfy-cli removed (§7) — ComfyUI is cloned directly below.
# huggingface_hub + hf_xet pulled in for the new download manager (§6).
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install pyyaml gdown triton jupyterlab jupyterlab-lsp \
        jupyter-server jupyter-server-terminals \
        ipykernel jupyterlab_code_formatter \
        "huggingface_hub>=0.27" hf_xet

# §7: Clone ComfyUI directly instead of using `comfy install`.
RUN --mount=type=cache,target=/root/.cache/pip \
    git clone --depth=1 https://github.com/comfyanonymous/ComfyUI.git /ComfyUI \
    && pip install -r /ComfyUI/requirements.txt

FROM base AS final
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install opencv-python

# Bulk custom-node clone. All these names start with capitals, so they sort
# before the lowercase `comfyui-manager` cloned below (§11).
RUN for repo in \
    https://github.com/ssitu/ComfyUI_UltimateSDUpscale.git \
    https://github.com/kijai/ComfyUI-KJNodes.git \
    https://github.com/rgthree/rgthree-comfy.git \
    https://github.com/JPS-GER/ComfyUI_JPS-Nodes.git \
    https://github.com/Suzie1/ComfyUI_Comfyroll_CustomNodes.git \
    https://github.com/Jordach/comfy-plasma.git \
    https://github.com/ltdrdata/ComfyUI-Impact-Pack.git \
    https://github.com/ClownsharkBatwing/RES4LYF.git \
    https://github.com/yolain/ComfyUI-Easy-Use.git \
    https://github.com/WASasquatch/was-node-suite-comfyui.git \
    https://github.com/theUpsider/ComfyUI-Logic.git \
    https://github.com/cubiq/ComfyUI_essentials.git \
    https://github.com/chrisgoringe/cg-image-picker.git \
    https://github.com/chflame163/ComfyUI_LayerStyle.git \
    https://github.com/ltdrdata/ComfyUI-Impact-Subpack.git \
    https://github.com/Jonseed/ComfyUI-Detail-Daemon.git \
    https://github.com/shadowcz007/comfyui-mixlab-nodes.git \
    https://github.com/chflame163/ComfyUI_LayerStyle_Advance.git \
    https://github.com/bash-j/mikey_nodes.git \
    https://github.com/chrisgoringe/cg-use-everywhere.git \
    https://github.com/M1kep/ComfyLiterals.git; \
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

# §11: ComfyUI-Manager — lowercase dir so it loads AFTER other nodes
# and can detect their IMPORT FAILED states.
RUN --mount=type=cache,target=/root/.cache/pip \
    git clone --depth=1 https://github.com/ltdrdata/ComfyUI-Manager.git \
        /ComfyUI/custom_nodes/comfyui-manager \
    && if [ -f /ComfyUI/custom_nodes/comfyui-manager/requirements.txt ]; then \
         pip install -r /ComfyUI/custom_nodes/comfyui-manager/requirements.txt; \
       fi

# §8: Several custom-node requirements.txt files pull in CPU-only `onnxruntime`
# alongside `onnxruntime-gpu`. They share a Python module, so last install wins.
# Force GPU at end of build; start.sh defensively re-checks at boot.
RUN --mount=type=cache,target=/root/.cache/pip \
    pip uninstall -y onnxruntime onnxruntime-gpu 2>/dev/null || true; \
    pip install onnxruntime-gpu

# §12: Bake the CivitAI helper at build time so boot doesn't pay a git clone.
RUN git clone --depth=1 https://github.com/Hearmeman24/CivitAI_Downloader.git /tmp/civitai-dl \
    && cp /tmp/civitai-dl/download_with_aria.py /usr/local/bin/ \
    && chmod +x /usr/local/bin/download_with_aria.py \
    && rm -rf /tmp/civitai-dl

COPY src/start_script.sh /start_script.sh
RUN chmod +x /start_script.sh
COPY Eyes.pt /Eyes.pt
COPY 4xLSDIR.pth /4xLSDIR.pth

CMD ["/start_script.sh"]
