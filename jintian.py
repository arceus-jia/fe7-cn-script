"""把堇天《狼组•火花汉化版错译盘点》专栏的纠错条目解析出来，并定位到游戏文本，生成 jintian.json。

用法：
  python3 jintian.py <专栏正文txt目录> <readlist.json>   从专栏原文解析并定位
  python3 jintian.py jintian.json                        只按新的规则重新定位（用已解析好的条目，不必重新抓取）
专栏正文需先用浏览器渲染后提取成纯文本（每篇一个 <cv号>.txt），readlist.json 来自
https://api.bilibili.com/x/article/list/web/articles?id=724370
"""
import difflib
import glob
import json
import os
import re
import sys

import fe7text as F
from fe7text import Rom, load_tbl, text, norm, TEXT_COUNT, JINTIAN_ALIASES

# 她文中说话人/人名的其他写法 -> 本 ROM 的说话人名（用于核对说话人、解析支援标题）
SPEAKER_ALIASES = {**{k: v for k, v in JINTIAN_ALIASES.items() if v != '{军师名}'},
                   '霍克艾': '霍凯', '多尔卡斯': '多尔克斯', '罗伊德': '罗依德', '戴斯蒙德': '德斯蒙德', '海尔曼': '桑塔鲁斯'}
SUPPORT_TITLE = re.compile(r'【烈火(?:支援|之剑)[^】]*?([\u4e00-\u9fff]+)/([\u4e00-\u9fff]+)】')

ITEM = re.compile(r'(\d+)、')
# 自动定位不了的条目，手动指定：条目号 -> [(文本ID, 本ROM里的原文, 修正行)]
MANUAL = {
    360: [('0DE0', '刚才那头冰龙……被你亲手打倒的野兽……', [['奈哥尔', '那条冰龙……被你亲手打倒的野兽……']]),  # 原句跨两段文本
          ('0DE1', '就是妮妮安啊。就是那个深爱着你的、你发誓要保护的那个小姑娘啊。', [[None, '就是妮妮安啊。那个仰慕着你的女孩。']])],
    568: [('0071', '可恶！我就是无法集中！', [['海克托尔', '……可恶！这叫我还怎么集中啊！！']])],  # 堇天引用的版本是「呀呀呸的！」
    # 以下只改标点/语气，原文以「=说话人：台词」整行定位
    654: [('0099', '=威尔：哦！', [['威尔', '哎~！']]),
          ('0099', '不过！即便是2岁', [['威尔', '不过啊~即便是2岁']])],  # 中间漏翻的「什~么嘛。」位置无法确定，未加
    704: [('00BB', '=疾：？\n疾：！', [['疾', '？！'], ['疾', '！　！　！']])],
    871: [('011D', '=露依斯：……', [['露易丝', '……？']])],
}
TAG = re.compile(r'【(火花|日文|英文|修正)】(.*)')


def alias(s):
    """堇天抄录火花原文时用的写法换回火花版写法（如 海克托尔 -> 赫克托耳）。"""
    for k, v in JINTIAN_ALIASES.items():
        s = s.replace(k, v)
    return s


def split_speaker(s):
    m = re.match(r'([^：:，。！？…“”「」『』\s]{1,8})[：:](.*)', s)
    return [m.group(1), m.group(2).strip()] if m else [None, s.strip()]


def parse(article):
    items, cur, seen_ref, variant = [], None, False, None
    for ln in article.split('\n'):
        s = ln.replace('**', '').strip()
        if ITEM.fullmatch(s):
            cur, seen_ref, variant = {'no': int(s[:-1]), 'hh': [], 'fix': []}, False, None
            items.append(cur)
            continue
        if variant and s.startswith('（') and '）' in s:  # 「（对艾利乌德）……」：同一句的不同版本，各占一行
            variant[0].append([variant[1], s[s.index('）') + 1:].strip()])
            continue
        m = TAG.match(s)
        variant = None
        if not m or cur is None:
            continue
        tag, body = m.group(1), re.sub(r'（感谢[^）]*）', '', m.group(2)).strip()  # 去掉「（感谢评论区指正）」之类的致谢
        if tag in ('日文', '英文'):
            seen_ref = True
        elif body:
            if tag == '火花' and seen_ref:  # 作者笔误：参考译文之后的【火花】其实是【修正】
                tag = '修正'
            dest = cur['hh'] if tag == '火花' else cur['fix']
            sp, t = split_speaker(body)
            if t:
                dest.append([sp, t])
            else:
                variant = (dest, sp)
    return [it for it in items if it['hh'] and it['fix']]


