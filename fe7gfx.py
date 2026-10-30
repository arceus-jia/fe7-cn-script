"""ROM 图像解码（只用标准库）：LZ77 解压、4bpp 图块、调色板、PNG 输出。"""
import struct
import zlib


def lz77(d, p):
    """GBA BIOS LZ77（头字节 0x10）解压。"""
    assert d[p] == 0x10, hex(d[p])
    size = d[p + 1] | d[p + 2] << 8 | d[p + 3] << 16
    out, p = bytearray(), p + 4
    while len(out) < size:
        flags = d[p]
        p += 1
        for bit in range(8):
            if len(out) >= size:
                break
            if flags & (0x80 >> bit):
                n, disp = (d[p] >> 4) + 3, ((d[p] & 0xF) << 8 | d[p + 1]) + 1
                p += 2
                for _ in range(n):
                    out.append(out[-disp])
            else:
                out.append(d[p])
                p += 1
    return bytes(out)


def palette(d, p, n=16):
    """GBA BGR555 调色板 -> [(r, g, b)]。"""
    out = []
    for k in range(n):
        c = struct.unpack_from('<H', d, p + 2 * k)[0]
        out.append(((c & 31) * 255 // 31, (c >> 5 & 31) * 255 // 31, (c >> 10 & 31) * 255 // 31))
    return out


class Canvas:
    """RGBA 画布，像素为 (r, g, b, a) 或 None（透明）。"""

    def __init__(self, w, h):
        self.w, self.h = w, h
        self.px = [None] * (w * h)

    def put_tile4(self, data, tile, x0, y0, pal, transparent=True, flip_h=False, flip_v=False):
        """把第 tile 个 4bpp 图块画到 (x0, y0)。"""
        base = tile * 32
        for y in range(8):
            for x in range(8):
                b = data[base + y * 4 + x // 2]
                v = b >> 4 if x & 1 else b & 15
                if v == 0 and transparent:
                    continue
                X, Y = x0 + (7 - x if flip_h else x), y0 + (7 - y if flip_v else y)
                if 0 <= X < self.w and 0 <= Y < self.h:
                    self.px[Y * self.w + X] = pal[v] + (255,)

    def tiles4(self, data, w_tiles, h_tiles, pal, x0=0, y0=0, first=0):
        """按行排列的一块 4bpp 图块（w_tiles × h_tiles）画到 (x0, y0)。"""
        for t in range(w_tiles * h_tiles):
            self.put_tile4(data, first + t, x0 + t % w_tiles * 8, y0 + t // w_tiles * 8, pal)

    def png(self, path, scale=1, alpha=True):
        rows, empty = [], b'\0' * (4 if alpha else 3)
        for y in range(self.h * scale):
            row = bytearray([0])
            for x in range(self.w * scale):
                p = self.px[(y // scale) * self.w + x // scale]
                row += (bytes(p) if alpha else bytes(p[:3])) if p else empty
            rows.append(bytes(row))
        chunk = lambda t, b: struct.pack('>I', len(b)) + t + b + struct.pack('>I', zlib.crc32(t + b))
        ihdr = struct.pack('>IIBBBBB', self.w * scale, self.h * scale, 8, 6 if alpha else 2, 0, 0, 0)
        with open(path, 'wb') as f:
            f.write(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', ihdr) + chunk(b'IDAT', zlib.compress(b''.join(rows), 9))
                    + chunk(b'IEND', b''))


def screen(d, tiles, tsa, pals, bottom_up=False, w=30, h=20):
    """按排列表（每项 u16：图块号/翻转/调色板）拼出 w×h 图块的画面；图块号 0x3FF 视为空白。"""
    c = Canvas(w * 8, h * 8)
    for i in range(w * h):
        v = tsa[2 * i] | tsa[2 * i + 1] << 8
        if v & 0x3FF == 0x3FF or (v & 0x3FF) * 32 >= len(tiles):
            continue
        y = h - 1 - i // w if bottom_up else i // w
        c.put_tile4(tiles, v & 0x3FF, i % w * 8, y * 8, pals[(v >> 12) % len(pals)], transparent=False,
                    flip_h=bool(v & 0x400), flip_v=bool(v & 0x800))
    return c


PORTRAIT_TABLE = 0xD5E23C  # 每项 0x1C：[大头像图块][小头像(LZ77)][调色板]…
# 大头像：ROM 里是 32×4 图块的长条，按 (起始列, 起始行, 宽, 高) -> 头像中 (列, 行) 拼成 12×10 图块（96×80）
FACE_LAYOUT = [((0, 0, 8, 4), (2, 0)), ((8, 0, 8, 4), (2, 4)), ((16, 0, 4, 2), (2, 8)),
               ((16, 2, 4, 2), (6, 8)), ((20, 0, 2, 4), (0, 6)), ((22, 0, 2, 4), (10, 6))]
BG_TABLE, BG_COUNT = 0xC00798, 95  # 对话背景：每项 12 字节 [图块(LZ77)][排列表(宽高头, 自下而上)][调色板×16]


def _u32(d, a):
    return struct.unpack_from('<I', d, a)[0]


def portrait(d, pid):
    """头像编号 -> 96×80 大头像画布；没有图像数据时返回 None。"""
    e = PORTRAIT_TABLE + pid * 0x1C
    if not 0x08000000 <= _u32(d, e) < 0x09000000:
        return None
    g, pal = _u32(d, e) - 0x08000000 + 4, palette(d, _u32(d, e + 8) - 0x08000000)
    c = Canvas(96, 80)
    for (sx, sy, w, h), (dx, dy) in FACE_LAYOUT:
        for ty in range(h):
            for tx in range(w):
                c.put_tile4(d[g:g + 0x1000], (sy + ty) * 32 + sx + tx, (dx + tx) * 8, (dy + ty) * 8, pal)
    return c


def crop(c, x, y, w, h):
    out = Canvas(w, h)
    for j in range(h):
        out.px[j * w:(j + 1) * w] = c.px[(y + j) * c.w + x:(y + j) * c.w + x + w]
    return out


def background(d, k):
    """对话背景编号 -> 240×160 画布。"""
    e = BG_TABLE + k * 12
    tsa = _u32(d, e + 4) - 0x08000000
    w, h = d[tsa] + 1, d[tsa + 1] + 1
    pals = [palette(d, _u32(d, e + 8) - 0x08000000 + 32 * b) for b in range(16)]
    return screen(d, lz77(d, _u32(d, e) - 0x08000000), d[tsa + 2:tsa + 2 + w * h * 2], pals, bottom_up=True, w=w, h=h)


def face_crop(d, pid, size=56):
    """以嘴和眼睛的位置（头像表 +0x14/+0x16，图块单位，相对第 2 列；各是 32×16 的动画框）的中点为中心裁出脸部方块。"""
    c = portrait(d, pid)
    if c is None:
        return None
    e = PORTRAIT_TABLE + pid * 0x1C
    mx, my, ey = d[e + 0x14], d[e + 0x15], d[e + 0x17]
    x = min(max(32 + mx * 8 - size // 2, 0), 96 - size)
    y = min(max((my + ey) * 4 + 8 - size // 2, 0), 80 - size)
    return crop(c, x, y, size, size)


CG_TABLE, CG_COUNT = 0xDB793C, 66  # 剧情 CG：每项 12 字节 [10 块图块指针的数组][排列表(宽高头, 自下而上)][调色板×8]


def cg(d, k):
    """剧情 CG 编号 -> 240×160 画布。图块和调色板在显存里有偏移，按排列表里的最小值对齐。"""
    e = CG_TABLE + k * 12
    arr, tsa, pal = _u32(d, e) - 0x08000000, _u32(d, e + 4) - 0x08000000, _u32(d, e + 8) - 0x08000000
    tiles = b''.join(lz77(d, _u32(d, arr + 4 * j) - 0x08000000) for j in range(10))
    w, h = d[tsa] + 1, d[tsa + 1] + 1
    ent = d[tsa + 2:tsa + 2 + w * h * 2]
    vals = [ent[2 * i] | ent[2 * i + 1] << 8 for i in range(w * h)]
    t0, p0 = min(v & 0x3FF for v in vals), min(v >> 12 for v in vals)
    fixed = b''.join(struct.pack('<H', ((v & 0x3FF) - t0) | (v & 0xC00) | ((v >> 12) - p0) << 12) for v in vals)
    pals = [palette(d, pal + 32 * b) for b in range(8)]
    return screen(d, tiles, fixed, pals, bottom_up=True, w=w, h=h)
