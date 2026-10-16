"""火焰纹章 烈火之剑（AE7J 汉化版）文本解码。地址来自本 ROM 反汇编，换版本需重新确认。"""
import os
import re
import struct
import unicodedata

TEXT_COUNT = 4661
FONT_BASE = 0xBC0698  # 字模 = BASE + ((hi-0x81)*128 + (lo-0x80)) * 0x54，见 0x08005614


class Rom:
    def __init__(self, path):
        self.d = open(path, 'rb').read()
        self.tree = self.u32(0x6E0) - 0x08000000
        self.root = self.u32(self.u32(0x6DC) - 0x08000000) - 0x08000000
        self.table = self.u32(0x13340) - 0x08000000

    def u32(self, a):
        return struct.unpack_from('<I', self.d, a)[0]

    def u16(self, a):
        return struct.unpack_from('<H', self.d, a)[0]

    def raw(self, i):
        """第 i 条文本的原始字节（Huffman 解压后，不含结尾 0）。"""
        p = self.u32(self.table + i * 4)
        if p >= 0x88000000:  # 未压缩文本
            p -= 0x88000000
            return self.d[p:self.d.index(0, p)]
        p -= 0x08000000
        out, node, bit, cur = bytearray(), self.root, 0, self.d[p]
        while True:
            l, r = self.u16(node), self.u16(node + 2)
            if r & 0x8000:  # 叶子：低字节、高字节依次输出
                if l & 0xFF == 0:
                    return bytes(out)
                out.append(l & 0xFF)
                if l >> 8:
                    out.append(l >> 8)
                node = self.root
                continue
            b = (cur >> bit) & 1
            bit += 1
            if bit == 8:
                p, bit = p + 1, 0
                cur = self.d[p]
            node = self.tree + (r if b else l) * 4

    def glyph(self, code):
        """返回 (宽, 高, 像素行列表)，像素值 3=笔画 2=阴影。"""
        g = FONT_BASE + (((code >> 8) - 0x81) * 128 + (code & 0xFF) - 0x80) * 0x54
        w, h = self.d[g], self.d[g + 1]
        px = []
        for k in range(20):
            x = self.u32(g + 4 + k * 4)
            px += [(x >> (2 * i)) & 3 for i in range(16)]
        return w, h, [px[r * w:(r + 1) * w] for r in range(h)]


def tokens(s):
    """切分成 (类型, 字节)：'char' 双字节字，'ctl' 控制码（含参数）。"""
    k = 0
    while k < len(s):
        b = s[k]
        if b == 0x10:
            yield 'ctl', s[k:k + 3]; k += 3
        elif b == 0x80:
            yield 'ctl', s[k:k + 2]; k += 2
        elif b >= 0x20:
            yield 'char', s[k:k + 2]; k += 2
        else:
            yield 'ctl', s[k:k + 1]; k += 1


CHAR_TABLE, CLASS_TABLE, ITEM_TABLE = 0xC4C124, 0xC4F468, 0xC51538  # 条目大小 0x34 / 0x54 / 0x24
# [OpenX] 0x08–0x0F 选中位置；0x80 0x0A–0x11 [MoveX] 把当前头像移到对应位置
MOVE_TO = {0x0A: 0x08, 0x0B: 0x09, 0x0C: 0x0A, 0x0D: 0x0B, 0x0E: 0x0C, 0x0F: 0x0D, 0x10: 0x0E, 0x11: 0x0F}
INLINE = {0x05: '{金额}', 0x20: '{军师名}', 0x22: '{道具}'}


def load_tbl(path):
    return {int(l[:4], 16): l[5:].rstrip('\n') for l in open(path, encoding='utf-8') if '=' in l}


def text(rom, tbl, i):
    """不含控制码的纯文本，换行保留。"""
    out = []
    for kind, b in tokens(rom.raw(i)):
        if kind == 'char':
            out.append(tbl.get(b[0] << 8 | b[1]) or (b.decode('latin-1') if b[0] < 0x80 else '〓'))
        elif b == b'\x01':
            out.append('\n')
    return ''.join(out).strip()


def script(rom, tbl, i, faces, state=None):
    """转成剧本行：[(说话人或None, 台词), ...]。faces: 头像编号 -> 人名。
    state: 场景里已显示的头像 {'slots', 'cur'}，传入则沿用并更新（同一场景跨多条文本时）。"""
    state = {'slots': {}, 'cur': None} if state is None else state
    lines, buf, slots, cur = [], [], state['slots'], state['cur']
    speaker = slots.get(cur)
    pending_name = None  # 0x80 0x23 后第一行是名字标签

    def flush():
        s = ''.join(buf).strip()
        if s:
            lines.append((speaker, s))
        buf.clear()

    for kind, b in tokens(rom.raw(i)):
        if kind == 'char':
            ch = tbl.get(b[0] << 8 | b[1]) or (b.decode('latin-1') if b[0] < 0x80 else '〓')
            (pending_name if pending_name is not None else buf).append(ch)
            continue
        c = b[0]
        if c == 0x01:
            if pending_name is not None:
                flush(); speaker = ''.join(pending_name); pending_name = None
        elif c in (0x02, 0x03):
            flush()
        elif 0x08 <= c <= 0x0F:
            flush(); cur = c; speaker = slots.get(c)
        elif c == 0x10:
            flush(); face = b[1] + (b[2] << 8) - 0x100
            slots[cur] = faces.get(face, '头像%02X' % face); speaker = slots[cur]
        elif c == 0x11:
            flush(); slots.pop(cur, None); speaker = None
        elif c == 0x80:
            if b[1] in INLINE:
                buf.append(INLINE[b[1]])
            elif b[1] == 0x23:
                flush(); pending_name = []
            elif b[1] in MOVE_TO and cur in slots:
                flush(); slots[MOVE_TO[b[1]]] = slots.pop(cur); cur = MOVE_TO[b[1]]
    flush()
    state['cur'] = cur
    return lines


