#!/usr/bin/env bash

# Use libtcmalloc for better memory management
TCMALLOC="$(ldconfig -p | grep -Po "libtcmalloc.so.\d" | head -n 1)"
export LD_PRELOAD="${TCMALLOC}"

NETWORK_VOLUME="/workspace"
REPO_DIR="/comfyui-qwen-template"

# Optional user override hook
if [ -f "/workspace/additional_params.sh" ]; then
    chmod +x /workspace/additional_params.sh
    echo "Executing additional_params.sh..."
    /workspace/additional_params.sh
else
    echo "additional_params.sh not found in /workspace. Skipping..."
fi

# Background: build SageAttention
echo "Starting SageAttention build..."
(
    export EXT_PARALLEL=4 NVCC_APPEND_FLAGS="--threads 8" MAX_JOBS=32
    cd /tmp
    git clone https://github.com/thu-ml/SageAttention.git
    cd SageAttention
    git reset --hard 68de379
    pip install -e .
    echo "SageAttention build completed" > /tmp/sage_build_done
) > /tmp/sage_build.log 2>&1 &
SAGE_PID=$!
echo "SageAttention build started in background (PID: $SAGE_PID)"

# Fallback: no network volume attached
if [ ! -d "$NETWORK_VOLUME" ]; then
    echo "NETWORK_VOLUME directory '$NETWORK_VOLUME' does not exist. Falling back to /."
    NETWORK_VOLUME="/"
    jupyter-lab --ip=0.0.0.0 --allow-root --no-browser --NotebookApp.token='' --NotebookApp.password='' --ServerApp.allow_origin='*' --ServerApp.allow_credentials=True --notebook-dir=/ &
else
    jupyter-lab --ip=0.0.0.0 --allow-root --no-browser --NotebookApp.token='' --NotebookApp.password='' --ServerApp.allow_origin='*' --ServerApp.allow_credentials=True --notebook-dir=/workspace &
fi

COMFYUI_DIR="/ComfyUI"
PERSIST_ROOT="$NETWORK_VOLUME/ComfyUI"
WORKFLOW_DIR="$PERSIST_ROOT/user/default/workflows"
CUSTOM_NODES_DIR="$PERSIST_ROOT/custom_nodes"
UPSCALE_MODELS_DIR="$PERSIST_ROOT/models/upscale_models"
export PERSIST_ROOT

# §1 + §2: symlink user-data subdirs onto the volume, generate extra_model_paths.yaml.
EXTRA_PATHS_FLAG=""
if [ "$NETWORK_VOLUME" != "/" ]; then
    mkdir -p "$PERSIST_ROOT"/{models,user,output,input,custom_nodes}
    if [ -d "$COMFYUI_DIR/user" ] && [ ! -L "$COMFYUI_DIR/user" ]; then
        cp -an "$COMFYUI_DIR/user/." "$PERSIST_ROOT/user/" 2>/dev/null || true
        rm -rf "$COMFYUI_DIR/user"
    fi
    for sub in models user output input; do
        [ -L "$COMFYUI_DIR/$sub" ] || rm -rf "$COMFYUI_DIR/$sub" 2>/dev/null || true
        ln -sfn "$PERSIST_ROOT/$sub" "$COMFYUI_DIR/$sub"
    done

    cat > "$COMFYUI_DIR/extra_model_paths.yaml" <<EOF
network_volume:
    base_path: $PERSIST_ROOT
    checkpoints: models/checkpoints
    clip: models/clip
    clip_vision: models/clip_vision
    configs: models/configs
    controlnet: models/controlnet
    diffusers: models/diffusers
    diffusion_models: models/diffusion_models
    embeddings: models/embeddings
    gligen: models/gligen
    hypernetworks: models/hypernetworks
    loras: models/loras
    photomaker: models/photomaker
    style_models: models/style_models
    text_encoders: models/text_encoders
    unet: models/unet
    upscale_models: models/upscale_models
    vae: models/vae
    vae_approx: models/vae_approx
    custom_nodes: custom_nodes
