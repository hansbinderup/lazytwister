#!/usr/bin/env bash
# Uninstall lazytwister installed by install.sh.
#
#   curl -fsSL https://raw.githubusercontent.com/hansbinderup/lazytwister/main/uninstall.sh | bash
#
# or from a clone:  ./uninstall.sh
#
# Removes ~/.local/share/lazytwister and the ~/.local/bin/lazytwister link.
# With --purge, also removes lazytwister's cache (~/.cache/lazytwister: test
# results, twister build output and the remembered test folders).
# Uses the same LAZYTWISTER_HOME / LAZYTWISTER_BIN_DIR overrides as install.sh.

main() {
    set -euo pipefail

    local home="${LAZYTWISTER_HOME:-${XDG_DATA_HOME:-$HOME/.local/share}/lazytwister}"
    local bin_dir="${LAZYTWISTER_BIN_DIR:-$HOME/.local/bin}"
    local cache="${XDG_CACHE_HOME:-$HOME/.cache}/lazytwister"
    local purge=0

    local arg
    for arg in "$@"; do
        case "$arg" in
            --purge) purge=1 ;;
            -h|--help) sed -n '2,12s/^# \{0,1\}//p' "${BASH_SOURCE[0]:-/dev/null}" 2>/dev/null ||
                           echo "usage: uninstall.sh [--purge]"; return 0 ;;
            *) echo "unknown option: $arg (usage: uninstall.sh [--purge])" >&2; return 1 ;;
        esac
    done

    local removed=0
    local link="$bin_dir/lazytwister"
    # Only remove the command if it is our link, not some other lazytwister.
    if [[ -L "$link" && "$(readlink "$link")" == "$home/"* ]]; then
        rm -f "$link"
        echo "removed $link"
        removed=1
    elif [[ -e "$link" ]]; then
        echo "left $link alone: it is not a link into $home"
    fi

    # Only remove what install.sh created: the venv link and venv-* directories,
    # then the directory itself if that leaves it empty.
    local venv
    for venv in "$home/venv" "$home"/venv-*; do
        [[ -e "$venv" || -L "$venv" ]] || continue
        rm -rf "$venv"
        echo "removed $venv"
        removed=1
    done
    rmdir "$home" 2>/dev/null || true

    if [[ "$purge" == 1 && -d "$cache" ]]; then
        rm -rf "$cache"
        echo "removed $cache"
        removed=1
    elif [[ -d "$cache" ]]; then
        echo "kept the cache in $cache (results and build output; --purge removes it)"
    fi

    if [[ "$removed" == 0 ]]; then
        echo "lazytwister is not installed in $home"
    fi
}

main "$@"
