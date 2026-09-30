"""Собрать django.mo из django.po без GNU gettext.

compilemessages требует msgfmt, а его нет ни на Windows, ни в образе. Здесь
только простые однострочные msgid/msgstr — ровно то, что лежит в нашем .po.

    python app/locale/compile.py
"""

import ast
import struct
from pathlib import Path

PO = Path(__file__).parent / "ru" / "LC_MESSAGES" / "django.po"


def parse(text: str) -> dict[str, str]:
    catalog: dict[str, str] = {}
    key = None
    field = None
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("msgid "):
            key, field = ast.literal_eval(line[6:]), "id"
        elif line.startswith("msgstr "):
            catalog[key] = ast.literal_eval(line[7:])
            field = "str"
        elif line.startswith('"') and field == "str":
            catalog[key] += ast.literal_eval(line)
    return catalog


def write_mo(catalog: dict[str, str], path: Path) -> None:
    keys = sorted(catalog)
    ids = [k.encode("utf-8") for k in keys]
    strs = [catalog[k].encode("utf-8") for k in keys]
    start = 7 * 4 + 16 * len(keys)
    offsets, blob = [], b""
    for data in ids:
        offsets.append((len(data), start + len(blob)))
        blob += data + b"\0"
    for data in strs:
        offsets.append((len(data), start + len(blob)))
        blob += data + b"\0"
    header = struct.pack("Iiiiiii", 0x950412DE, 0, len(keys), 7 * 4, 7 * 4 + 8 * len(keys), 0, 0)
    table = b"".join(struct.pack("ii", *pair) for pair in offsets)
    path.write_bytes(header + table + blob)


if __name__ == "__main__":
    write_mo(parse(PO.read_text(encoding="utf-8")), PO.with_suffix(".mo"))
    print("собрано:", PO.with_suffix(".mo"))