EOF
    EXTRA_PATHS_FLAG="--extra-model-paths-config $COMFYUI_DIR/extra_model_paths.yaml"
else
    rm -f "$COMFYUI_DIR/extra_model_paths.yaml"
fi

echo "Updating ComfyUI repository..."
cd "$COMFYUI_DIR"
git checkout master
git pull
echo "✅ ComfyUI repository updated"

# §9: background pip installs into a single PID array + one wait loop at the end.
declare -A INSTALL_PIDS=()

echo "Installing ComfyUI requirements (background)..."
( /opt/venv/bin/python3 -m pip install -r "$COMFYUI_DIR/requirements.txt" ) > /tmp/pip_comfyui.log 2>&1 &
INSTALL_PIDS[comfyui_requirements]=$!

echo "Installing qwen-vl-utils (background)..."
( /opt/venv/bin/python3 -m pip install "qwen-vl-utils>=0.0.8" ) > /tmp/pip_qwen_vl.log 2>&1 &
INSTALL_PIDS[qwen_vl_utils]=$!

# §10: consolidated custom-node clone-or-pull loop.
mkdir -p "$CUSTOM_NODES_DIR"
CUSTOM_REPOS=(
    "https://github.com/spacepxl/ComfyUI-VAE-Utils.git|force"
    "https://github.com/obisin/ComfyUI-FSampler.git"
)
if [ -n "$GITHUB_PAT" ]; then
    CUSTOM_REPOS+=( "https://${GITHUB_PAT}@github.com/Hearmeman24/ComfyUI-HMNodes.git" )
else
    echo "⏭️  GITHUB_PAT not set. Skipping ComfyUI-HMNodes clone."
fi

for entry in "${CUSTOM_REPOS[@]}"; do
    url="${entry%%|*}"
    mode=""
    [[ "$entry" == *"|"* ]] && mode="${entry#*|}"
    name="$(basename "$url" .git)"
    dir="$CUSTOM_NODES_DIR/$name"

    if [ "$mode" = "force" ] && [ -d "$dir" ]; then
        echo "🗑️  Removing existing $name (force-refresh)..."
        rm -rf "$dir"
    fi

    if [ -d "$dir/.git" ]; then
        echo "🔄 Updating $name..."
        git -C "$dir" pull --ff-only || true
    else
        echo "📥 Cloning $name..."
        git clone "$url" "$dir" || echo "❌ Failed to clone $name"
    fi

    if [ -f "$dir/requirements.txt" ]; then
        ( /opt/venv/bin/python3 -m pip install -r "$dir/requirements.txt" ) > "/tmp/pip_${name}.log" 2>&1 &
        INSTALL_PIDS[$name]=$!
    fi
done

# §5: model provisioning + download (replaces the entire hand-listed download block).
echo "🧩 Provisioning workflows + manifest..."
/opt/venv/bin/python3 "$REPO_DIR/src/provision_models.py"

# 4xLSDIR.pth is baked into the image — move it into place if missing.
mkdir -p "$UPSCALE_MODELS_DIR"
if [ ! -f "$UPSCALE_MODELS_DIR/4xLSDIR.pth" ] && [ -f "/4xLSDIR.pth" ]; then
    mv "/4xLSDIR.pth" "$UPSCALE_MODELS_DIR/4xLSDIR.pth"
    echo "Moved 4xLSDIR.pth into place."
fi

echo "⬇️  Starting model downloads (HF via hf_hub_download, others via aria2)..."
/opt/venv/bin/python3 "$REPO_DIR/src/download_models.py" || {
    echo "❌ Some model downloads failed — see output above. Continuing to launch anyway."
}

