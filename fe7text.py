"""火焰纹章 烈火之剑（AE7J 汉化版）文本解码。地址来自本 ROM 反汇编，换版本需重新确认。"""
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
    for slot, name in SLOT_FIXES.get(i, {}).items():  # 本段从未加载、只能按同组场景补上的位置
        slots.setdefault(slot, name)
    speaker = slots.get(cur)
    fresh = set()  # 本段文本里加载过头像的位置
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
                flush(); speaker = ''.join(pending_name).rstrip('：:'); pending_name = None
        elif c in (0x02, 0x03):
            flush()
        elif 0x08 <= c <= 0x0F:
            flush(); cur = c; speaker = slots.get(c)
        elif c == 0x10:
            flush(); face = b[1] + (b[2] << 8) - 0x100
            name = faces.get(face, '头像%02X' % face)
            for k in [k for k, v in slots.items() if v == name and name and k not in fresh]:
                del slots[k]  # 角色在本段换了位置：从上一段继承来的旧位置作废
            slots[cur] = name; speaker = name; fresh.add(cur)
        elif c == 0x11:
            flush(); slots.pop(cur, None); speaker = None
        elif c == 0x80:
            if b[1] in INLINE:
                buf.append(INLINE[b[1]])
            elif b[1] == 0x23:
                flush(); pending_name = []
            elif b[1] in MOVE_TO:  # 移到有人的位置时两人互换（如波鲁和加斯敏轮流站到前排）
                flush(); to = MOVE_TO[b[1]]
                moving = slots.pop(cur, None)
                if moving is not None:  # 原位置已空（重复的移动指令）时不互换，只切换当前位置
                    other = slots.pop(to, None)
                    slots[to] = moving
                    if other is not None:
                        slots[cur] = other
                cur, speaker = to, slots.get(to)
    flush()
    state['cur'] = cur
    if i in SPEAKER_FIXES:
        lines = [(SPEAKER_FIXES[i].get(s, sp), s) for sp, s in lines]
    return lines


# 本段文本没加载、但同组场景（#0936/#0937/#0940）里固定由该角色站的位置：文本ID -> {位置: 说话人}
SLOT_FIXES = {0x938: {0x0B: '塞拉'}}  # 塞拉受伤的版本，没有加载她的头像
# 原文站位码与实际站位对不上、推断不出的个别段落，按剧情（对照美版剧本）手动指定：文本ID -> {台词: 说话人}
SPEAKER_FIXES = {
    0x940: {'！': '塞拉', '你们为什么和山贼们交战？': '琳', '……被逼的。': '埃克', '就是就是。': '塞拉',
            '我们被误认为和你们一起的了！': '塞拉', '要不是你吵着要来看热闹，我们怎么会被卷进来？': '埃克',
            '对不起，请不要在意我们。': '埃克'},  # 中间一段用的是实际站位的左右镜像位置
}


DEBUG_FACE_TEXTS = range(0x11A6, 0x11AE)  # 开发用头像查看器：「[09]头像A [0C]头像B / 名A、名B」
FACE_SUFFIXES = ('正面', '礼服', '5年后', '怒', '忍', '眠', '操', '悲', '忧', '左', '2', 'F')


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
    faces[0xDF] = '安娜'  # 秘密商店、教学提示、第17章外传村庄都用这个头像
    faces[0xE0] = '肖克'  # 第18章，自称「我是肖克」
    return faces


def table(rom, tbl, base, size, num_off):
    """遍历人物/职业/道具表，返回 [(编号, 名称文本ID, 条目地址)]。"""
    rows, k = [], 1
    while rom.d[base + k * size + num_off] == k and rom.u16(base + k * size) < TEXT_COUNT:
        a = base + k * size
        rows.append((k, rom.u16(a), a)); k += 1
    return rows


