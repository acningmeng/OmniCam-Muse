#!/system/bin/sh
# x8u_selftest.sh - read-only checks for the layered X8U port. Nothing here writes to /odm,
# restarts a process, or touches LSPosed: run it as root (su -c 'sh /data/local/tmp/x8u_selftest.sh <cmd>').
#
#   gate     device profile, firmware, camera version, module markers
#   hooks    whether the LSPosed module is injected into camera and gallery
#   mounts   which of our binds are live, and whether the merged dirs look complete
#   shoot    media counter before/after one shutter press (needs a human to press, or an awake screen)
#   all      gate + hooks + mounts
#
# Exit code: 0 when every executed check passes, 1 otherwise.

MODDIR=${MODDIR:-/data/adb/modules/ricoh_pop_x9u}
FAIL=0

say()  { echo "$1"; }
ok()   { echo "  [ok]   $1"; }
warn() { echo "  [warn] $1"; }
bad()  { echo "  [FAIL] $1"; FAIL=1; }

cfg() { echo "$1"; }

profile() {
    MODEL=$(getprop ro.product.model)
    FW=$(getprop ro.build.display.id)
    CAM=$(dumpsys package com.oplus.camera 2>/dev/null | grep -m1 versionName | tr -d ' ')
    case "$MODEL" in
        PKU110|PKJ110) P=x8u ;;
        PMA110)        P=x9u ;;
        *)             P=unknown ;;
    esac
    say "device: model=$MODEL profile=$P firmware=$FW $CAM"
    [ "$P" = "unknown" ] && bad "unknown model, config layers must stay off"
    for m in enable_config_binds enable_algo_switch enable_occ_extras enable_legacy_configs enable_composition; do
        [ -f "$MODDIR/$m" ] && say "  marker: $m"
    done
    return 0
}

hooks() {
    say "hooks:"
    for pkg in com.oplus.camera com.coloros.gallery3d; do
        # grep -c with several files prints "file:count"; sum the counts instead of taking the last line.
        N=$(grep -h -c "($pkg)\[local.jiege.camera" /data/adb/lspd/log/verbose_*.log 2>/dev/null | awk '{s+=$1} END{print s+0}')
        [ -n "$N" ] && [ "$N" -gt 0 ] && ok "$pkg injected ($N frames)" || bad "$pkg not injected"
    done
    # Injection only proves LSPosed loaded the module. These lines prove each group's install() actually ran,
    # which is what the layer markers gate. Missing ones are warnings: a marker can legitimately switch a group off.
    for tag in "FeatureModeCompat: installed" "PopPort: POP SDR style hook installed" \
               "MasterColor: installed" "CompositionBridge" "FeatureModeCompat: empty operation table"; do
        N=$(grep -h -c "$tag" /data/adb/lspd/log/modules_*.log 2>/dev/null | awk '{s+=$1} END{print s+0}')
        [ -n "$N" ] && [ "$N" -gt 0 ] && ok "log: $tag ($N)" || warn "log line not seen: $tag"
    done
    return 0
}

mounted() { # path -> prints "bound" or "stock"; field 5 is the mount point, nothing else matches
    if awk -v p="$1" '$5==p{found=1} END{exit !found}' /proc/self/mountinfo 2>/dev/null; then
        echo bound
    else
        echo stock
    fi
}

mounts() {
    say "mounts:"
    for f in camera_unit_config camera_unit_feature_config.protobuf oplus_camera_algo_switch_config oplus_camera_config; do
        echo "  $f: $(mounted /odm/etc/camera/config/$f)"
    done
    echo "  basictone dirs: $(ls /odm/etc/camera/basictone 2>/dev/null | wc -l)"
    echo "  meishe_lut files: $(ls /odm/etc/camera/meishe_lut 2>/dev/null | wc -l)"
    [ "$(ls /odm/etc/camera/meishe_lut 2>/dev/null | wc -l)" -gt 100 ] && ok "meishe_lut complete" || bad "meishe_lut looks short"
    [ -d /odm/etc/camera/basictone/lmt ] && ok "basictone/lmt present" || bad "basictone/lmt missing"
    # A marker without a live bind means the layer was declared but the boot script did not apply it.
    [ -f "$MODDIR/enable_config_binds" ] && [ "$(mounted /odm/etc/camera/config/camera_unit_config)" = stock ] \
        && warn "enable_config_binds present but camera_unit_config is stock"
    [ -f "$MODDIR/enable_algo_switch" ] && [ "$(mounted /odm/etc/camera/config/oplus_camera_algo_switch_config)" = stock ] \
        && warn "enable_algo_switch present but the APS table is stock"
    return 0
}

shoot() {
    MODE=${1:-photo}
    B=$(content query --uri content://media/external/images/media --projection _id --sort 'date_added DESC' 2>/dev/null | head -1)
    say "mode requested: $MODE (check the viewfinder: the shutter coordinates come from the live layout)"
    say "media head before: $B"

    # Take the shutter rectangle from the running UI instead of hard-coding it: the pill moves between
    # photo / POP / GR layouts, and a stale pair of coordinates silently taps empty canvas.
    uiautomator dump /data/local/tmp/selftest.xml >/dev/null 2>&1
    XY=$(sed -n 's/.*resource-id="com.oplus.camera:id\/shutter_button"[^>]*bounds="\[\([0-9]*\),\([0-9]*\)\]\[\([0-9]*\),\([0-9]*\)\]".*/\1 \2 \3 \4/p' \
         /data/local/tmp/selftest.xml 2>/dev/null | head -1)
    if [ -n "$XY" ]; then
        set -- $XY
        X=$(( ($1 + $3) / 2 )); Y=$(( ($2 + $4) / 2 ))
        say "shutter at $X,$Y from uiautomator"
    else
        X=2584; Y=720
        warn "shutter node not found, falling back to the photo-mode centre $X,$Y"
    fi

    C0=$(logcat -d -b main 2>/dev/null | grep -c "CMD_PRE_CAPTURE")
    input tap "$X" "$Y"
    sleep 6
    A=$(content query --uri content://media/external/images/media --projection _id --sort 'date_added DESC' 2>/dev/null | head -1)
    C1=$(logcat -d -b main 2>/dev/null | grep -c "CMD_PRE_CAPTURE")
    say "media head after:  $A   (pre-capture lines $C0 -> $C1)"
    [ "$B" != "$A" ] && ok "capture landed" || bad "no new media row"
    [ "$C1" -gt "$C0" ] || warn "the camera did not even ask for a pre-capture: the tap missed or the UI is not ready"
    return 0
}

case "${1:-all}" in
    gate)   profile ;;
    hooks)  hooks ;;
    mounts) mounts ;;
    shoot)  shoot "${2:-photo}" ;;
    all)    profile; hooks; mounts ;;
    *)      say "usage: $0 {gate|hooks|mounts|shoot [photo|pop|gr]|all}"; exit 2 ;;
esac
exit $FAIL