DEBUG_FACE_TEXTS = range(0x11A6, 0x11AE)  # 开发用头像查看器：「[09]头像A [0C]头像B / 名A、名B」
FACE_SUFFIXES = ('正面', '礼服', '5年后', '怒', '忍', '眠', '操', '悲', '左', '2', 'F')


def face_names(rom, tbl):
    """头像编号 -> 人名：人物表优先，其余用头像查看器里的标注（去掉表情/姿态后缀）。"""
    faces = {}
    for _, name_id, a in table(rom, tbl, CHAR_TABLE, 0x34, 4):
        faces.setdefault(rom.u16(a + 6), text(rom, tbl, name_id))
    for i in DEBUG_FACE_TEXTS:
        slots, cur, buf = {}, None, []
        for kind, b in tokens(rom.raw(i)):
            if kind == 'char':
                buf.append(tbl.get(b[0] << 8 | b[1], ''))
                continue
            if buf:
                names = ''.join(buf).split('、')
                for slot, name in zip((0x09, 0x0C) if len(names) == 2 else (cur,), names):
                    while name.endswith(FACE_SUFFIXES) and len(name) > 1:
                        name = next(name[:-len(s)] for s in FACE_SUFFIXES if name.endswith(s))
                    if slot in slots:
                        faces.setdefault(slots[slot], name)
                buf = []
            if 0x08 <= b[0] <= 0x0F:
                cur = b[0]
            elif b[0] == 0x10:
                slots[cur] = b[1] + (b[2] << 8) - 0x100
            elif b[0] == 0x11:
                slots.pop(cur, None)
    faces[0xFEFF] = '（当前角色）'  # [LoadFace 0xFFFF]：触发事件的单位
    for f in (0xDF, 0xE0, 0xE4):    # 系统提示框，不标说话人
        faces[f] = None
    return faces


def table(rom, tbl, base, size, num_off):
    """遍历人物/职业/道具表，返回 [(编号, 名称文本ID, 条目地址)]。"""
    rows, k = [], 1
    while rom.d[base + k * size + num_off] == k and rom.u16(base + k * size) < TEXT_COUNT:
        a = base + k * size
        rows.append((k, rom.u16(a), a)); k += 1
    return rows


CHAPTER_DATA = 0xD62184   # 第 0 章条目里「事件编号」字节的位置；条目 0x94 字节，-4 处是章节名文本ID
POINTER_TABLE = 0xD648F4  # 事件头：+0x38 开场剧情；各章剧情脚本按章节顺序连续存放
EVENTS_END = 0xD88708     # 最后一章剧情脚本的结束位置
WORLDMAP_IDX = 253        # 指针表 253+章节序号 = 该章开头的世界地图旁白（指令 0xB4 文本ID）
BATTLE_TABLE = range(0xD66CE0, 0xD67060, 16)  # 战斗对话：[角色1, 角色2, 章节, 0][文本ID][事件指针][?]
DEATH_TABLE = range(0xD67228, 0xD678A8, 16)   # 阵亡台词：[标志][角色, 章节, 0, 0][文本ID][事件指针]
SUPPORT_TABLE = 0xD67934                      # 支援：20 字节 [角色A, 角色B, 0, 0][C][B][A][0]
ANY_CHAPTER = 0x45
# 事件里显示文本的指令：(第几个参数开始是文本ID, 文本个数, 是否沿用上一条文本的头像)
TEXT_OPS = {0x0D: (0, 1, False), 0x11: (0, 1, True), 0xD2: (0, 1, True), 0xD4: (0, 1, True),
            0x0F: (0, 2, False), 0x12: (0, 2, True),   # 两条分别是艾利乌德篇 / 赫克托耳篇
            0x17: (0, 2, False), 0x18: (0, 2, True),   # 两条分别是男军师 / 女军师（只差称呼，取男军师版）
            0x19: (1, 2, False)}                       # [条件, A, B]：两版只差头像站位，取 A
MODE_OPS = (0x0F, 0x12)
# 章节序号分组（同章不同路线合并）与显示章号；章节名取自 ROM
CHAPTERS = [
    ([0], '序章'), ([1], '第1章'), ([2], '第2章'), ([3], '第3章'), ([4], '第4章'), ([5], '第5章'),
    ([6], '第6章'), ([7], '第7章'), ([8], '第7章外传'), ([9], '第8章'), ([10], '第9章'), ([11], '第10章'),
    ([12], '第11章（艾利乌德篇）'), ([13], '第11章（赫克托耳篇）'), ([14], '第12章'), ([15], '第13章'),
    ([16], '第13章外传'), ([17], '第14章'), ([18], '第15章（赫克托耳篇限定）'), ([19], '艾15章・赫16章'),
    ([20], '艾16章・赫17章'), ([21], '艾16章外传・赫17章外传'), ([22], '艾17章・赫18章'), ([23], '艾18章・赫19章'),
    ([24], '艾18章外传・赫19章外传'), ([25], '赫19章异传（赫克托耳篇限定）'), ([26], '艾19章・赫20章'),
    ([27], '艾20章・赫21章'), ([28], '艾21章・赫22章'), ([29], '艾22章・赫23章'), ([30], '艾22章外传・赫23章外传'),
    ([31, 32], '艾23章・赫24章'), ([33], '艾24章・赫25章'), ([34], '艾25章・赫26章'), ([35, 36], '艾26章・赫27章'),
    ([37], '艾27章・赫28章'), ([38], '艾27章外传・赫28章外传'), ([39], '艾28章・赫29章'), ([40], '艾29章・赫30章'),
    ([41], '赫31章（赫克托耳篇限定）'), ([42], '艾30章・赫32章'), ([43], '艾30章外传・赫32章外传'),
    ([44], '艾31章・赫33章'), ([45], '艾31章外传・赫33章外传'), ([46, 47], '终章'),
]
CHAPTER_TEXTS = range(0x833, 0xF36)  # 剧情文本按章节连续编号（含终章后的收尾剧情）
# 未被事件引用的文本默认归到编号在它之前的那一章；例外：第4章防卫图的教学与评价排在第4章剧情之前
CHAPTER_OVERRIDES = {t: 4 for t in range(0x8EA, 0x8FD)}
DEATH_TEXTS = range(0x7B4, 0x80C)
EPILOGUE_TEXTS = [*range(0xFC6, 0xFE4), *range(0x1014, 0x1096)]


