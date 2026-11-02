"""Builds the per-device audio_policy_volumes.xml payload copies (bind-mounted over /odm/etc/audio/).

Change against each device's own stock table: STREAM_SYSTEM_ENFORCED (the forced shutter sound
stream that ShutterSound plays on in silent/vibrate mode) uses the system volume curve on the
speaker, as the file's own JP-version branch does. The CN branch caps it at -24 dB, which is
barely audible; the system curve peaks at -5 dB, the stock shutter loudness in normal mode.
Everything else stays that device's stock, so the two tables are never interchangeable:
post-fs-data.sh picks the copy by profile.

  x9u  inputs/stock_audio/...     -> module/payload/audio_policy_volumes.xml
  x8u  inputs/stock_audio_x8u/... -> module/payload/x8u/audio_policy_volumes.xml
"""
from __future__ import annotations

from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent

DEVICES = {
    "x9u": (PROJECT / "inputs/stock_audio/audio_policy_volumes.xml",
            PROJECT / "module/payload/audio_policy_volumes.xml"),
    "x8u": (PROJECT / "inputs/stock_audio_x8u/audio_policy_volumes.xml",
            PROJECT / "module/payload/x8u/audio_policy_volumes.xml"),
}

CN_SPEAKER = """    <volume stream="AUDIO_STREAM_ENFORCED_AUDIBLE" deviceCategory="DEVICE_CATEGORY_SPEAKER">
        <point>1,-3500</point>
        <point>33,-3100</point>
        <point>66,-2700</point>
        <point>100,-2400</point>
    </volume>
"""
SYSTEM_SPEAKER = """    <volume stream="AUDIO_STREAM_ENFORCED_AUDIBLE" deviceCategory="DEVICE_CATEGORY_SPEAKER"
                                                   ref="DEFAULT_SYSTEM_VOLUME_CURVE"/>
"""


def main() -> None:
    for profile, (stock, output) in DEVICES.items():
        text = stock.read_text(encoding="utf-8")
        if text.count(CN_SPEAKER) != 1:
            raise RuntimeError("%s: stock enforced speaker curve changed; review the patch" % profile)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text.replace(CN_SPEAKER, SYSTEM_SPEAKER), encoding="utf-8", newline="\n")
        print("%s audio volumes: enforced speaker curve -> DEFAULT_SYSTEM_VOLUME_CURVE" % profile)


if __name__ == "__main__":
    main()
