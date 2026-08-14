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
# Packs the PAID workflows need that no shipped workflow references, so the
# node cull correctly removed them from the image. A valid GITHUB_PAT is the
# only signal that this pod belongs to a paid customer, so they are installed
# only when the private pack resolved. Everyone else pays nothing for them.
PAID_PACKS=("https://github.com/chflame163/ComfyUI_LayerStyle_Advance.git")
HMNODES_OK=0

if [ -z "${GITHUB_PAT:-}" ]; then
    echo "ℹ️  No GITHUB_PAT set, so the optional HearmemanAI node pack is skipped. This is normal and everything in this template works without it."
elif [ -d "$HMNODES_DIR/.git" ]; then
    echo "🔄 Updating ComfyUI-HMNodes..."
    git -C "$HMNODES_DIR" pull --ff-only --quiet 2>/dev/null \
        || echo "⚠️  ComfyUI-HMNodes pull failed. Keeping the existing checkout."
    HMNODES_OK=1
else
    echo "📥 Cloning the private ComfyUI-HMNodes pack..."
    # Redirect stderr: a bad PAT makes git echo the URL, token included.
    if git clone --quiet \
        "https://${GITHUB_PAT}@github.com/Hearmeman24/ComfyUI-HMNodes.git" \
        "$HMNODES_DIR" 2>/dev/null; then
        echo "✅ ComfyUI-HMNodes cloned"
        HMNODES_OK=1
    else
        echo "ℹ️  Could not fetch the optional HearmemanAI node pack. Everything in this template still works. If you bought the add-on workflows, check your GITHUB_PAT; otherwise ignore this."
        report_warn "Optional HearmemanAI node pack unavailable (only affects the paid add-on workflows)"
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

# Paid-workflow packs, gated on the PAT having actually resolved. A PAT that is
# set but invalid leaves HMNODES_OK at 0 and installs nothing: the workflows
# would be broken anyway without HMNodes, so adding a heavy pack on top helps
# nobody.
if [ "$HMNODES_OK" = "1" ]; then
    for repo in "${PAID_PACKS[@]}"; do
        name="$(basename "$repo" .git)"
        dir="$CUSTOM_NODES_DIR/$name"
        if [ -d "$dir/.git" ]; then
            echo "🔄 Updating $name (paid workflows)..."
            git -C "$dir" pull --ff-only --quiet 2>/dev/null \
                || echo "⚠️  $name pull failed. Keeping the existing checkout."
            continue
        fi
        echo "📥 Cloning $name for the paid workflows..."
        if git clone --quiet "$repo" "$dir"; then
            if [ -f "$dir/requirements.txt" ]; then
                pip install -r "$dir/requirements.txt" > "/tmp/${name}_pip.log" 2>&1 \
                    || { echo "⚠️  $name requirements install failed (see /tmp/${name}_pip.log)."
                         report_warn "$name requirements install failed"; }
            fi
        else
            echo "ℹ️  Could not fetch $name, an optional pack for the paid add-on workflows. The bundled workflows are unaffected."
            report_warn "Optional pack $name unavailable (only affects the paid add-on workflows)"
        fi
    done

    # This hook runs AFTER the runtime's onnxruntime-gpu reassert
    # (comfyui-runtime/src/start.sh:616), and LayerStyle_Advance pins plain
    # onnxruntime (CPU) at requirements.txt:30. Without this, a paid pod would
    # silently fall back to CPU inference for every onnx model on the box, with
    # nothing left in the boot to notice.
    if ! python3 -c 'import onnxruntime as o, sys; sys.exit(0 if "CUDAExecutionProvider" in o.get_available_providers() else 1)' 2>/dev/null; then
        echo "⚙️  A paid pack clobbered onnxruntime-gpu. Reinstalling..."
        report_warn "A paid-workflow pack replaced onnxruntime-gpu; it was reinstalled at boot"
        pip uninstall -y onnxruntime onnxruntime-gpu > /dev/null 2>&1 || true
        if [ "${TORCH_CUDA_MAJOR:-13}" = "13" ]; then
            pip install onnxruntime-gpu > /tmp/ort_reassert.log 2>&1
        else
            pip install onnxruntime-gpu \
                --index-url https://aiinfra.pkgs.visualstudio.com/PublicPackages/_packaging/onnxruntime-cuda-12/pypi/simple/ \
                > /tmp/ort_reassert.log 2>&1
        fi
        python3 -c 'import onnxruntime as o, sys; sys.exit(0 if "CUDAExecutionProvider" in o.get_available_providers() else 1)' 2>/dev/null \
            && echo "✅ onnxruntime-gpu restored" \
            || { echo "❌ onnxruntime-gpu could not be restored (see /tmp/ort_reassert.log)."
                 report_warn "onnxruntime-gpu could not be restored after a paid pack install"; }
    fi
fi
