"""Round-trip check for tools/oplus_config.py.

The envelope is 01 01 + salt + AES-ECB(pkcs7 text) + salt + ff. Two properties matter and neither
is visible in a build log: encode(decode(x)) must return x exactly, and the salt must be derived
from the text so that regenerating a table twice produces identical bytes.
"""
import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import oplus_config

TEXT = '{\n    "file_version": "15.003",\n    "aps_version": 6\n}\n'


def main() -> int:
    salt, tail = oplus_config.salt_for(TEXT)
    first = oplus_config.encode(TEXT, salt=salt, tail=tail)
    second = oplus_config.encode(TEXT, salt=salt, tail=tail)
    checks = [
        ("envelope magic", first[:2] == oplus_config.MAGIC),
        ("envelope terminator", first[-1] == 0xFF),
        ("deterministic salt", first == second),
        ("round trip", oplus_config.decode(first) == TEXT),
        ("plain passthrough", oplus_config.decode(TEXT.encode()) == TEXT),
        ("not enveloped", not oplus_config.is_enveloped(TEXT.encode())),
        ("sha256 salt", salt + tail == hashlib.sha256(TEXT.encode()).digest()[:5]),
    ]
    bad = [name for name, ok in checks if not ok]
    for name, ok in checks:
        print(f"  [{'ok' if ok else 'FAIL'}] {name}")
    print("envelope_roundtrip: " + ("ok" if not bad else "FAILED " + ", ".join(bad)))
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
