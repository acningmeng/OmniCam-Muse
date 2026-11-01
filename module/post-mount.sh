#!/system/bin/sh
# Binds the module's /odm/lib64 replacements. Every entry is optional: a device that ships its own
# build of a library (Find X8 Ultra has no libBasicTonePhotoX9/X10 at all) simply keeps the stock
# one, instead of aborting the whole script the way `set -e` used to.
set -u
MODDIR=${0%/*}
LOG=$MODDIR/bind.log

log() { echo "$1" >> "$LOG"; }

bind_library() {
    NAME=$1
    SOURCE="$MODDIR/system/odm/lib64/$NAME"
    TARGET="/odm/lib64/$NAME"
    if [ ! -f "$SOURCE" ]; then
        log "skip $NAME (module has no $SOURCE)"
        return 0
    fi
    if [ ! -f "$TARGET" ]; then
        log "skip $NAME (target device has no $TARGET)"
        return 0
    fi
    chown root:root "$SOURCE"
    chmod 0644 "$SOURCE"
    chcon u:object_r:same_process_hal_file:s0 "$SOURCE" 2>>"$LOG" || true
    if mount --bind "$SOURCE" "$TARGET" >>"$LOG" 2>&1; then
        log "lib bind ok $TARGET"
    else
        log "lib bind FAIL $TARGET"
    fi
}

: > "$LOG"
log "begin"

# X9 Ultra only: libBasicTonePhoto.so is a router that dlopens libBasicTonePhotoX9/X10.so, so it is
# pointless (and breaks the palette) on a device that has neither file.
if [ -f /odm/lib64/libBasicTonePhotoX9.so ]; then
    bind_library libBasicTonePhotoX9.so
    bind_library libBasicTonePhotoX10.so
    bind_library libBasicTonePhoto.so
fi

# The grain trampolines in tools/patch_grain_gate.py are hand-placed for the X9 Ultra build of
# libAlgoInterface.so; on a different build the offsets land in unrelated code. Touch
# $MODDIR/enable_algo_interface once the patch has been re-derived for this device.
if [ -f "$MODDIR/enable_algo_interface" ]; then
    bind_library libAlgoInterface.so
else
    log "skip libAlgoInterface.so (no enable_algo_interface marker)"
fi
log "end"
