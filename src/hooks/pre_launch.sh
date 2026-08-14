#!/usr/bin/env bash
# pre_launch hook (CONTRACTS.md section 7). Sourced by the runtime immediately
# before ComfyUI launches. Must not call exit; use return.
#
# ComfyUI-HMNodes is a PRIVATE pack behind GITHUB_PAT. The migration dropped it
# because no SHIPPED workflow references a type it registers, which was the
# wrong test: it is used by paid workflows customers add themselves, and those
# never appear in this repo. Same class of miss as wan's rife426.
#
# It stays out of template.json custom_nodes on purpose. The runtime's clone
# loop reads URLs verbatim from JSON with no env expansion, so a
# "https://${GITHUB_PAT}@..." entry would be cloned literally and 404.
#
# No PAT set is the normal case for a customer: say so once and move on.

HMNODES_DIR="$CUSTOM_NODES_DIR/ComfyUI-HMNodes"

if [ -z "${GITHUB_PAT:-}" ]; then
    echo "⏭️  GITHUB_PAT not set. Skipping the private ComfyUI-HMNodes pack."
elif [ -d "$HMNODES_DIR/.git" ]; then
    echo "🔄 Updating ComfyUI-HMNodes..."
    git -C "$HMNODES_DIR" pull --ff-only --quiet 2>/dev/null \
        || echo "⚠️  ComfyUI-HMNodes pull failed. Keeping the existing checkout."
else
    echo "📥 Cloning the private ComfyUI-HMNodes pack..."
    # Redirect stderr: a bad PAT makes git echo the URL, token included.
    if git clone --quiet \
        "https://${GITHUB_PAT}@github.com/Hearmeman24/ComfyUI-HMNodes.git" \
        "$HMNODES_DIR" 2>/dev/null; then
        echo "✅ ComfyUI-HMNodes cloned"
    else
        echo "⚠️  ComfyUI-HMNodes clone failed. Check that GITHUB_PAT is valid and has read access."
        report_warn "ComfyUI-HMNodes clone failed; paid workflows using its nodes will show red nodes"
    fi
fi

# Scrub the token out of .git/config either way (CLAUDE.md section 5): a clone
# URL with credentials is persisted there, on the customer's volume, in clear.
if [ -d "$HMNODES_DIR/.git" ]; then
    git -C "$HMNODES_DIR" remote set-url origin \
        "https://github.com/Hearmeman24/ComfyUI-HMNodes.git" 2>/dev/null || true
    if grep -q "@github.com" "$HMNODES_DIR/.git/config" 2>/dev/null; then
        echo "⚠️  Could not scrub the credential from ComfyUI-HMNodes/.git/config"
        report_warn "A GITHUB_PAT remained in ComfyUI-HMNodes/.git/config"
    fi
    if [ -f "$HMNODES_DIR/requirements.txt" ]; then
        pip install -r "$HMNODES_DIR/requirements.txt" > /tmp/hmnodes_pip.log 2>&1 \
            || { echo "⚠️  ComfyUI-HMNodes requirements install failed (see /tmp/hmnodes_pip.log)."
                 report_warn "ComfyUI-HMNodes requirements install failed"; }
    fi
fi