def fmt(lines):
    return '\n'.join(f'{sp}：{s}' if sp else s for sp, s in lines)


# 堇天《狼组•火花汉化版错译盘点》：https://www.bilibili.com/read/readlist/rl724370
JINTIAN_URL = 'https://www.bilibili.com/read/readlist/rl724370'
JINTIAN_LABEL = '堇天修正 v0.9'  # 堇天定的版本号，出新版时改这里
# 修正版统一使用的堇天译名：火花译名 -> 堇天译名。只收她在修正文里一贯使用、或文中明确说明改过的；
# 混用的（霍凯/霍克艾、多尔克斯/多尔卡斯、罗依德/罗伊德、艾特鲁斯坎/艾特鲁利亚）不做全局替换，各句照她原文
JINTIAN_NAMES = {'赫克托耳': '海克托尔', '露依斯': '露易丝', '雷钠多': '雷纳多', '艾利克': '埃利克',
                 '埃伦': '埃伦诺亚', '巴萨鲁': '哈萨鲁', '海亚德': '贝亚德'}
# 堇天文中的写法 -> 火花写法（定位原文用）；「玛克」是她游戏里的军师名
JINTIAN_ALIASES = {**{v: k for k, v in JINTIAN_NAMES.items()}, '玛克': '{军师名}'}
# 专栏修正文里的笔误（生成网页时更正）
JINTIAN_TYPOS = {'奥迪斯亚': '奥斯迪亚'}


def norm_chars(s):
    """逐字归一化：去掉标点、空白和 {占位符} -> [(字, 在原文中的下标)]。"""
    out, i = [], 0
    while i < len(s):
        if s[i] == '{' and '}' in s[i:]:
            i = s.index('}', i) + 1
            continue
        out += [(c, i) for c in unicodedata.normalize('NFKC', s[i]) if c.isalnum()]
        i += 1
    return out


def norm(s):
    return ''.join(c for c, _ in norm_chars(s))


def apply_fixes(lines, fixes):
    """把纠错替换进剧本行 -> (新的剧本行, 改动组 [[起始行, 结束行(不含), 对应的原文行]])。
    fixes: [(原文锚点, [(说话人, 修正文)])]。"""
    lines, groups = list(lines), []
    for anchor, fix in fixes:
        if anchor.startswith('='):  # 只改标点的条目：按整行原文精确定位，「=说话人：台词」，多行用换行分隔
            want = anchor[1:].split('\n')
            fmt_line = lambda ln: f'{ln[0]}：{ln[1]}' if ln[0] else ln[1]
            l0 = next((i for i in range(len(lines) - len(want) + 1)
                       if [fmt_line(ln) for ln in lines[i:i + len(want)]] == want), None)
            if l0 is None:
                continue
            l1, c0, c1 = l0 + len(want) - 1, 0, len(lines[l0 + len(want) - 1][1])
            s0, s1 = lines[l0][1], lines[l1][1]
        else:
            flat = [(c, li, ci) for li, (_, s) in enumerate(lines) for c, ci in norm_chars(s)]
            k = ''.join(c for c, _, _ in flat).find(anchor)
            if k < 0 or not anchor:
                continue
            (_, l0, c0), (_, l1, c1) = flat[k], flat[k + len(anchor) - 1]
            s0, s1, c1 = lines[l0][1], lines[l1][1], c1 + 1
        if not fix[-1][1][-1:].isalnum():  # 修正文自带结尾标点时，去掉原文紧跟的标点
            while c1 < len(s1) and not s1[c1].isalnum() and s1[c1] != '{':
                c1 += 1
        if not fix[0][1][:1].isalnum():
            while c0 > 0 and not s0[c0 - 1].isalnum() and s0[c0 - 1] != '}':
                c0 -= 1
        speakers = {lines[i][0] for i in range(l0, l1 + 1)}
        new, prev = [], lines[l0][0]
        for sp, t in fix:  # 说话人用本站写法；对不上原文范围内的说话人时沿用上一行
            sp = JINTIAN_ALIASES.get(sp, sp) if sp else prev
            prev = sp if sp in speakers else prev
            new.append((prev, t))
        new[0] = (new[0][0], s0[:c0] + new[0][1])
        new[-1] = (new[-1][0], new[-1][1] + s1[c1:])
        # 原文：被覆盖的行里，已经改过的取当初的原文（同一行被多条纠错修改时合并成一组）
        hit = [g for g in groups if g[0] <= l1 and l0 < g[1]]
        lo, hi = min([l0] + [g[0] for g in hit]), max([l1 + 1] + [g[1] for g in hit])
        old, i = [], lo
        while i < hi:
            g = next((g for g in hit if g[0] == i), None)
            old += g[2] if g else [lines[i]]
            i = g[1] if g else i + 1
        new = lines[lo:l0] + new + lines[l1 + 1:hi]
        lines[lo:hi] = new
        shift = len(new) - (hi - lo)
        groups = [g if g[0] < lo else [g[0] + shift, g[1] + shift, g[2]] for g in groups if g not in hit]
        groups.append([lo, lo + len(new), old])
    return lines, sorted(groups)