STATS = ('HP', '力量', '技术', '速度', '幸运', '守备', '魔防', '体格', '移动')
PLAYABLE = [*range(0x01, 0x0A), 0x0B, *range(0x0D, 0x29), *range(0x2C, 0x35), *range(0x36, 0x39)]  # 我方角色的人物表编号
LYN_ONLY = {0x03, 0x0D, 0x17, 0x18, 0x1C, 0x1D}  # 这几位在琳篇用单独一条数据（艾利乌德篇的在 0x2D～0x32）
JOIN_LEVELS = {0x04: 5, 0x06: 3, 0x07: 8, 0x0F: 4}  # 雷万、疾、卡雷尔、露依斯：作为敌方/友军登场后交谈加入，等级写在关卡部队配置里，人物表里是 1
ENEMY_CLASSES = (0x38, 0x39, 0x43, 0x45, 0x46)  # 只有敌人用的职业：士兵、山贼、封魔者、灾祸招致者、太古的火龙


def unit_data(rom, tbl):
    """我方角色和职业的能力数据（能力按 STATS 顺序，表里没有的项为 None）。
    人物表（0x34 字节）：+5 职业，+0xB 等级，+0xC 起 HP/力/技/速/守/魔防/幸运/体格 的个人加成（有符号），
    +0x1C 起 HP/力/技/速/守/魔防/幸运 成长率。
    职业表（0x54 字节）：+5 转职后（已转职的指回转职前），+0xB 起 HP/力/技/速/守/魔防/体格/移动 基础值，
    +0x13 起 HP～体格 上限（幸运上限固定 30），+0x1B 起成长率，+0x22 起 HP～魔防 转职加成，+0x29 bit0 = 已转职。"""
    d = rom.d
    s8 = lambda b: b - 256 if b > 127 else b
    pick = lambda vals, order: {s: dict(zip(order, vals)).get(s) for s in STATS}  # 数据比 order 短时后面的项为 None
    char_order, class_order = ('HP', '力量', '技术', '速度', '守备', '魔防', '幸运', '体格'), ('HP', '力量', '技术', '速度', '守备', '魔防', '体格', '移动')
    growth_order = ('HP', '力量', '技术', '速度', '守备', '魔防', '幸运')
    classes = {}
    for k, nid, a in table(rom, tbl, CLASS_TABLE, 0x54, 4):
        classes[k] = {'id': k, 'name': text(rom, tbl, nid), 'promoted': bool(d[a + 0x29] & 1), 'to': d[a + 5],
                      'base': pick(d[a + 0xB:a + 0x13], class_order), 'cap': {**pick(d[a + 0x13:a + 0x1A], class_order), '幸运': 30},
                      'growth': pick(d[a + 0x1B:a + 0x22], growth_order), 'promo': pick(d[a + 0x22:a + 0x28], class_order)}
    chars = []
    for k, nid, a in table(rom, tbl, CHAR_TABLE, 0x34, 4):
        if k not in PLAYABLE:
            continue
        c, own = classes[d[a + 5]], pick([s8(b) for b in d[a + 0xC:a + 0x14]], char_order)
        base = {s: (c['base'][s] or 0) + (own[s] or 0) for s in STATS}  # 显示值 = 职业基础值 + 个人加成
        chars.append({'id': k, 'name': text(rom, tbl, nid), 'class': d[a + 5], 'lv': JOIN_LEVELS.get(k, d[a + 0xB]), 'lyn': k in LYN_ONLY,
                      'base': base, 'growth': pick(d[a + 0x1C:a + 0x23], growth_order)})
    # 列出我方用到的职业、它们的转职目标，再加敌方专属职业；同名职业（男女版、三位主角的领主）用第一个使用者区分
    shown = {}
    for ch in chars:
        c = classes[ch['class']]
        shown.setdefault(c['id'], ch['name'])
        if not c['promoted'] and c['to'] in classes:
            shown.setdefault(c['to'], ch['name'])
    for k in ENEMY_CLASSES:
        shown.setdefault(k, None)
    names = [classes[k]['name'] for k in shown]
    for k, user in shown.items():
        c = classes[k]
        c['label'] = f'{c["name"]}（{user}）' if names.count(c['name']) > 1 else c['name']
    return chars, [classes[k] for k in sorted(shown)], classes