def best_window(needle, hay):
    """hay 里与 needle 最相似的等长窗口 -> (相似度, 窗口)。"""
    sm = difflib.SequenceMatcher(None, hay, needle, autojunk=False)
    a, _, size = sm.find_longest_match(0, len(hay), 0, len(needle))
    if not needle or size < max(2, min(4, len(needle) // 2)):
        return 0, ''
    # 在最长公共片段附近逐字对齐，窗口取「第一个对上的字」到「最后一个对上的字」，避免多吃或少吃
    seg_lo = max(0, a - len(needle))
    seg = hay[seg_lo:a + size + len(needle)]
    blocks = [b for b in difflib.SequenceMatcher(None, seg, needle, autojunk=False).get_matching_blocks() if b.size]
    if not blocks:
        return 0, ''
    w = seg[blocks[0].a:blocks[-1].a + blocks[-1].size]
    return difflib.SequenceMatcher(None, w, needle, autojunk=False).ratio(), w


def occ_speakers(lines, anchor):
    """anchor 在这段剧本行里每次出现时所在行的说话人。"""
    flat = [(c, li) for li, (_, s) in enumerate(lines) for c, _ in F.norm_chars(s)]
    joined, out, k = ''.join(c for c, _ in flat), [], -1
    while anchor and (k := joined.find(anchor, k + 1)) >= 0:
        out.append(lines[flat[k][1]][0])
    return out


def load_articles(src, readlist):
    """-> [(cv, 标题, 条目列表)]。src 为 jintian.json 时，从已解析的结果还原条目。"""
    if src.endswith('.json'):
        arts = {}
        for r in json.load(open(src, encoding='utf-8')):
            if r['match'] == 'gender':  # 由原条目派生，重新生成
                continue
            items = arts.setdefault(r['cv'], (r['title'], {}))[1]
            items.setdefault((r['no'], json.dumps(r['hh'], ensure_ascii=False)), {'no': r['no'], 'hh': r['hh'], 'fix': r['fix']})
        return [(cv, t, list(items.values())) for cv, (t, items) in arts.items()]
    titles = {a['id']: a['title'] for a in json.load(open(readlist, encoding='utf-8'))['data']['articles']}
    out = []
    for cv, title in titles.items():
        path = os.path.join(src, f'{cv}.txt')
        if os.path.exists(path):
            out.append((cv, title, parse(open(path, encoding='utf-8').read())))
        else:
            print('缺少', cv, title)
    return out


def main(src, readlist, rom_path):
    rom = Rom(rom_path)
    tbl = load_tbl(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fe7_cn.tbl'))
    faces = F.face_names(rom, tbl)
    lines_of = {i: F.script(rom, tbl, i, faces) for i in range(TEXT_COUNT)}
    corpus = {i: norm(''.join(t for _, t in ls)) for i, ls in lines_of.items()}
    corpus = {i: s for i, s in corpus.items() if s}
    known = {sp for ls in lines_of.values() for sp, _ in ls if sp}
    _, _, supports, names = F.quote_tables(rom, tbl)
    pairs = {}
    for a, b, levels in supports:
        pairs.setdefault(frozenset((names.get(a), names.get(b))), set()).update(t for _, t in levels)
    sp_of = lambda sp: SPEAKER_ALIASES.get(sp, sp) if SPEAKER_ALIASES.get(sp, sp) in known else None
    out = []
    for cv, title, items in load_articles(src, readlist):
        titles = {cv: title}
        m = SUPPORT_TITLE.search(title)  # 支援篇：只在这一对的 C/B/A 里找
        pool = pairs.get(frozenset(SPEAKER_ALIASES.get(x, x) for x in m.groups())) if m else None
        if m and not pool:
            print('支援配对没对上', titles[cv])

        def candidates(anchor, sp):
            ids = [i for i, s in corpus.items() if anchor and anchor in s and (pool is None or i in pool)]
            if sp:  # 优先说话人对得上的；原文没标说话人的也算可能
                exact = [i for i in ids if sp in occ_speakers(lines_of[i], anchor)]
                ids = exact or [i for i in ids if None in occ_speakers(lines_of[i], anchor)]
            return ids

        found = []
        for it in items:
            sp = sp_of(it['hh'][0][0])
            anchor = norm(alias(''.join(t for _, t in it['hh'])))
            ids = candidates(anchor, sp)
            if not ids and len(it['hh']) > 1 and len(it['fix']) in (1, len(it['hh'])):  # 多行整体找不到：逐行配对
                for h, f in zip(it['hh'], it['fix'] * len(it['hh']) if len(it['fix']) == 1 else it['fix']):
                    a, s1 = norm(alias(h[1])), sp_of(h[0])
                    found.append(({**it, 'hh': [h], 'fix': [f]}, a, s1, candidates(a, s1)))
                continue
            found.append((it, anchor, sp, ids))
        # 同一篇里只命中一处的条目，确定这篇对应的文本编号范围；多处命中的只取范围内的
        uniq = sorted(ids[0] for *_, ids in found if len(ids) == 1)
        lo, hi = (uniq[0] - 0x30, uniq[-1] + 0x30) if uniq else (0, TEXT_COUNT)
        for n, (it, anchor, sp, ids) in enumerate(found):
            rec = {'cv': cv, 'title': titles[cv], 'no': it['no'], 'hh': it['hh'], 'fix': it['fix'], 'speaker': sp}
            if it['no'] in MANUAL:
                out += [{**rec, 'fix': fix, 'match': 'manual', 'anchor': orig if orig.startswith('=') else norm(orig), 'ids': [tid]}
                        for tid, orig, fix in MANUAL[it['no']]]
                continue
            near = [i for i in ids if lo <= i <= hi] or ids
            if len(near) > 4:  # 还是太多：取离前后条目最近的一处，及紧挨着的重复版本（两篇版本、男女军师版）
                ref = [x[3][0] for x in found[max(0, n - 3):n + 4] if len(x[3]) == 1] or uniq or near
                i0 = min(near, key=lambda i: min(abs(i - r) for r in ref))
                near = [i for i in near if abs(i - i0) <= 3]
            if near:
                rec.update(match='exact', anchor=anchor, ids=[f'{i:04X}' for i in near])
            else:  # 文字有出入（作者抄录差异），找最相似的位置
                scope = [i for i in corpus if (pool is None or i in pool) and (lo <= i <= hi or not uniq)]
                (score, win), i = max((best_window(anchor, corpus[i]), i) for i in scope) if scope else ((0, ''), None)
                if score >= 0.8:  # 包含同样文字的其他文本（如男女军师版）一起改
                    same = [j for j in scope if win in corpus[j] and abs(j - i) <= 3
                            and (not sp or sp in occ_speakers(lines_of[j], win) or None in occ_speakers(lines_of[j], win))] or [i]
                    rec.update(match='fuzzy', score=round(score, 3), anchor=win, ids=[f'{j:04X}' for j in same])
                else:
                    rec.update(match='none', score=round(score, 3))
            out.append(rec)
            # 堇天引用的是女军师版（「玛克小姐」）时，把称呼换成「君」再套到男军师版上
            hh = ''.join(t for _, t in it['hh'])
            if rec.get('ids') and '玛克小姐' in hh:
                a = norm(alias(hh.replace('玛克小姐', '玛克君')))
                male = [i for i, s in corpus.items() if a in s and lo <= i <= hi and f'{i:04X}' not in rec['ids']
                        and min(abs(i - int(x, 16)) for x in rec['ids']) <= 3]
                if male:
                    out.append({**rec, 'match': 'gender', 'anchor': a, 'ids': [f'{i:04X}' for i in male],
                                'fix': [[sp, t.replace('玛克小姐', '玛克君')] for sp, t in it['fix']]})
    with open('jintian.json', 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    from collections import Counter
    print('条目', len(out), Counter(r['match'] for r in out))


if __name__ == '__main__':
    src = sys.argv[1]
    readlist = sys.argv[2] if len(sys.argv) > 2 and not src.endswith('.json') else None
    rom_path = sys.argv[3] if len(sys.argv) > 3 else glob.glob('rom/*.gba')[0]
    main(src, readlist, rom_path)
