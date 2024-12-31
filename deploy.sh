#!/bin/bash

DEST="/Volumes/CIRCUITPY/"
SRC="tree/"
EXCLUDES="--exclude='settings.toml' --exclude='boot_out.txt' --exclude='.Trashes' --exclude='.fseventsd' --exclude='.Spotlight*' --exclude='.DS_Store'"
RSYNC_BASE="rsync --inplace --no-times --no-perms --chmod=ugo=rwX --out-format='[%i] %n'"

debug() {
    echo "[$(date +%H:%M:%S.%N)] $1" >&2
}

# Get absolute path of source directory
SRC_ABS=$(cd "${SRC}" && pwd)

debug "Starting watch on ${SRC}"
COPYFILE_DISABLE=1 fswatch -0 ${SRC} | while IFS= read -r -d '' f; do
    debug "Detected change in: $f"

    if [ -f "$f" ]; then
        # Convert absolute path to relative
        rel_path=${f#"$SRC_ABS/"}
        debug "Starting rsync for ${rel_path}"
        eval "${RSYNC_BASE} ${EXCLUDES} \"${SRC}${rel_path}\" \"${DEST}${rel_path}\"" | grep '^\[>f' | cut -d] -f2-
        debug "Rsync complete"
    else
        debug "File $f no longer exists, skipping rsync"
    fi
done