def chapter_events(rom, k):
    """第 k 章剧情脚本里按顺序出现的文本：[(指令, [文本ID...])]。"""
    hdr = lambda c: rom.u32(rom.u32(POINTER_TABLE + 4 * rom.d[CHAPTER_DATA + c * 0x94]) - 0x08000000 + 0x38) - 0x08000000
    start, end = hdr(k), (hdr(k + 1) if k < 47 else EVENTS_END)
    out = []
    for a in range(start, end, 4):
        op = rom.u32(a)
        if op in TEXT_OPS:
            first, n, _ = TEXT_OPS[op]
            ids = [rom.u32(a + 4 * (1 + first + j)) for j in range(n)]
            if all(0x800 <= t < TEXT_COUNT for t in ids):
                out.append((op, ids))
    return out


def worldmap_texts(rom, k):
    """第 k 章开头的世界地图旁白文本ID。"""
    if k >= 44:
        return []
    addrs = sorted({rom.u32(POINTER_TABLE + 4 * (WORLDMAP_IDX + j)) - 0x08000000 for j in range(44)})
    start = rom.u32(POINTER_TABLE + 4 * (WORLDMAP_IDX + k)) - 0x08000000
    end = next((a for a in addrs if a > start), start + 0x400)
    ids = [rom.u32(a + 4) for a in range(start, end, 4) if rom.u32(a) == 0xB4 and 0x600 <= rom.u32(a + 4) < 0x833]
    return list(dict.fromkeys(ids))


def quote_tables(rom, tbl):
    """战斗对话 / 阵亡台词 / 支援表 -> (文本标签, 文本所属章节, 支援 [(角色A编号, 角色B编号, [(等级, 文本ID)])])。"""
    names = {k: text(rom, tbl, nid) for k, nid, _ in table(rom, tbl, CHAR_TABLE, 0x34, 4)}
    d, tags, chapter, supports = rom.d, {}, {}, []
    for e in BATTLE_TABLE:
        t = rom.u32(e + 4)
        if 0 < t < TEXT_COUNT:
            tags[t] = f'【战斗对话】{names.get(d[e], "?")} × {names.get(d[e + 1], "?")}'
            if d[e + 2] < 48:
                chapter[t] = d[e + 2]
    for e in DEATH_TABLE:
        t = rom.u32(e + 8)
        if 0 < t < TEXT_COUNT:
            tags[t] = f'【阵亡台词】{names.get(d[e + 4], "?")}'
            if d[e + 5] < 48:
                chapter[t] = d[e + 5]
    e = SUPPORT_TABLE
    while d[e] and d[e + 1]:
        levels = [(lv, t) for lv, t in zip('CBA', (rom.u32(e + 4), rom.u32(e + 8), rom.u32(e + 12))) if 0 < t < TEXT_COUNT]
        supports.append((d[e], d[e + 1], levels))
        e += 20
    return tags, chapter, supports, names