# CivitAI extras (user-provided IDs). Backgrounded so they don't block launch.
if [ -n "$CIVITAI_LORAS" ] || [ -n "$CIVITAI_CHECKPOINTS" ]; then
    mkdir -p "$PERSIST_ROOT/models/loras" "$PERSIST_ROOT/models/checkpoints"
    declare -A CIVITAI_MAP=(
        ["$PERSIST_ROOT/models/loras"]="$CIVITAI_LORAS"
        ["$PERSIST_ROOT/models/checkpoints"]="$CIVITAI_CHECKPOINTS"
    )
    for target in "${!CIVITAI_MAP[@]}"; do
        IFS=',' read -ra IDS <<< "${CIVITAI_MAP[$target]}"
        for mid in "${IDS[@]}"; do
            mid="${mid// /}"
            [ -z "$mid" ] && continue
            echo "🚀 CivitAI: scheduling $mid -> $target"
            ( cd "$target" && download_with_aria.py -m "$mid" ) &
            sleep 6
        done
    done
fi

# ComfyUI-Manager default config
CONFIG_PATH="$PERSIST_ROOT/user/default/ComfyUI-Manager"
CONFIG_FILE="$CONFIG_PATH/config.ini"
mkdir -p "$CONFIG_PATH"
if [ ! -f "$CONFIG_FILE" ]; then
    cat > "$CONFIG_FILE" <<EOL
[default]
preview_method = auto
git_exe =
use_uv = False
channel_url = https://raw.githubusercontent.com/ltdrdata/ComfyUI-Manager/main
share_option = all
bypass_ssl = False
file_logging = True
component_policy = workflow
update_policy = stable-comfyui
windows_selector_event_loop_policy = False
model_download_by_agent = False
downgrade_blacklist =
security_level = normal
skip_migration_check = False
always_lazy_install = False
network_mode = public
db_mode = cache
EOL
else
    sed -i 's/^preview_method = .*/preview_method = auto/' "$CONFIG_FILE"
fi

echo "cd $NETWORK_VOLUME" >> ~/.bashrc

# §9: wait on all background pip installs before launch
for name in "${!INSTALL_PIDS[@]}"; do
    if wait "${INSTALL_PIDS[$name]}"; then
        echo "✅ pip install: $name"
    else
        echo "❌ pip install failed: $name (see /tmp/pip_${name}.log)"
    fi
done

# §8 runtime defensive: a custom-node requirements.txt may have just clobbered
# onnxruntime-gpu with the CPU build. Re-assert GPU if so.
if ! /opt/venv/bin/python3 -c 'import onnxruntime, sys; sys.exit(0 if "CUDAExecutionProvider" in onnxruntime.get_available_providers() else 1)' 2>/dev/null; then
    echo "🩺 onnxruntime missing CUDAExecutionProvider — reinstalling onnxruntime-gpu..."
    /opt/venv/bin/python3 -m pip uninstall -y onnxruntime onnxruntime-gpu 2>/dev/null || true
    /opt/venv/bin/python3 -m pip install onnxruntime-gpu
fi

# Wait for SageAttention build
while kill -0 "$SAGE_PID" 2>/dev/null; do
    echo "🛠️  SageAttention is currently installing... (this can take around 5 minutes)"
    sleep 10
done
SAGE_ATTENTION_AVAILABLE=false
if [ -f "/tmp/sage_build_done" ]; then
    SAGE_ATTENTION_AVAILABLE=true
    echo "✅ SageAttention build completed successfully"
else
    echo "⚠️  SageAttention build failed. Launching ComfyUI without --use-sage-attention flag"
fi

URL="http://127.0.0.1:8188"
COMFYUI_CMD="python3 $COMFYUI_DIR/main.py --listen --enable-cors-header '*' $EXTRA_PATHS_FLAG"
if [ "$SAGE_ATTENTION_AVAILABLE" = "true" ]; then
    COMFYUI_CMD="$COMFYUI_CMD --use-sage-attention"
fi

nohup $COMFYUI_CMD > "$NETWORK_VOLUME/comfyui_${RUNPOD_POD_ID}_nohup.log" 2>&1 &
until curl --silent --fail "$URL" --output /dev/null; do
    echo "🔄  ComfyUI Starting Up... You can view the startup logs here: $NETWORK_VOLUME/comfyui_${RUNPOD_POD_ID}_nohup.log"
    sleep 2
done
echo "🚀 ComfyUI is ready"
sleep infinity
