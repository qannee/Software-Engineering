"""Generate small branded PNG icons using only Python's standard library."""

from pathlib import Path
import struct
import zlib


OUTPUT = Path(__file__).resolve().parents[1] / "frontend" / "public" / "icons"
BACKGROUND = (21, 63, 55)
FOREGROUND = (248, 247, 242)
GLYPHS = {
    "Q": ("01110", "10001", "10001", "10001", "10101", "10010", "01101"),
    "1": ("00100", "01100", "00100", "00100", "00100", "00100", "01110"),
}


def png_chunk(name: bytes, data: bytes) -> bytes:
    content = name + data
    return struct.pack(">I", len(data)) + content + struct.pack(">I", zlib.crc32(content) & 0xFFFFFFFF)


def make_icon(size: int) -> bytes:
    pixels = bytearray(BACKGROUND * (size * size))
    scale = max(1, size // 18)
    center = size // 2
    radius = round(size * 0.39)
    stroke = max(1, size // 100)
    for y in range(size):
        for x in range(size):
            distance = (x - center) ** 2 + (y - center) ** 2
            if (radius - stroke) ** 2 <= distance <= (radius + stroke) ** 2:
                offset = (y * size + x) * 3
                pixels[offset:offset + 3] = bytes(FOREGROUND)

    width = (5 * 2 + 1) * scale
    height = 7 * scale
    start_x = (size - width) // 2
    start_y = (size - height) // 2
    for glyph_index, glyph in enumerate((GLYPHS["Q"], GLYPHS["1"])):
        glyph_x = start_x + glyph_index * 6 * scale
        for row, pattern in enumerate(glyph):
            for column, pixel in enumerate(pattern):
                if pixel != "1":
                    continue
                for dy in range(scale):
                    y = start_y + row * scale + dy
                    for dx in range(scale):
                        x = glyph_x + column * scale + dx
                        offset = (y * size + x) * 3
                        pixels[offset:offset + 3] = bytes(FOREGROUND)
    raw = b"".join(b"\x00" + pixels[y * size * 3:(y + 1) * size * 3] for y in range(size))
    header = struct.pack(">2I5B", size, size, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + png_chunk(b"IHDR", header) + png_chunk(b"IDAT", zlib.compress(raw, 9)) + png_chunk(b"IEND", b"")


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for size in (180, 192, 512):
        (OUTPUT / f"q1-{size}.png").write_bytes(make_icon(size))


if __name__ == "__main__":
    main()