ITEM_TYPES = {0: '剑', 1: '枪', 2: '斧', 3: '弓', 5: '理魔法', 6: '光魔法', 7: '暗魔法', 11: '吐息', 4: '杖', 9: '道具', 12: '道具'}
RANKS = {1: 'E', 31: 'D', 71: 'C', 121: 'B', 181: 'A', 251: 'S'}  # 武器等级 = 所需熟练度
ITEM_LOCKS = {0x40000: '艾利乌德', 0x80000: '赫克托耳', 0x100000: '琳', 0x200000: '阿特斯'}  # 专用武器的属性位
EFFECTIVE = {0xD5FB4E: '重甲', 0xD5FB54: '骑兵、重甲', 0xD5FB65: '剑系步兵', 0xD5FB6F: '骑兵',
             0xD5FB7D: '龙', 0xD5FB83: '龙、灾祸招致者', 0xD5FB8A: '飞行'}  # 特效对象表（职业编号列表，0 结束）的概括
BONUS_ORDER = ('HP', '力量', '技术', '速度', '守备', '魔防', '幸运', '移动', '体格')


def item_data(rom, tbl):
    """武器和道具。道具表（0x24 字节）：+0 名称，+2 说明，+7 种类，+8 属性位，+0xC 能力加成表，+0x10 特效对象表，
    +0x14 耐久，+0x15 威力，+0x16 命中，+0x17 重量，+0x18 必杀，+0x19 射程（高 4 位最小、低 4 位最大，最大 0 = 魔力/2），
    +0x1A 单次价格，+0x1C 武器等级，+0x1D 图标。"""
    d, items = rom.d, []
    for k, nid, a in table(rom, tbl, ITEM_TABLE, 0x24, 6):
        kind, attr, uses, rk, rng = d[a + 7], rom.u32(a + 8), d[a + 0x14], d[a + 0x1C], d[a + 0x19]
        if kind not in ITEM_TYPES or kind == 12 and not uses:  # 舞蹈、演奏不是实际道具
            continue
        bonus, eff = rom.u32(a + 0xC) - 0x08000000, rom.u32(a + 0x10) - 0x08000000
        targets = []
        while eff > 0 and d[eff + len(targets)]:
            targets.append(text(rom, tbl, rom.u16(CLASS_TABLE + d[eff + len(targets)] * 0x54)))
        targets = list(dict.fromkeys(targets))
        lock = next((n for bit, n in ITEM_LOCKS.items() if attr & bit), None)
        lo, hi = rng >> 4, rng & 15
        items.append({
            'id': k, 'icon': d[a + 0x1D], 'name': ''.join(s for _, s in script(rom, tbl, nid, {})), 'type': ITEM_TYPES[kind],
            'desc': text(rom, tbl, rom.u16(a + 2)).replace('\n', ' '),
            'rank': RANKS.get(rk) or (f'{lock}专用' if lock else None),
            'might': d[a + 0x15], 'hit': d[a + 0x16], 'crit': d[a + 0x18], 'weight': d[a + 0x17], 'uses': uses or None,
            'range': f'{lo}～魔力/2' if not hi else str(lo) if lo == hi else f'{lo}～{hi}',
            'price': rom.u16(a + 0x1A) * (uses or 1) or None,
            'effective': (EFFECTIVE.get(eff, '、'.join(targets)), targets) if targets else None,  # (概括, 职业名)
            'bonus': '　'.join(f'{s}+{v}' for s, v in zip(BONUS_ORDER, d[bonus:bonus + 9]) if v) if bonus > 0 else ''})
    return items


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
            0x19: (1, 2, False),                       # [条件, A, B]：两版只差头像站位，取 A
            0x1A: (1, 2, False), 0x1B: (1, 2, False)}  # [判断函数, A, B]：条件满足（军师在场/某角色在队）时 A，否则 B
