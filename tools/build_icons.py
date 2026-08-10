# -*- coding: utf-8 -*-
"""生成 fn-cocks 的应用图标（纯标准库，无外部依赖）。

用法:
  python build_icons.py [输出目录]

默认输出到本脚本所在项目根目录：
  ICON.PNG (64x64), ICON_256.PNG (256x256)
  app/ui/images/icon-64.png, app/ui/images/icon-256.png
"""
import os
import struct
import sys
import zlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

TEAL = (56, 225, 200)
AMBER = (255, 180, 84)
BG_TOP = (19, 32, 44)
BG_BOTTOM = (9, 14, 20)
BORDER = (56, 225, 200, 90)

BOLT = [
    (0.55, 0.00), (0.15, 0.55), (0.40, 0.55),
    (0.22, 1.00), (0.85, 0.38), (0.58, 0.38), (0.72, 0.00),
]


def lerp(a, b, t):
    return int(a + (b - a) * t)


def point_in_poly(x, y, poly):
    inside = False
    n = len(poly)
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > y) != (yj > y):
            x_cross = (xj - xi) * (y - yi) / (yj - yi) + xi
            if x_cross > x:
                inside = not inside
        j = i
    return inside


def sample(size, ux, uy):
    x = ux * size
    y = uy * size
    cx = size / 2.0

    t = min(max(uy, 0.0), 1.0)
    r, g, b = lerp(BG_TOP[0], BG_BOTTOM[0], t), lerp(BG_TOP[1], BG_BOTTOM[1], t), lerp(BG_TOP[2], BG_BOTTOM[2], t)
    radius = size * 0.19
    half = size / 2.0 - size * 0.015
    dx = max(abs(x - cx) - (half - radius), 0.0)
    dy = max(abs(y - cx) - (half - radius), 0.0)
    dist = (dx * dx + dy * dy) ** 0.5
    if dist > radius:
        return (0, 0, 0, 0)
    px, py, pb = r, g, b

    if radius - 2.2 <= dist <= radius:
        px, py, pb = lerp(px, TEAL[0], 0.35), lerp(py, TEAL[1], 0.35), lerp(b, TEAL[2], 0.35)

    ex = (ux - 0.5) * 2.0
    ey = (uy - 0.5) * 2.0
    a, bb = 0.74, 0.30
    v = (ex / a) ** 2 + (ey / bb) ** 2
    if 0.88 <= v <= 1.12:
        px, py, pb = lerp(px, TEAL[0], 0.55), lerp(py, TEAL[1], 0.55), lerp(b, TEAL[2], 0.55)

    ndx, ndy = 0.5 + 0.74, 0.5
    ddx, ddy = ux - ndx, uy - ndy
    if ddx * ddx + ddy * ddy <= (0.055) ** 2:
        px, py, pb = AMBER

    dist_c = ((ux - 0.5) ** 2 + (uy - 0.5) ** 2) ** 0.5
    if 0.38 <= dist_c <= 0.44:
        px, py, pb = lerp(px, TEAL[0], 0.45), lerp(py, TEAL[1], 0.45), lerp(b, TEAL[2], 0.45)

    if point_in_poly(ux, uy, BOLT):
        px, py, pb = TEAL[0], TEAL[1], TEAL[2]

    return (px, py, pb, 255)


def render(size, ss=3):
    big = size * ss
    buf = bytearray()
    for yy in range(size):
        for xx in range(size):
            rs = gs = bs = as_ = 0
            for dy in range(ss):
                for dx in range(ss):
                    ux = (xx * ss + dx + 0.5) / big
                    uy = (yy * ss + dy + 0.5) / big
                    pr, pg, pb, pa = sample(size, ux, uy)
                    rs += pr * pa
                    gs += pg * pa
                    bs += pb * pa
                    as_ += pa
            if as_ == 0:
                buf += bytes((0, 0, 0, 0))
            else:
                buf += bytes((rs // as_, gs // as_, bs // as_, as_ // (ss * ss)))
    return bytes(buf)


def write_png(path, size, pixels):
    def chunk(tag, data):
        c = tag + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xffffffff)

    raw = b"".join(
        b"\x00" + pixels[y * size * 4:(y + 1) * size * 4]
        for y in range(size)
    )
    ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", ihdr)
    png += chunk(b"IDAT", zlib.compress(raw, 9))
    png += chunk(b"IEND", b"")
    with open(path, "wb") as f:
        f.write(png)
    print("已生成: %s (%dx%d, %d bytes)" % (path, size, size, len(png)))


def main():
    out_dir = sys.argv[1] if len(sys.argv) > 1 else ROOT
    ui_dir = os.path.join(out_dir, "app", "ui", "images")
    os.makedirs(ui_dir, exist_ok=True)

    write_png(os.path.join(out_dir, "ICON.PNG"), 64, render(64))
    write_png(os.path.join(out_dir, "ICON_256.PNG"), 256, render(256))
    write_png(os.path.join(ui_dir, "icon-64.png"), 64, render(64))
    write_png(os.path.join(ui_dir, "icon-256.png"), 256, render(256))


if __name__ == "__main__":
    main()
