# shellcheck shell=bash
# Sourced by the runtime before provisioning. Never exit or fail the whole boot.
klein3_preflight() {
    local requested
    requested="$(printf '%s' "${DOWNLOAD_KLEIN3:-}" | tr '[:upper:]' '[:lower:]' | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
    case "$requested" in
        1|true|yes|on) ;;
        *) return 0 ;;
    esac
    # The downloader uses the same explicit HF_TOKEN, never a cached login.
    export HF_TOKEN="${HF_TOKEN:-}"
    export HF_TOKEN="${HF_TOKEN#"${HF_TOKEN%%[![:space:]]*}"}"
    export HF_TOKEN="${HF_TOKEN%"${HF_TOKEN##*[![:space:]]}"}"
    if python3 "$TEMPLATE_DIR/src/klein3_preflight.py"; then
        echo "[Klein 3] Preflight passed; enabling models and workflows."
    else
        export DOWNLOAD_KLEIN3=false
        echo "ERROR [Klein 3]: Skipping Klein 3 downloads and workflows for this boot. Continuing template setup."
        if declare -F report_off >/dev/null; then
            report_off "Flux Klein 3" "Preflight failed; see the Klein 3 error in /workspace/comfyui.log. Accept the model license, set HF_TOKEN with gated read access, and use a ComfyUI version supporting FLUX.3. Restart to retry."
        fi
    fi
    return 0
}
klein3_preflight
unset -f klein3_preflight
