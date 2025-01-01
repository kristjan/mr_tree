#!/bin/bash

CIRCUITPY="/Volumes/CIRCUITPY/"
HOMEASSISTANT="/Volumes/config/custom_components/mr_tree/"
TREE_SRC="tree/"
HA_SRC="home_assistant/"
EXCLUDES="--exclude='settings.toml' --exclude='boot_out.txt' --exclude='.Trashes' --exclude='.fseventsd' --exclude='.Spotlight*' --exclude='.DS_Store'"
RSYNC_BASE="rsync --inplace --no-times --no-perms --chmod=ugo=rwX --out-format='[%i] %n'"

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

# Get absolute paths of source directories
TREE_SRC_ABS=$(cd "${TREE_SRC}" && pwd)
HA_SRC_ABS=$(cd "${HA_SRC}" && pwd)

debug "Starting watch on ${TREE_SRC} and ${HA_SRC}"
COPYFILE_DISABLE=1 fswatch -0 ${TREE_SRC} ${HA_SRC} | while IFS= read -r -d '' f; do
    debug "Detected change in: $f"

    if [ -f "$f" ]; then
        # Determine which source directory the file belongs to and sync accordingly
        if [[ "$f" == "$TREE_SRC_ABS"* ]]; then
            sync_file "${TREE_SRC}" "${CIRCUITPY}" "$f" "$TREE_SRC_ABS"
        elif [[ "$f" == "$HA_SRC_ABS"* ]]; then
            sync_file "${HA_SRC}" "${HOMEASSISTANT}" "$f" "$HA_SRC_ABS"
        fi
    else
        debug "File $f no longer exists, skipping rsync"
    fi
done