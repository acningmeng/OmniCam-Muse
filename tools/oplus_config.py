"""Reader/writer for OPPO's encrypted camera config files.

Four scripts used to carry their own copy of this logic (two of them hard-coded the key, one
derived it from libOplusSecurity.so, one imported the derivation from another module), which is
one refactor away from disagreeing on the envelope. This module is the single source of truth.

Layout
------
    b"\\x01\\x01" + 2 salt bytes + AES-128-ECB(pkcs7(utf-8 text)) + 3 salt bytes + b"\\xff"

The five salt bytes are random, not a checksum: re-wrapping unchanged plaintext reproduces the
original bytes exactly, so they carry no integrity check. A file that does not start with
b"\\x01\\x01" is already plain text and is returned as is (several payload tables ship that way).

Key
---
The device derives it from /odm/lib64/libOplusSecurity.so: 32 bytes at offset 0x7AB, XOR 0x3F,
then every second byte. The result is identical on the Find X9 Ultra and the Find X8 Ultra, so
DEFAULT_KEY works for both; `key_from_security()` recomputes it from a dump when in doubt.
"""

from __future__ import annotations

import os
from pathlib import Path

from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad

ENVELOPE_HEAD = 4
ENVELOPE_TAIL = 4
MAGIC = b"\x01\x01"
DEFAULT_KEY = bytes.fromhex("6f2170406c247525535e4326412a4d28")
SECURITY_OFFSET = 0x7AB


def key_from_security(path: Path) -> bytes:
    """Derive the AES key from libOplusSecurity.so."""
    blob = Path(path).read_bytes()
    chunk = blob[SECURITY_OFFSET:SECURITY_OFFSET + 32]
    if len(chunk) != 32:
        raise ValueError(f"{path}: too short for the key at 0x{SECURITY_OFFSET:x}")
    return bytes(byte ^ 0x3F for byte in chunk)[::2]


def is_enveloped(raw: bytes) -> bool:
    return raw[:2] == MAGIC


def decode(raw: bytes, key: bytes = DEFAULT_KEY) -> str:
    if not is_enveloped(raw):
        return raw.decode("utf-8")
    body = raw[ENVELOPE_HEAD:len(raw) - ENVELOPE_TAIL]
    plain = unpad(AES.new(key, AES.MODE_ECB).decrypt(body), 16)
    return plain.decode("utf-8")


def encode(text: str, key: bytes = DEFAULT_KEY, salt: bytes | None = None,
           tail: bytes | None = None) -> bytes:
    """Wrap text in the envelope. Salt/tail default to fresh random bytes."""
    salt = os.urandom(2) if salt is None else salt
    tail = os.urandom(3) if tail is None else tail
    body = AES.new(key, AES.MODE_ECB).encrypt(pad(text.encode("utf-8"), 16))
    return MAGIC + salt + body + tail + b"\xff"


def read(path: Path, key: bytes = DEFAULT_KEY) -> str:
    return decode(Path(path).read_bytes(), key)


def write(path: Path, text: str, key: bytes = DEFAULT_KEY, envelope: bool = False) -> int:
    """Write text as plain UTF-8, or wrapped when envelope=True. Returns the byte count."""
    data = encode(text, key) if envelope else text.encode("utf-8")
    Path(path).write_bytes(data)
    return len(data)


# ---------------------------------------------------------------- JSON with OPPO's quirks

def strip_comments(text: str) -> str:
    """Drop // line comments while respecting string literals."""
    out: list[str] = []
    index, size, in_string, escaped = 0, len(text), False, False
    while index < size:
        char = text[index]
        if in_string:
            out.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            index += 1
            continue
        if char == '"':
            in_string = True
            out.append(char)
            index += 1
            continue
        if char == "/" and index + 1 < size and text[index + 1] == "/":
            while index < size and text[index] != "\n":
                index += 1
            continue
        out.append(char)
        index += 1
    return "".join(out)


def drop_trailing_commas(text: str) -> str:
    import re
    return re.sub(r",(\s*[}\]])", r"\1", text)


def loads(text: str):
    """Parse OPPO's JSON dialect: // comments and trailing commas."""
    import json
    return json.loads(drop_trailing_commas(strip_comments(text)))


def dumps(value) -> str:
    import json
    return json.dumps(value, indent=4, ensure_ascii=False) + "\n"
