"""Decode one bounded, digest-verified workflow bundle without extracting paths."""
import hashlib
import io
import json
import re
import stat
import sys
import zipfile


def unpack(raw, digest):
    if (len(raw) > 128 * 1024 * 1024 or not re.fullmatch(r"[a-f0-9]{64}", digest)
            or hashlib.sha256(raw).hexdigest() != digest):
        raise ValueError()
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        entries = archive.infolist()
        if len(entries) != 1:
            raise ValueError()
        entry = entries[0]
        if (entry.filename != "bundle.json" or entry.is_dir() or entry.flag_bits & 1
                or not 0 < entry.file_size <= 96_000_000
                or entry.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)
                or stat.S_IFMT(entry.external_attr >> 16) not in (0, stat.S_IFREG)):
            raise ValueError()
        with archive.open(entry) as stream:
            value = stream.read(96_000_001)
        if len(value) != entry.file_size:
            raise ValueError()
        json.loads(value)
        return value


if __name__ == "__main__":
    try:
        if len(sys.argv) != 2:
            raise ValueError()
        sys.stdout.buffer.write(unpack(sys.stdin.buffer.read(128 * 1024 * 1024 + 1), sys.argv[1]))
    except Exception:
        print("Hosted agent bundle is invalid; private details withheld.", file=sys.stderr)
        sys.exit(1)
