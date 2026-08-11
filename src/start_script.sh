#!/usr/bin/env bash
set -e

REPO_DIR=/comfyui-qwen-template
REPO_URL=https://github.com/Hearmeman24/comfyui-qwen-template.git
REPO_BRANCH=master

# RunPod's Global Networking option blocks outbound traffic from the pod, DNS
# included. Without this check the clone below is the first thing to notice, and
# it reports "Could not resolve host: github.com" - which sends people to look at
# GitHub instead of at the pod setting. One host answering means the network is
# up, so a single host being down on its own is not a failure here.
network_works() {
    for host in github.com huggingface.co; do
        curl --silent --head --max-time 5 "https://$host" >/dev/null 2>&1 && return 0
    done
    return 1
}

if ! network_works; then
    cat >&2 <<'EOF'

================================================================================
This pod has no outbound network. It cannot reach github.com or huggingface.co,
so nothing can be cloned or downloaded and ComfyUI will not start.

Almost always this means Global Networking is enabled on the pod.

To fix it: terminate this pod and deploy it again with Global Networking
switched off. The toggle is in the RunPod deploy form, in the same section as
the network volume and the exposed ports.

Nothing is wrong with GitHub or with the template.
================================================================================

EOF
    exit 1
fi

if [ -d "$REPO_DIR/.git" ]; then
    git -C "$REPO_DIR" fetch --depth=1 origin "$REPO_BRANCH"
    git -C "$REPO_DIR" reset --hard "origin/$REPO_BRANCH"
else
    rm -rf "$REPO_DIR"
    git clone --depth=1 --branch "$REPO_BRANCH" "$REPO_URL" "$REPO_DIR"
fi

set +e
cp -f "$REPO_DIR/src/start.sh" /start.sh
chmod +x /start.sh
bash /start.sh