def build_pages(rom, tbl, faces):
    """整理成页面：[{'name', 'title', 'sections': [(小标题, [(文本ID, 标签, 剧本行)])],
    'index': [(分组名, [(链接文字, 第几个小标题)])]（可选，网页顶部的索引）}]，每条文本只出现一次。"""
    tags, table_ch, supports, names = quote_tables(rom, tbl)
    events = {k: chapter_events(rom, k) for ks, _ in CHAPTERS for k in ks}
    used = {t for k in events for _, ids in events[k] for t in ids}
    starts = sorted((min(t for _, ids in events[k] for t in ids if t >= CHAPTER_TEXTS.start), k) for k in events)
    leftovers = {}
    for t in CHAPTER_TEXTS:
        if t not in used and rom.raw(t):
            k = CHAPTER_OVERRIDES.get(t, table_ch.get(t))
            if k is None:
                k = max((s for s in starts if s[0] <= t), default=starts[0])[1]
            leftovers.setdefault(k, []).append(t)
    done, pages = set(), []

    def entries(ids, tag=None):
        out = []
        for t in ids:
            lines = script(rom, tbl, t, faces)
            if t not in done and lines:
                out.append((t, tag(t) if tag else tags.get(t, ''), lines))
            done.add(t)
        return out

    for n, (ks, label) in enumerate(CHAPTERS):
        title = text(rom, tbl, rom.u16(CHAPTER_DATA + ks[0] * 0x94 - 4))
        sections = []
        wm = [t for k in ks for t in worldmap_texts(rom, k)]
        both = any(0x69F <= t < 0x6BC for t in wm) and any(t >= 0x6BC for t in wm)
        wm_entries = []
        for t in wm:
            tag = ('【赫克托耳篇】' if t >= 0x6BC else '【艾利乌德篇】') if both and t >= 0x69F else ''
            wm_entries.append((t, tag, [(None, text(rom, tbl, t).replace('\n', ''))])); done.add(t)
        if wm_entries:
            sections.append(('世界地图旁白', wm_entries))

        story = []
        for k in ks:
            state = {'A': None, 'B': None}
            for op, ids in events[k]:
                keep = TEXT_OPS[op][2]
                if op in MODE_OPS:
                    tracks = [('A', ids[0], '【艾利乌德篇】'), ('B', ids[1], '【赫克托耳篇】')]
                else:  # 只输出第一版，另一版只记为已处理
                    tracks = [('A', ids[0], '')]
                    done.update(ids[1:])
                for track, t, tag in tracks:
                    st = state[track] if keep and state[track] else {'slots': {}, 'cur': None}
                    lines = script(rom, tbl, t, faces, st)
                    state[track] = st
                    if op not in MODE_OPS:
                        state['B'] = {'slots': dict(st['slots']), 'cur': st['cur']}
                    if t not in done and lines:
                        story.append((t, tag, lines))
                    done.add(t)
        sections.append(('剧情', story))
        rest = entries(t for k in ks for t in leftovers.get(k, []))
        if rest:
            sections.append(('本章其他文本（战斗对话、阵亡台词、村庄、教学提示等）', rest))
        pages.append({'name': f'{n:02d}_{label}_{title}', 'title': f'{label}　{title}', 'sections': sections})

    # 支援：每个角色一页（配对在双方页面都出现），总页 'hub' 是角色 -> 支援对象的索引
    pairs = []
    for a, b, levels in supports:
        lv = dict((t, l) for l, t in levels)
        items = entries([t for _, t in levels], tag=lambda t: f'【支援{lv[t]}】')
        if items:
            pairs.append((a, b, items, '·'.join(lv[t] for t, _, _ in items)))
    subpages, hub, first = [], [], {}
    for k in sorted(names):  # 同一角色在琳篇/艾赫篇有不同编号，按名字合并、按首次出现的编号排序
        first.setdefault(names[k], k)
    pairs = [(names.get(a, '?'), names.get(b, '?'), items, lvs) for a, b, items, lvs in pairs]
    for n, name in enumerate(sorted({x for a, b, *_ in pairs for x in (a, b)}, key=lambda x: first.get(x, 999))):
        slug = f'sup{first.get(name, 0):02x}'
        mine = [(b if a == name else a, items, lvs) for a, b, items, lvs in pairs if name in (a, b)]
        subpages.append({'name': f'{n:02d}_{name}', 'title': f'{name}的支援对话', 'slug': slug,
                         'sections': [(f'{name} × {o}', items) for o, items, _ in mine],
                         'index': [('', [(o, j) for j, (o, _, _) in enumerate(mine)])]})
        hub.append((name, slug, [(o, j, lvs) for j, (o, _, lvs) in enumerate(mine)]))
    pages.append({'name': '支援对话', 'title': '支援对话', 'sections': [], 'hub': hub, 'subpages': subpages})

    # 阵亡与撤退台词：按角色分节，不在阵亡表里的（琳篇战后对话等）放最后
    who = {t: tags[t][len('【阵亡台词】'):] for t in tags if tags[t].startswith('【阵亡')}
    groups = {}
    for t in [*(t for t in who if t not in table_ch), *DEATH_TEXTS]:
        groups.setdefault(who.get(t, '其他（战后对话等）'), []).append(t)
    other = groups.pop('其他（战后对话等）', [])
    sections = [(n, entries(ids, tag=lambda t: '')) for n, ids in [*groups.items(), ('其他（战后对话等）', other)]]
    sections = [s for s in sections if s[1]]
    pages.append({'name': '阵亡与撤退台词', 'title': '阵亡与撤退台词', 'sections': sections,
                  'index': [('角色', [(n, i) for i, (n, _) in enumerate(sections)])]})

    for name, ids in (('结局与后日谈', EPILOGUE_TEXTS), ('其他文本（系统、说明、菜单等）', range(TEXT_COUNT))):
        pages.append({'name': name, 'title': name, 'sections': [('', entries(ids))]})
    return pages


def write_txt(page, path):
    body = [f'# {page["title"]}']
    for head, items in page['sections']:
        if head:
            body.append(f'【{head}】')
        body += [f'#{t:04X}{tag}\n{fmt(lines)}' for t, tag, lines in items]
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n\n'.join(body) + '\n')

