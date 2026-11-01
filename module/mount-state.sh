#!/system/bin/sh
# Records the binds this module creates, so a later boot only releases its own top mounts.
#
# Why not scan mountinfo by path prefix: /odm/etc/camera is shared with whatever else the user runs
# (another camera module, a layout guard, a manual bind). Unmounting every entry under a prefix takes
# those with it; the POP preview then loses basictone/meishe_lut and the viewfinder locks up. This
# file keeps (source, target) pairs we mounted ourselves and releases only those that are still the
# top mount at that target.
#
# Wire format: one "source<TAB>target" pair per line, newest first.

MOUNTINFO=${MOUNTINFO:-/proc/self/mountinfo}
MOUNT_STATE_FILE=${MOUNT_STATE_FILE:-$MODDIR/mounted-targets}
MOUNTED_TARGETS=

ms_log() {
    [ -n "${LOG:-}" ] && echo "$1" >> "$LOG"
    return 0
}

mount_state_reset() {
    rm -f "$MOUNT_STATE_FILE" "$MOUNT_STATE_FILE.tmp"
    MOUNTED_TARGETS=
}

mount_state_record() {
    MOUNT_SOURCE=$1
    MOUNT_TARGET=$2
    MOUNTED_TARGETS="$MOUNT_SOURCE	$MOUNT_TARGET
$MOUNTED_TARGETS"
    printf '%s' "$MOUNTED_TARGETS" > "$MOUNT_STATE_FILE.tmp" && mv "$MOUNT_STATE_FILE.tmp" "$MOUNT_STATE_FILE"
}

# True when $2 is currently a bind whose source root is $1. /data is its own filesystem on this
# device, so mountinfo reports the root without the /data prefix; both spellings are accepted.
mount_state_owned() {
    MOUNT_SOURCE=$1
    MOUNT_TARGET=$2
    case "$MOUNT_SOURCE" in
        /data/*) MOUNT_ROOT=${MOUNT_SOURCE#/data} ;;
        *) MOUNT_ROOT=$MOUNT_SOURCE ;;
    esac
    # mountinfo: id parent maj:min root mountpoint opts ... - fstype source superopts. The bind's
    # source shows up as the root field ($4), spelled without the /data prefix.
    # A bind whose source directory was replaced while it was mounted keeps the old inode and shows up
    # as "...//deleted"; treat that as ours too, otherwise the next run cannot release it and the merge
    # then copies from an empty tree.
    awk -v target="$MOUNT_TARGET" -v root_a="$MOUNT_ROOT" -v root_b="$MOUNT_SOURCE" '
        $5 == target {
            if ($4 == root_a || $4 == root_b) hit = 1
            if ($4 == root_a "//deleted" || $4 == root_b "//deleted") hit = 1
        }
        END { exit(hit ? 0 : 1) }
    ' "$MOUNTINFO"
}

# Releases every recorded bind that is still ours, newest first. Leaves foreign mounts alone.
mount_state_release() {
    [ -f "$MOUNT_STATE_FILE" ] || return 0
    while IFS='	' read -r MOUNT_SOURCE MOUNT_TARGET; do
        [ -n "${MOUNT_TARGET:-}" ] || continue
        if mount_state_owned "$MOUNT_SOURCE" "$MOUNT_TARGET"; then
            if umount -l "$MOUNT_TARGET" >> "${LOG:-/dev/null}" 2>&1; then
                ms_log "release $MOUNT_TARGET"
            else
                ms_log "release FAIL $MOUNT_TARGET"
            fi
        else
            ms_log "release skip $MOUNT_TARGET (not ours or already gone)"
        fi
    done < "$MOUNT_STATE_FILE"
    mount_state_reset
}
