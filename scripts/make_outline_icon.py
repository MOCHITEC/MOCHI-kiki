"""Generate a 32x32 white-on-transparent outline PNG for Teams manifest."""
import struct
import zlib
import pathlib

W, H = 32, 32


def _chunk(tag: bytes, data: bytes) -> bytes:
    c = struct.pack(">I", len(data)) + tag + data
    return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)


def make_png(pixels: list[list[tuple[int, int, int, int]]]) -> bytes:
    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = _chunk(b"IHDR", struct.pack(">IIBBBBB", W, H, 8, 2, 0, 0, 0))
    raw = b""
    for row in pixels:
        raw += b"\x00"  # filter type None
        for r, g, b, a in row:
            raw += bytes([r, g, b, a])
    idat = _chunk(b"IDAT", zlib.compress(raw, 9))
    iend = _chunk(b"IEND", b"")
    return sig + ihdr + idat + iend


def draw() -> list[list[tuple[int, int, int, int]]]:
    cx, cy, r = W // 2, H // 2, 13
    img = [[(0, 0, 0, 0)] * W for _ in range(H)]
    for y in range(H):
        for x in range(W):
            dx, dy = x - cx, y - cy
            dist = (dx * dx + dy * dy) ** 0.5
            if dist <= r:
                img[y][x] = (255, 255, 255, 255)
    return img


out = pathlib.Path(__file__).parent.parent / "teams_app" / "outline.png"
out.write_bytes(make_png(draw()))
print(f"[OK] {out}")