SITE_CSS = """:root{--bg:#fbfaf7;--fg:#1f1f1f;--muted:#6f6c66;--line:#e4e1da;--accent:#9b2c2c;--card:#fff;--mark:#fbefc4;--l:36%}
@media (prefers-color-scheme:dark){:root{--bg:#17171a;--fg:#e6e4df;--muted:#9a978f;--line:#2e2d33;--accent:#e8917f;--card:#202026;--mark:#3d3520;--l:72%}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:17px/1.8 -apple-system,"PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif;overflow-wrap:anywhere}
main,nav{max-width:42em;margin:0 auto;padding:0 16px}
nav{display:flex;gap:1em;justify-content:space-between;padding-top:12px;padding-bottom:12px;font-size:15px}
a{color:var(--accent);text-decoration:none}
h1{font-size:1.45em;line-height:1.4;margin:.4em 0 .8em}
h2{font-size:1.05em;color:var(--muted);border-bottom:1px solid var(--line);padding-bottom:.3em;margin-top:2.4em}
article{margin:1.1em 0;padding-bottom:.7em;border-bottom:1px dashed var(--line)}
article header{font-size:13px;color:var(--muted)}
article header a{color:var(--muted)}
.tag{color:var(--accent);margin-left:.5em}
p{margin:.1em 0}
b{font-weight:600;color:hsl(var(--h) 55% var(--l))}
.toc{padding-left:0;list-style:none}.toc li{margin:.25em 0}.toc small{color:var(--muted);display:inline-block;min-width:11em}
.note{color:var(--muted);font-size:14px}
.jump{font-size:15px;line-height:2;border:1px solid var(--line);border-radius:8px;padding:.4em .9em;margin-bottom:1em}
.jump summary{cursor:pointer;color:var(--muted)}
.jump b{margin-right:.8em}
.jump a{display:inline-block;border:1px solid var(--line);border-radius:999px;padding:0 .75em;margin:.2em .4em .2em 0;line-height:1.9;white-space:nowrap;background:var(--card)}
.hub{display:flex;flex-wrap:wrap;gap:.5em;margin-top:1em}
.hub details{border:1px solid var(--line);border-radius:999px;background:var(--card)}
.hub details[open]{flex-basis:100%;border-radius:12px;border-color:var(--muted)}
.hub summary{list-style:none;cursor:pointer;padding:.25em .9em;user-select:none}
.hub summary::-webkit-details-marker{display:none}
.hub small{color:var(--muted);font-size:12px;margin-left:.4em}
.partners{display:flex;flex-wrap:wrap;gap:.45em;padding:.6em .8em .9em;border-top:1px dashed var(--line)}
.partners a{border:1px solid var(--line);border-radius:999px;padding:.1em .75em;font-size:15px;background:var(--bg)}
.partners a.all{border-style:dashed;color:var(--muted)}
h2 .up{float:right;font-size:13px;font-weight:normal}
table{border-collapse:collapse;width:100%;font-size:15px}
th,td{border-bottom:1px solid var(--line);padding:.35em .5em;text-align:left;vertical-align:top}
body{padding-bottom:64px}
.cmp>summary{list-style:none;cursor:pointer}.cmp>summary::-webkit-details-marker{display:none}
.cmp>summary>span{display:block;background:var(--mark);border-radius:4px;padding:0 .3em;margin:0 -.3em}
.mk{font-style:normal;font-size:11px;color:var(--muted);border:1px solid var(--muted);border-radius:999px;padding:0 .5em;margin-left:.4em;white-space:nowrap;vertical-align:1px}
.cmp[open] .mk{background:var(--muted);color:var(--card)}
.old{border-left:3px solid var(--mark);margin:.25em 0 .6em;padding:.1em 0 .1em .7em;color:var(--muted)}
.old::before{content:"火花原文";display:block;font-size:12px}
.src{margin-left:.5em}
.ver{position:fixed;right:12px;bottom:12px;display:flex;border:1px solid var(--line);border-radius:999px;background:var(--card);box-shadow:0 2px 10px rgba(0,0,0,.15);overflow:hidden;font-size:14px;z-index:9}
.ver a{color:var(--muted);padding:.5em 1em}
html:not(.jt) .ver [data-v=hh],html.jt .ver [data-v=jt]{background:var(--accent);color:var(--card)}
"""
SITE_SLUGS = {'支援对话': 'support', '阵亡与撤退台词': 'death', '结局与后日谈': 'epilogue',
              '其他文本（系统、说明、菜单等）': 'misc'}


def renamer(names):
    """火花译名 -> 堇天译名的整体替换函数（长名优先）。"""
    if not names:
        return lambda s: s
    pat = re.compile('|'.join(map(re.escape, sorted(names, key=len, reverse=True))))
    abbr = names.get('赫克托耳', '赫')[:1]  # 章号缩写「赫16章」跟着改
    return lambda s: re.sub(r'赫(?=\d)', abbr, pat.sub(lambda m: names[m.group(0)], s)) if s else s