MODE_OPS = (0x0F, 0x12)
BG_OP, BG_COUNT = 'bg', 95  # 场景背景切换（事件指令 0x05，见 chapter_events）
CG_SHOW, CG_FADE, CG_COUNT = 0xD6, 0xDD, 66  # 剧情插画：0xD6 高 16 位是插画编号；0xDD 渐变切换，第 1 个参数是编号
ALT_OPS = (0x1A, 0x1B)
# 事件流程控制：0x42 标签、0x43 无条件跳转、0x44–0x4E 条件判断（第一个参数都是目标标签）。
# 分支剧情里，跳到标签处的文本要沿用跳转前的头像，而不是上一条（另一分支）文本的
# 条件指令也可能以「(长度<<16)|指令」的打包格式出现（如 0x1004C），按低 16 位识别
LABEL_OP, GOTO_OP, IF_OPS = 0x42, 0x43, {*range(0x44, 0x51), 0x55, 0x65}
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
LYN_ENDINGS = 0xDB7D14     # 琳篇结局：每项 12 字节 [人物][结局][负伤时的结局]，文本第一行是称号；人物为 0 结束
ENDING_TITLES = 0xDB85F4   # 本篇结局称号：每项 8 字节 [人物][称号文本]
ENDING_LISTS = 0xDB85EC    # 本篇结局顺序（艾利乌德篇、赫克托耳篇各一份，内容相同）：每项 8 字节 [类型][人物1][人物2][-][文本]；
#                            类型 1 个人结局，2 双人结局（A 支援），3、4 固定一起出场的两人（妮妮安姐弟、潘特夫妇），5 结束
TACTICIAN = 0xCD
TACTICIAN_ENDINGS = (0x1069, 0x106B, 0x106D)  # 本篇军师结局：三种称号，各接一段正文
EPILOGUE_EXTRA = {0x03: [0xFE1], 0x02: [0x1016]}  # 表外的结局文本：琳篇结尾旁白、赫克托耳的另一版个人结局


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
    fixes: [(原文锚点, [(说话人, 修正文)], 说话人或None)]；锚点出现多次时，替换说话人对得上的那一处。"""
    lines, groups = list(lines), []
    for anchor, fix, *who in fixes:
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
            joined, hits, k = ''.join(c for c, _, _ in flat), [], -1
            while anchor and (k := joined.find(anchor, k + 1)) >= 0:
                hits.append(k)
            if not hits:
                continue
            k = next((h for h in hits if who and who[0] and lines[flat[h][1]][0] == who[0]), hits[0])
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


def reuses_faces(raw):
    """文本在加载某个位置的头像之前就用到了它（说话/清除/移动）：说明接着上一段的场面。"""
    loaded, cur = set(), None
    for kind, b in tokens(raw):
        if kind == 'char':
            if cur is not None and cur not in loaded:
                return True
        elif 0x08 <= b[0] <= 0x0F:
            cur = b[0]
        elif b[0] == 0x10:
            loaded.add(cur)
        elif (b[0] == 0x11 or (b[0] == 0x80 and b[1] in MOVE_TO)) and cur is not None and cur not in loaded:
            return True
    return False


# 第11章以后的篇章判断：(顺着执行一侧, 跳到标签一侧)
MODE_IF_OPS = {0x4E: ('【艾利乌德篇】', '【赫克托耳篇】'), 0x55: ('【赫克托耳篇】', '【艾利乌德篇】')}
# 判断触发事件的角色（参数是角色编号）：打包格式 0x1004C 是「是该角色就跳转」，普通格式 0x4C 是「不是该角色就跳转」
CHAR_IF_OP = 0x4C


def branch_tags(ev, k, names):
    """事件里的条件分支 -> {事件下标: 标签}。对每个条件判断，分别求「跳转」和「不跳转」各自能走到、
    而另一边走不到的台词，两边都有台词才算一个分支（游戏中两边只会出现一边）；嵌套分支会有多层标签。"""
    def target(i, lab):  # 跳转目标：之后最近的同号标签（标签号在不同场景间会重复使用）
        return next((j for j in range(i + 1, len(ev)) if ev[j][0] == LABEL_OP and ev[j][1][0] == lab), None)

    def reach(start):
        seen, todo = set(), [start]
        while todo:
            i = todo.pop()
            if i is None or i >= len(ev) or i in seen:
                continue
            seen.add(i)
            op, ids = ev[i]
            if op == GOTO_OP:
                todo.append(target(i, ids[0]))
            else:
                todo.append(i + 1)
                if op in IF_OPS:
                    todo.append(target(i, ids[0]))
        return {i for i in seen if ev[i][0] in TEXT_OPS}

    tags, n, others, named = {}, 0, {}, set()
    for i, (op, ids) in enumerate(ev):
        if op not in IF_OPS:
            continue
        a, b = reach(i + 1), reach(target(i, ids[0]))
        then, other = a - b, b - a
        if op == CHAR_IF_OP and ids[1] in names:  # 按角色判断：两边都有台词才标
            mine, rest = (other, then) if ids[2] else (then, other)
            if mine and rest:
                for p in mine:
                    tags.setdefault(p, []).append(f'【{names[ids[1]]}的情况】')
                named |= mine
                for p in rest:
                    others.setdefault(p, []).append(names[ids[1]])
            continue
        if not then or not other:
            continue
        mode = MODE_IF_OPS.get(op) if k >= 12 else None
        n += not mode
        for side, ps in enumerate((then, other)):
            for p in ps:
                tags.setdefault(p, []).append(mode[side] if mode else f'【分支{n}·情况{side + 1}】')
    for p, ns in others.items():  # 按角色判断时，不属于任何具体角色的一侧
        if p not in named:
            ns = list(dict.fromkeys(ns))
            tags.setdefault(p, []).append(f'【{ns[0]}以外的情况】' if len(ns) == 1 else '【以上角色以外的情况】')
    return {p: ''.join(v) for p, v in tags.items()}


def talk_events(rom, k, names):
    """第 k 章「角色对话」触发的剧情：{文本ID: '【A与B交谈】'}。事件头 +4 是对话表，
    每条 16 字节 [类型3, 事件号][脚本地址][角色A, 角色B]，脚本里第一条显示文本的指令即对话内容。"""
    hdr = rom.u32(POINTER_TABLE + 4 * rom.d[CHAPTER_DATA + k * 0x94]) - 0x08000000
    e, out = rom.u32(hdr + 4) - 0x08000000, {}
    while rom.u16(e) == 3:
        ptr, a, b = rom.u32(e + 4) - 0x08000000, rom.d[e + 8], rom.d[e + 9]
        for x in range(ptr, ptr + 0x40, 4):
            if rom.u32(x) in TEXT_OPS:
                first = TEXT_OPS[rom.u32(x)][0]
                t = rom.u32(x + 4 * (1 + first))
                if 0x800 <= t < TEXT_COUNT and a in names and b in names:
                    out.setdefault(t, f'【{names[a]}与{names[b]}交谈】')
                break
        e += 16
    return out


def chapter_events(rom, k):
    """第 k 章剧情脚本里按顺序出现的文本与流程控制：[(指令, [文本ID...] 或 [标签号])]。"""
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
        elif op >> 16 <= 1 and ((op & 0xFFFF) in (LABEL_OP, GOTO_OP) or (op & 0xFFFF) in IF_OPS) and rom.u32(a + 4) < 0x100:
            out.append((op & 0xFFFF, [rom.u32(a + 4), rom.u32(a + 8), op >> 16]))  # [标签, 条件参数, 是否打包格式]
        elif op & 0xFFFF == 0x05 and op >> 16 < BG_COUNT and any(rom.u32(a + 4 * j) & 0xFF == 0x8D for j in (1, 2, 3)):
            out.append((BG_OP, [f'bg/{op >> 16:02d}']))  # 换背景（高 16 位是背景编号），后面紧跟淡入
        elif op & 0xFFFF == CG_SHOW and op >> 16 < CG_COUNT:
            out.append((BG_OP, [f'cg/{op >> 16:02d}']))
        elif op == CG_FADE and rom.u32(a + 4) < CG_COUNT and rom.u32(a + 8) < 0x10:
            out.append((BG_OP, [f'cg/{rom.u32(a + 4):02d}']))
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
    used = {t for k in events for op, ids in events[k] if op in TEXT_OPS for t in ids}
    starts = sorted((min(t for t in (t for op, ids in events[k] if op in TEXT_OPS for t in ids) if t >= CHAPTER_TEXTS.start), k) for k in events)
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

        story, bgs, bg, shown_bg = [], {}, None, None
        copy = lambda st: {k: v and {'slots': dict(v['slots']), 'cur': v['cur']} for k, v in st.items()}
        for k in ks:
            state, saved, dead = {'A': None, 'B': None, 'alt': None}, {}, False
            btags = branch_tags(events[k], k, names)
            ttags = talk_events(rom, k, names)
            for pos, (op, ids) in enumerate(events[k]):
                if op == BG_OP:
                    bg = ids[0]
                    continue
                if op not in TEXT_OPS:  # 流程控制：记下跳转时的头像状态，跳转后进入标签时恢复
                    if op == LABEL_OP and ids[0] in saved:
                        if dead:  # 只能从跳转进入
                            state = copy(saved[ids[0]])
                        else:  # 分支汇合：顺流路径为准，空着的位置用跳转路径的头像补上
                            state = {k: saved[ids[0]][k] and state[k] and
                                     {'slots': {**saved[ids[0]][k]['slots'], **state[k]['slots']}, 'cur': state[k]['cur']}
                                     or copy(saved[ids[0]])[k] or state[k] for k in state}
                    else:  # 标签号在不同场景间会重复使用，取最近一次跳转
                        saved[ids[0]] = copy(state)
                    dead = op == GOTO_OP
                    continue
                dead = False
                keep = TEXT_OPS[op][2] or reuses_faces(rom.raw(ids[0]))
                if op in MODE_OPS:
                    tracks = [('A', ids[0], '【艾利乌德篇】'), ('B', ids[1], '【赫克托耳篇】')]
                elif op in ALT_OPS:  # 另一分支从同一场面开始，显示完回到主线
                    state['alt'] = copy(state)['A']
                    tracks = [('A', ids[0], ''), ('alt', ids[1], '【另一分支】')]
                else:  # 只输出第一版，另一版只记为已处理
                    tracks = [('A', ids[0], '')]
                    done.update(ids[1:])
                for track, t, tag in tracks:
                    st = state.get(track) if keep and state.get(track) else {'slots': {}, 'cur': None}
                    lines = script(rom, tbl, t, faces, st)
                    state[track] = st
                    if op not in MODE_OPS and track == 'A':
                        state['B'] = {'slots': dict(st['slots']), 'cur': st['cur']}
                    if t not in done and lines:
                        story.append((t, btags.get(pos, '') + ttags.get(t, '') + tag, lines))
                        if bg is not None and bg != shown_bg:  # 背景换了：在这一段前面放背景图
                            bgs[t] = shown_bg = bg
                    done.add(t)
        sections.append(('剧情', story))
        rest = entries(t for k in ks for t in leftovers.get(k, []))
        if rest:
            sections.append(('本章其他文本（战斗对话、阵亡台词、村庄、教学提示等）', rest))
        pages.append({'name': f'{n:02d}_{label}_{title}', 'title': f'{label}　{title}', 'sections': sections, 'bgs': bgs})

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
        subpages.append({'name': f'{n:02d}_{name}', 'title': f'{name}的支援对话', 'slug': slug, 'who': name,
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

    pages.append(ending_page(rom, tbl, names, entries, done))
    pages.append({'name': '其他文本（系统、说明、菜单等）', 'title': '其他文本（系统、说明、菜单等）',
                  'sections': [('', entries(range(TEXT_COUNT)))]})
    return pages


def ending_page(rom, tbl, names, entries, done):
    """结局与后日谈，按 ROM 里的结局表排成卡片：'endings': [(分组, 说明, [{'who': [头像角色], 'title': (称号, 名字),
    'ids': [称号文本ID], 'texts': [(文本ID, 标签, 剧本行)]}])]；'sections' 是同样内容的纯文本版。"""
    def body(t, tag=''):
        return entries([t], tag=lambda _: tag)

    def title(t):  # 「称号　名字」
        epithet, _, name = script(rom, tbl, t, {})[0][1].partition('　')
        return epithet, name

    lyn, a = [], LYN_ENDINGS
    while rom.u32(a):
        c, ok, hurt = rom.u32(a), rom.u32(a + 4), rom.u32(a + 8)
        name = '{军师名}' if c == TACTICIAN else names[c]
        texts = body(ok) + body(hurt, '另一版本' if c == TACTICIAN else '负伤时')
        epithet = texts[0][2][0][1].partition('　')[0]
        for k, (t, tag, lines) in enumerate(texts):  # 去掉开头的「称号　名字」
            s = lines[0][1].partition('　')[2]
            assert s.startswith(name), (hex(t), s)
            texts[k] = (t, tag, [(None, s[len(name):])] + lines[1:])
        texts = texts[:1] + [x for e in EPILOGUE_EXTRA.get(c, []) for x in body(e)] + texts[1:]
        lyn.append({'who': [] if c == TACTICIAN else [name], 'title': (epithet, name), 'ids': [], 'texts': texts})
        a += 12

    order = []
    for k in range(2):
        a = rom.u32(ENDING_LISTS + 4 * k) - 0x08000000
        while rom.d[a] != 5:
            order.append((rom.d[a], rom.d[a + 1], rom.d[a + 2], rom.u32(a + 4)))
            a += 8
    order = list(dict.fromkeys(order))
    titles, a = [], ENDING_TITLES
    while rom.u32(a):
        titles.append((rom.u32(a), rom.u32(a + 4)))
        a += 8
    solo, seen = [], set()
    for c, _ in titles:
        if c in seen:
            continue
        both = next((e for e in order if e[0] in (3, 4) and c in e[1:3]), None)  # 固定一起出场的两人合成一张卡
        members = [m for m, _ in titles if m in (both[1:3] if both else (c,))]
        seen.update(members)
        ids = [t for m, t in titles if m in members]
        done.update(ids)
        heads = [title(t) for t in ids]
        texts = [x for m in members for ty, c1, _, t in order if ty == 1 and c1 == m for x in body(t)]
        texts += [x for m in members for e in EPILOGUE_EXTRA.get(m, []) for x in body(e, '另一版本')]
        if both:
            ty, c1, c2, t = both
            texts += body(t) + (body(t + 1, f'{names[c1]}负伤时') + body(t + 2, f'{names[c2]}负伤时') if ty == 4 else [])
        solo.append({'who': [names[m] for m in members], 'ids': ids, 'texts': texts,
                     'title': ('、'.join(dict.fromkeys(e for e, _ in heads)), ' × '.join(n for _, n in heads))})
    for t in TACTICIAN_ENDINGS:
        done.add(t)
        solo.append({'who': [], 'title': title(t), 'ids': [t], 'texts': body(t + 1)})
    pairs = [{'who': [names[c1], names[c2]], 'title': ('', f'{names[c1]} × {names[c2]}'), 'ids': [], 'texts': body(t)}
             for ty, c1, c2, t in order if ty == 2]

    groups = [('琳篇', '琳篇通关后显示。在琳篇的战斗中负伤撤退的同伴，显示「负伤时」的版本。', lyn),
              ('个人结局', '艾利乌德篇、赫克托耳篇通关后，按角色依次显示。', solo),
              ('双人结局', '两人的支援对话进行到 A 级时，结局显示这段双人结局，代替两人各自的个人结局。', pairs)]
    sections = []
    for g, _, cards in groups:
        sections.append((g, []))
        sections += [('　'.join(filter(None, c['title'])), c['texts']) for c in cards]
    return {'name': '结局与后日谈', 'title': '结局与后日谈', 'endings': groups, 'sections': sections}


def write_txt(page, path):
    body = [f'# {page["title"]}']
    for head, items in page['sections']:
        if head:
            body.append(f'【{head}】')
        body += [f'#{t:04X}{tag}\n{fmt(lines)}' for t, tag, lines in items]
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n\n'.join(body) + '\n')
