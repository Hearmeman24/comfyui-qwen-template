#!/usr/bin/env bash
set -e

REPO_DIR=/comfyui-qwen-template
REPO_URL=https://github.com/Hearmeman24/comfyui-qwen-template.git
REPO_BRANCH=master

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