def write_site(pages, glossary, site, jt=None):
    """生成一套网页。jt=None 为火花原版（site 根目录）；jt={'fixes', 'names'} 为堇天修正版（site/jt/）：
    fixes: {文本ID: [(原文锚点, 修正行, (专栏cv号, 条目号))]}，names: {火花译名: 堇天译名}。"""
    import html, zlib
    esc = html.escape
    fixes, T = (jt['fixes'], renamer(jt['names'])) if jt else ({}, lambda s: s)
    applied = set()  # 网页上实际生效的纠错（专栏cv号, 条目号）
    root, out_dir = ('../', os.path.join(site, 'jt')) if jt else ('', site)
    os.makedirs(out_dir, exist_ok=True)
    if not jt:
        open(os.path.join(site, '.nojekyll'), 'w').close()
        with open(os.path.join(site, 'style.css'), 'w', encoding='utf-8') as f:
            f.write(SITE_CSS)
    slug = lambda p: p.get('slug') or ('c' + p['name'][:2] if p['name'][:2].isdigit() else SITE_SLUGS[p['name']])

    def doc(title, nav, body, file):
        hh, jt_link = (f'../{file}', file) if jt else (file, f'jt/{file}')
        switch = (f'<div class="ver"><a data-v="hh" href="{hh}">火花原版</a><a data-v="jt" href="{jt_link}">{JINTIAN_LABEL}</a></div>'
                  '<script>document.querySelectorAll(".ver a").forEach(function(a){a.onclick=function(){'
                  'location.href=a.getAttribute("href")+location.hash;return false}})</script>')
        return (f'<!doctype html><html lang="zh-CN"{" class=\"jt\"" if jt else ""}><head><meta charset="utf-8">'
                f'<meta name="viewport" content="width=device-width,initial-scale=1">'
                f'<title>{esc(T(title))}{f"（{JINTIAN_LABEL}）" if jt else ""}</title><link rel="stylesheet" href="{root}style.css"></head>'
                f'<body>{nav}<main>{body}</main>{nav}{switch}</body></html>\n')

    def line(sp, s, tag='p', raw=False):  # raw：对照用的火花原文，不换译名
        t = (lambda x: x) if raw else T
        return f'<{tag}>{who(sp, raw)}：{esc(t(s))}</{tag}>' if sp else f'<{tag}>{esc(t(s))}</{tag}>'

    def who(name, raw=False):  # 每个角色固定一个颜色（按火花名算，两版一致）
        return f'<b style="--h:{zlib.crc32(name.encode()) % 360}">{esc(name if raw else T(name))}</b>'

    def render(lines, groups):
        """改动组显示修正文（黄底），句尾「原文」点开可对照火花原文。"""
        out, k = [], 0
        for start, end, old in groups:
            out += [line(sp, s) for sp, s in lines[k:start]]
            new = [line(sp, s, 'span') for sp, s in lines[start:end]]
            new[-1] = new[-1][:-len('</span>')] + '<i class="mk">原文</i></span>'
            out.append('<details class="cmp"><summary>' + ''.join(new) + '</summary><div class="old">'
                       + ''.join(line(sp, s, raw=True) for sp, s in old) + '</div></details>')
            k = end
        return ''.join(out + [line(sp, s) for sp, s in lines[k:]])

    def jump(index):
        rows = ''.join(f'<p>{who(g) if len(index) > 1 else ""}'
                       + ''.join(f'<a href="#s{j}">{esc(T(t))}</a>' for t, j in links) + '</p>' for g, links in index)
        return f'<details id="idx" class="jump" open><summary>索引</summary>{rows}</details>'

    def hub(chars):  # 角色胶囊：点开显示支援对象（同一时间只展开一个），点对象跳到对话
        out = []
        for name, sl, partners in chars:
            links = ''.join(f'<a href="{sl}.html#s{j}">{who(o)}<small>{esc(lv)}</small></a>' for o, j, lv in partners)
            out.append(f'<details name="sup"><summary>{who(name)}<small>{len(partners)}</small></summary>'
                       f'<div class="partners">{links}<a class="all" href="{sl}.html">全部 →</a></div></details>')
        return '<p class="note">点角色展开支援对象，再点对象跳到对话。名字旁的数字是支援对象数，C·B·A 是可进行的支援等级。</p>' \
               '<div class="hub">' + ''.join(out) + '</div>'

    def write_pages(ps, home, home_title, prev_text, next_text):
        for i, p in enumerate(ps):
            prev = f'<a href="{slug(ps[i - 1])}.html" title="{esc(T(ps[i - 1]["title"]))}">← {prev_text}</a>' if i else '<span></span>'
            nxt = f'<a href="{slug(ps[i + 1])}.html" title="{esc(T(ps[i + 1]["title"]))}">{next_text} →</a>' if i + 1 < len(ps) else '<span></span>'
            nav = f'<nav>{prev}<a href="{home}">{home_title}</a>{nxt}</nav>'
            body = [f'<h1>{esc(T(p["title"]))}</h1>']
            if p.get('hub'):
                body.append(hub(p['hub']))
                write_pages(p['subpages'], slug(p) + '.html', '支援目录', '上一位', '下一位')
            if p.get('index'):
                body.append(jump(p['index']))
            n_fix = 0
            for j, (head, items) in enumerate(p['sections']):
                if head:
                    up = '<a class="up" href="#idx">↑ 索引</a>' if p.get('index') else ''
                    body.append(f'<h2 id="s{j}">{esc(T(head))}{up}</h2>')
                for t, tag, lines in items:
                    tag_html = f'<span class="tag">{esc(T(tag))}</span>' if tag else ''
                    lines, groups = apply_fixes(lines, [(a, f) for a, f, _ in fixes.get(t, [])])
                    if groups:
                        n_fix += 1
                        applied.update(src for *_, src in fixes[t])
                        links = ''.join(f'<a href="https://www.bilibili.com/read/cv{cv}/" target="_blank">#{no}</a> '
                                        for _, _, (cv, no) in fixes[t])
                        tag_html += f'<span class="src">堇天纠错 {links}</span>'
                    body.append(f'<article id="t{t:04X}"><header><a href="#t{t:04X}">#{t:04X}</a>{tag_html}</header>'
                                + render(lines, groups) + '</article>')
            if n_fix:
                body.insert(1, f'<p class="note">本页有 {n_fix} 段文本采用了堇天的修正（黄色底色），点句尾「原文」可对照火花原文。</p>')
            with open(os.path.join(out_dir, slug(p) + '.html'), 'w', encoding='utf-8') as f:
                f.write(doc(p['title'], nav, ''.join(body), slug(p) + '.html'))

    write_pages(pages, 'index.html', '目录', '上一页', '下一页')

    kinds = list(dict.fromkeys(r[0] for r in glossary[1:]))
    body = ['<h1>名词表</h1>', jump([('', [(k, j) for j, k in enumerate(kinds)])])]
    for j, kind in enumerate(kinds):
        uniq = dict.fromkeys((r[2], r[3]) for r in glossary[1:] if r[0] == kind)  # 同名同说明的重复条目只留一条
        rows = ''.join(f'<tr><td>{esc(T(n))}</td><td>{esc(T(desc))}</td></tr>' for n, desc in uniq)
        body.append(f'<h2 id="s{j}">{esc(kind)}<a class="up" href="#idx">↑ 索引</a></h2>'
                    f'<table><tr><th>名称</th><th>说明</th></tr>{rows}</table>')
    nav = '<nav><span></span><a href="index.html">目录</a><span></span></nav>'
    with open(os.path.join(out_dir, 'names.html'), 'w', encoding='utf-8') as f:
        f.write(doc('名词表', nav, ''.join(body), 'names.html'))

    def toc(ps):
        items = []
        for p in ps:
            label, _, title = p['title'].partition('　')
            items.append(f'<li><a href="{slug(p)}.html"><small>{esc(T(label))}</small>{esc(T(title))}</a></li>')
        return '<ul class="toc">' + ''.join(items) + '</ul>'
    chapters = [p for p in pages if p['name'][:2].isdigit()]
    jt_link = f'<a href="{JINTIAN_URL}" target="_blank">堇天《狼组•火花汉化版错译盘点》</a>'
    if jt:
        n = len(applied)
        intro = (f'<h1>火焰纹章 烈火之剑 汉化版文本（{JINTIAN_LABEL}）</h1><p class="note">在火花 × 狼组汉化版的基础上，'
                 f'采用 {jt_link} 的 {n} 条修正替换错译（修改处以黄色底色标出，并附原文章链接），人名统一使用堇天的译名。'
                 '右下角可切回火花原版。<br>')
    else:
        intro = ('<h1>火焰纹章 烈火之剑 汉化版文本</h1><p class="note">文本出自火花 × 狼组汉化版，仅供查阅参考，版权归原作及汉化组所有。<br>'
                 f'右下角可切换到「{JINTIAN_LABEL}」：采用 {jt_link} 的修正译文替换原版中的错译。<br>')
    body = (intro + T('章号中「艾」指艾利乌德篇、「赫」指赫克托耳篇。').replace('「赫」', f'「{T("赫1")[0]}」')
            + '每段开头的 #编号 是游戏内文本编号。</p>'
            '<h2>琳篇</h2>' + toc(chapters[:12]) + '<h2>艾利乌德篇・赫克托耳篇</h2>' + toc(chapters[12:])
            + '<h2>其他</h2><ul class="toc">'
            + ''.join(f'<li><a href="{slug(p)}.html">{esc(T(p["title"]))}</a></li>' for p in pages if not p['name'][:2].isdigit())
            + '<li><a href="names.html">名词表（人物・职业・道具）</a></li></ul>')
    with open(os.path.join(out_dir, 'index.html'), 'w', encoding='utf-8') as f:
        f.write(doc('烈火之剑 汉化版文本', '', body, 'index.html'))


