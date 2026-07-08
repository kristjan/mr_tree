#!/bin/bash

# Usage:
#   ./deploy.sh            # watch tree/ and sync changed files continuously (default)
#   ./deploy.sh --watch    # same as above
#   ./deploy.sh --once      # sync all of tree/ to the board once, then exit

CIRCUITPY="/Volumes/CIRCUITPY/"
TREE_SRC="tree/"
EXCLUDES="--exclude='settings.toml' --exclude='boot_out.txt' --exclude='.Trashes' --exclude='.fseventsd' --exclude='.Spotlight*' --exclude='.DS_Store' --exclude='__pycache__' --exclude='*.pyc'"
RSYNC_BASE="rsync --inplace --no-times --no-perms --chmod=ugo=rwX --out-format='[%i] %n'"

MODE="watch"
case "$1" in
    --once|once) MODE="once" ;;
    --watch|watch|"") MODE="watch" ;;
    *) echo "Usage: $0 [--once|--watch]" >&2; exit 2 ;;
esac

debug() {
    echo "[$(date +%H:%M:%S.%N)] $1" >&2
}

sync_file() {
    local src=$1
    local dest=$2
    local file=$3
    local src_abs=$4

    if [ -d "$dest" ]; then
        # Convert absolute path to relative
        rel_path=${file#"$src_abs/"}
        debug "Starting rsync for ${rel_path} to ${dest}"
        eval "${RSYNC_BASE} ${EXCLUDES} \"${src}${rel_path}\" \"${dest}${rel_path}\"" | grep '^\[>f' | cut -d] -f2-
        debug "Rsync complete"
    fi
}

sync_all() {
    if [ ! -d "$CIRCUITPY" ]; then
        debug "CIRCUITPY not mounted at ${CIRCUITPY}; aborting"
        exit 1
    fi
    debug "Syncing all of ${TREE_SRC} to ${CIRCUITPY}"
    eval "${RSYNC_BASE} -r ${EXCLUDES} \"${TREE_SRC}\" \"${CIRCUITPY}\"" | grep '^\[>f' | cut -d] -f2-
    debug "Full sync complete"
}

if [ "$MODE" = "once" ]; then
    sync_all
    exit 0
fi

# Watch mode
TREE_SRC_ABS=$(cd "${TREE_SRC}" && pwd)

debug "Starting watch on ${TREE_SRC}"
COPYFILE_DISABLE=1 fswatch -0 ${TREE_SRC} | while IFS= read -r -d '' f; do
    debug "Detected change in: $f"

    if [ -f "$f" ]; then
        if [[ "$f" == "$TREE_SRC_ABS"* ]]; then
            sync_file "${TREE_SRC}" "${CIRCUITPY}" "$f" "$TREE_SRC_ABS"
        fi
    else
        debug "File $f no longer exists, skipping rsync"
    fi
done