if __name__ == '__main__':
    import csv, glob, json, sys
    here = os.path.dirname(os.path.abspath(__file__))
    rom = Rom(sys.argv[1] if len(sys.argv) > 1 else glob.glob(os.path.join(here, 'rom', '*.gba'))[0])
    tbl = load_tbl(os.path.join(here, 'fe7_cn.tbl'))
    out = os.path.join(here, 'output'); os.makedirs(os.path.join(out, '章节'), exist_ok=True)
    faces = face_names(rom, tbl)

    with open(os.path.join(out, '全文本.txt'), 'w', encoding='utf-8') as f:
        for i in range(TEXT_COUNT):
            body = script(rom, tbl, i, faces)
            if body:
                f.write('#%04X\n%s\n\n' % (i, fmt(body)))

    glossary = [['类别', '编号', '名称', '说明']]
    for kind, base, size, off in (('人物', CHAR_TABLE, 0x34, 4), ('职业', CLASS_TABLE, 0x54, 4), ('道具', ITEM_TABLE, 0x24, 6)):
        for k, name_id, a in table(rom, tbl, base, size, off):
            glossary.append([kind, '%02X' % k, text(rom, tbl, name_id), text(rom, tbl, rom.u16(a + 2)).replace('\n', ' ')])
    with open(os.path.join(out, '名词表.csv'), 'w', encoding='utf-8-sig', newline='') as f:
        csv.writer(f).writerows(glossary)

    pages = build_pages(rom, tbl, faces)
    for p in pages:
        if 'subpages' in p:  # 支援对话：每个角色一个文件
            os.makedirs(os.path.join(out, p['name']), exist_ok=True)
            for sp in p['subpages']:
                write_txt(sp, os.path.join(out, p['name'], sp['name'] + '.txt'))
            continue
        sub = '章节' if p['name'][:2].isdigit() else ''
        write_txt(p, os.path.join(out, sub, p['name'] + '.txt'))
    fixes = {}  # 堇天纠错（jintian.py 生成）：{文本ID: [(原文锚点, 修正行, (cv号, 条目号))]}
    jt_path = os.path.join(here, 'jintian.json')
    for r in (json.load(open(jt_path, encoding='utf-8')) if os.path.exists(jt_path) else []):
        fix = [(sp, renamer({**JINTIAN_TYPOS, '玛克': '{军师名}'})(t)) for sp, t in r['fix']]
        for i in r.get('ids', []):
            fixes.setdefault(int(i, 16), []).append((r['anchor'], fix, (r['cv'], r['no'])))
    write_site(pages, glossary, os.path.join(here, 'docs'))  # GitHub Pages：main 分支 /docs
    write_site(pages, glossary, os.path.join(here, 'docs'), jt={'fixes': fixes, 'names': JINTIAN_NAMES})

    # 自检：几处人工核对过的原文
    assert '纵横捭阖' in text(rom, tbl, 0x6CD).replace('\n', '')
    assert '克扣我军饷' in text(rom, tbl, 0x7F).replace('\n', '')
    ch = lambda n: open(glob.glob(os.path.join(out, '章节', f'{n:02d}_*.txt'))[0], encoding='utf-8').read()
    assert '琳：刚才的那些家伙们也叫我『琳迪斯』！\n肯特：！难道说……' in ch(1)  # 跨文本沿用头像
    assert '多尔克斯被干掉了' not in ch(3) and '多尔克斯被干掉了' in ch(4)
    print('完成：', out)
