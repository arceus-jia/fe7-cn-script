"""把 fe7text 整理好的页面写成 GitHub Pages 静态网站（docs/），并从 ROM 导出网页用到的图片。

网站结构（火花原版在 docs/，堇天修正版在 docs/jt/，两版共用 docs/style.css 和 docs/img/）：
  index.html                首页：章节目录
  story/c00.html…           各章剧情，story/epilogue.html 结局与后日谈
  support/index.html        支援目录，support/supXX.html 每个角色的支援对话
  data/                     资料：角色、职业、名词表
  other/                    阵亡与撤退台词、系统与说明文本
"""
import html
import json
import os
import re
import zlib

import fe7gfx
from fe7text import CHAR_TABLE, JINTIAN_LABEL, JINTIAN_URL, RANKS, STATS, apply_fixes, table, text

esc = html.escape
COVER = 'cg/47'          # 首页封面插画：艾利乌德、赫克托耳、琳
EPILOGUE_IMG = 'cg/50'   # 「结局与后日谈」卡片的配图
PATHS = {'支援对话': 'support/index.html', '阵亡与撤退台词': 'other/death.html',
         '结局与后日谈': 'story/epilogue.html', '其他文本（系统、说明、菜单等）': 'other/misc.html'}
NAV = (('剧情', 'story', 'index.html'), ('支援', 'support', 'support/index.html'),
       ('资料', 'data', 'data/characters.html'), ('其他', 'other', 'other/death.html'), ('搜索', 'search', 'search.html'))
TABS = {'data': (('角色', 'data/characters.html'), ('职业', 'data/classes.html'), ('武器与道具', 'data/items.html'),
                 ('名词表', 'data/names.html')),
        'other': (('阵亡与撤退台词', 'other/death.html'), ('系统与说明文本', 'other/misc.html'), ('游戏音乐', 'other/music.html'))}
ASSET, LINK = '\0', '\1'  # 写页面时的占位前缀：分别换成到 docs/ 根和到本版本根目录的相对路径
SORT_JS = ('<script>document.querySelectorAll("table.sort").forEach(function(t){t.tHead.querySelectorAll("th").forEach(function(th,i){'
           'var b=document.createElement("button");b.type="button";b.textContent=th.textContent;th.textContent="";th.appendChild(b);'
           'b.onclick=function(){var d=th.dataset.d=th.dataset.d?-th.dataset.d:(th.dataset.num?-1:1),body=t.tBodies[0];'
           '[].slice.call(body.rows).sort(function(x,y){var a=x.cells[i].dataset.v,c=y.cells[i].dataset.v;'
           'return (a!=null?a-c:x.cells[i].textContent.localeCompare(y.cells[i].textContent,"zh"))*d})'
           '.forEach(function(r){body.appendChild(r)});t.tHead.querySelectorAll("th").forEach(function(h){h.removeAttribute("aria-sort")});'
           'th.setAttribute("aria-sort",d<0?"descending":"ascending")}})})</script>')
# 旧版网址（所有页面平铺在根目录）-> 新位置；GitHub Pages 找不到页面时显示 404.html，由它跳转
REDIRECT_JS = ('var p=location.pathname,m=!/\\/(story|support|data|other)\\//.test(p)&&p.match(/^(.*?\\/)(jt\\/)?(c\\d\\d|epilogue|support|sup[0-9a-f]{2}|death|misc|names)\\.html$/);'
               'if(m){var n=m[3],to=/^(c\\d\\d|epilogue)$/.test(n)?"story/"+n:n=="support"?"support/index":'
               '/^sup/.test(n)?"support/"+n:n=="names"?"data/names":"other/"+n;'
               'location.replace(m[1]+(m[2]||"")+to+".html"+location.hash)}'
               'else document.getElementById("home").href=p.slice(0,p.indexOf("/",1)+1);')


def renamer(names):
    """火花译名 -> 堇天译名的整体替换函数（长名优先）。"""
    if not names:
        return lambda s: s
    pat = re.compile('|'.join(map(re.escape, sorted(names, key=len, reverse=True))))
    abbr = names.get('赫克托耳', '赫')[:1]  # 章号缩写「赫16章」跟着改
    return lambda s: re.sub(r'赫(?=\d)', abbr, pat.sub(lambda m: names[m.group(0)], s)) if s else s


def page_path(p):
    return f'story/c{p["name"][:2]}.html' if p['name'][:2].isdigit() else PATHS[p['name']]


def write_site(pages, glossary, units, items, music, site, jt=None, art=None):
    """生成一套网页。jt=None 为火花原版（site 根目录）；jt={'fixes', 'names'} 为堇天修正版（site/jt/）：
    fixes: {文本ID: [(原文锚点, 修正行, (专栏cv号, 条目号), 说话人)]}，names: {火花译名: 堇天译名}。
    units / items: fe7text.unit_data / item_data 的结果；music: music.json 的曲目；art: export_art 的结果。"""
    fixes, T = (jt['fixes'], renamer(jt['names'])) if jt else ({}, lambda s: s)
    art = art or {'face': {}, 'portrait': {}}
    applied = set()  # 网页上实际生效的纠错（专栏cv号, 条目号）
    found = []  # 全文搜索的索引：[(页面路径, 出处, 文本ID, 纯文本)]
    out_dir = os.path.join(site, 'jt') if jt else site
    if not jt:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fe7site.css'), encoding='utf-8') as f:
            css = f.read()
        with open(os.path.join(site, 'style.css'), 'w', encoding='utf-8') as f:
            f.write(css)
        open(os.path.join(site, '.nojekyll'), 'w').close()
        with open(os.path.join(site, '404.html'), 'w', encoding='utf-8') as f:
            f.write('<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
                    '<title>页面不存在</title></head>'
                    '<body style="font:17px/1.8 sans-serif;max-width:40em;margin:3em auto;padding:0 16px">'
                    f'<p>找不到这个页面。<a id="home" href="./">回到首页</a></p><script>{REDIRECT_JS}</script></body></html>\n')

    def doc(path, title, body, wide=False, pager=''):
        up = '../' * path.count('/')
        section = path.split('/')[0] if '/' in path else 'story' if path == 'index.html' else path[:-len('.html')]
        cur = lambda on: ' aria-current="page"' if on else ''
        nav = ''.join(f'<a href="{LINK}{href}"{cur(sec == section)}>{label}</a>' for label, sec, href in NAV)
        tabs = ''.join(f'<a href="{LINK}{href}"{cur(href == path)}>{label}</a>' for label, href in TABS.get(section, ()))
        name = os.path.basename(path)
        other = up + ('../' if jt else 'jt/') + path
        hh, jtv = (other, name) if jt else (name, other)
        page = (f'<!doctype html><html lang="zh-CN"{" class=\"jt\"" if jt else ""}><head><meta charset="utf-8">'
                '<meta name="viewport" content="width=device-width,initial-scale=1">'
                f'<title>{esc(T(title))}{f"（{JINTIAN_LABEL}）" if jt else ""}</title><link rel="stylesheet" href="{ASSET}style.css"></head>'
                f'<body><header class="bar"><div class="in"><a class="brand" href="{LINK}index.html">烈火之剑<small>汉化版文本</small></a>'
                f'<nav>{nav}</nav></div></header><main class="{"wide" if wide else "read"}">'
                + (f'<nav class="tabs">{tabs}</nav>' if tabs else '') + body + pager + '</main>'
                f'<div class="ver"><a data-v="hh" href="{hh}">火花原版</a><a data-v="jt" href="{jtv}">{JINTIAN_LABEL}</a></div>'
                '<script>document.querySelectorAll(".ver a").forEach(function(a){a.onclick=function(){'
                'location.href=a.getAttribute("href")+location.hash;return false}})</script></body></html>\n')
        page = page.replace(ASSET, up + ('../' if jt else '')).replace(LINK, up)
        os.makedirs(os.path.dirname(os.path.join(out_dir, path)), exist_ok=True)
        with open(os.path.join(out_dir, path), 'w', encoding='utf-8') as f:
            f.write(page)

    def face(name):
        return f'<img class="av" src="{ASSET}{art["face"][name]}" alt="" loading="lazy">' if name in art['face'] else ''

    def who(name, raw=False):  # 头像 + 名字；每个角色固定一个颜色（按火花名算，两版一致）
        return f'{face(name)}<b style="--h:{zlib.crc32(name.encode()) % 360}">{esc(name if raw else T(name))}</b>'

    def line(sp, s, tag='p', raw=False):  # raw：对照用的火花原文，不换译名
        t = (lambda x: x) if raw else T
        return f'<{tag}>{who(sp, raw)}：{esc(t(s))}</{tag}>' if sp else f'<{tag}>{esc(t(s))}</{tag}>'

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
                       + ''.join(f'<a href="#s{j}">{face(t)}{esc(T(t))}</a>' for t, j in links) + '</p>' for g, links in index)
        return f'<details id="idx" class="jump" open><summary>索引</summary>{rows}</details>'

    def heading(title):  # 「第5章　标题」-> 小字章号 + 标题
        label, _, rest = title.partition('　')
        return f'<h1><small>{esc(T(label))}</small>{esc(T(rest))}</h1>' if rest else f'<h1>{esc(T(title))}</h1>'

    def pagers(seq, i, prev_text, next_text):
        """seq: [(路径, 标题)]；返回 (顶部小链接, 底部大按钮)。"""
        here = seq[i][0]
        rel = lambda path: os.path.relpath(path, os.path.dirname(here))
        prev, nxt = (seq[i - 1] if i else None), (seq[i + 1] if i + 1 < len(seq) else None)
        top = (f'<a href="{rel(prev[0])}">‹ {prev_text}</a>' if prev else '<span></span>') + \
              (f'<a href="{rel(nxt[0])}">{next_text} ›</a>' if nxt else '<span></span>')
        big = (f'<a class="prev" href="{rel(prev[0])}"><small>{prev_text}</small>{esc(T(prev[1]))}</a>' if prev else '') + \
              (f'<a class="next" href="{rel(nxt[0])}"><small>{next_text}</small>{esc(T(nxt[1]))}</a>' if nxt else '')
        return f'<nav class="pager top">{top}</nav>', f'<nav class="pager">{big}</nav>'

    def article(t, tag, lines, src):
        """一段文本 -> (HTML, 是否采用了堇天修正)。src: (页面路径, 出处)，记进搜索索引。"""
        tag_html = f'<span class="tag">{esc(T(tag))}</span>' if tag else ''
        lines, groups = apply_fixes(lines, [(a, f, sp) for a, f, _, sp in fixes.get(t, [])])
        found.append((*src, t, '\n'.join(f'{T(sp)}：{T(x)}' if sp else T(x) for sp, x in lines)))
        if groups:
            applied.update(src for _, _, src, _ in fixes[t])
            links = ''.join(f'<a href="https://www.bilibili.com/read/cv{cv}/" target="_blank">#{no}</a> '
                            for _, _, (cv, no), _ in fixes[t])
            tag_html += f'<span class="src">堇天纠错 {links}</span>'
        return (f'<article id="t{t:04X}"><header><a href="#t{t:04X}">#{t:04X}</a>{tag_html}</header>'
                + render(lines, groups) + '</article>'), bool(groups)

    def ending_card(j, c, path):  # 头像（翻转成面朝正文）+ 称号与名字 + 各段结局
        pics = ''.join(f'<img src="{ASSET}{art["portrait"][n]}" alt="{esc(T(n))}" loading="lazy">'
                       for n in c['who'] if n in art['portrait'])
        epithet, name = c['title']
        src = (path, T('结局与后日谈　' + name))
        found.extend((*src, t, T('　'.join(c['title']))) for t in c['ids'])
        h3 = (''.join(f'<span id="t{t:04X}"></span>' for t in c['ids'])
              + (f'<small>{esc(T(epithet))}</small>' if epithet else '') + esc(T(name)))
        return (f'<section class="ed" id="s{j}"><div class="pic">{pics or "<i></i>"}</div>'
                f'<div><h3>{h3}</h3>{"".join(article(*x, src)[0] for x in c["texts"])}</div></section>')

    def ending_page(p, path, pager):
        body, index, j = [], [], 0
        for g, intro, cards in p['endings']:
            index.append((g, [(c['title'][1 if c['who'] else 0], j + k) for k, c in enumerate(cards)]))  # 军师没有头像，用称号区分
            body.append(f'<h2 id="g{len(index)}">{g}<a class="up" href="#idx">↑ 索引</a></h2><p class="note">{T(intro)}</p>')
            body += [ending_card(j + k, c, path) for k, c in enumerate(cards)]
            j += len(cards)
        doc(path, p['title'], pager[0] + heading(p['title'])
            + f'<figure class="scene"><img src="{ASSET}img/{EPILOGUE_IMG}.png" alt=""></figure>'
            + jump(index).replace(' open>', '>') + ''.join(body), pager=pager[1])

    def text_page(p, path, pager=('', '')):
        if p.get('endings'):
            return ending_page(p, path, pager)
        body = [pager[0], heading(p['title'])]
        if p.get('who') in art['portrait']:
            body.append(f'<img class="portrait" src="{ASSET}{art["portrait"][p["who"]]}" alt="">')
        if p.get('index'):
            body.append(jump(p['index']))
        n_fix = 0
        for j, (head, items) in enumerate(p['sections']):
            if head:
                up = '<a class="up" href="#idx">↑ 索引</a>' if p.get('index') else ''
                body.append(f'<h2 id="s{j}">{esc(T(head))}{up}</h2>')
            src = (path, T(p['title'] + (f'　{head}' if head else '')))
            for t, tag, lines in items:
                if t in p.get('bgs', {}):
                    body.append(f'<figure class="scene"><img src="{ASSET}img/{p["bgs"][t]}.png" alt="" loading="lazy"></figure>')
                html_, fixed = article(t, tag, lines, src)
                body.append(html_)
                n_fix += fixed
        notes = []
        if any('【分支' in tag for _, items in p['sections'] for _, tag, _ in items):
            notes.append('标有【分支n·情况1】【分支n·情况2】的段落是条件分支（如某角色是否在场、战斗中是否触发），'
                         '同一个分支的两种情况，游戏中只会出现其中一种。')
        if n_fix:
            notes.append(f'本页有 {n_fix} 段文本采用了堇天的修正（黄色底色），点句尾「原文」可对照火花原文。')
        if notes:
            body.insert(2, '<div class="note">' + ''.join(f'<p>{n}</p>' for n in notes) + '</div>')
        doc(path, p['title'], ''.join(body), pager=pager[1])

    # 剧情：各章 + 结局，按顺序串起上一章 / 下一章
    chapters = [p for p in pages if p['name'][:2].isdigit()]
    epilogue = next(p for p in pages if p['name'] == '结局与后日谈')
    story = [(page_path(p), p['title']) for p in chapters + [epilogue]]
    for i, p in enumerate(chapters + [epilogue]):
        text_page(p, story[i][0], pagers(story, i, '上一章', '下一章'))

    # 支援：目录页 + 每个角色一页
    sup = next(p for p in pages if p.get('hub'))
    hub = []
    for name, sl, partners in sup['hub']:  # 角色胶囊：点开显示支援对象（同一时间只展开一个），点对象跳到对话
        links = ''.join(f'<a href="{sl}.html#s{j}">{who(o)}<small>{esc(lv)}</small></a>' for o, j, lv in partners)
        hub.append(f'<details name="sup"><summary>{who(name)}<small>{len(partners)}</small></summary>'
                   f'<div class="partners">{links}<a class="all" href="{sl}.html">全部对话</a></div></details>')
    doc('support/index.html', '支援对话',
        '<h1>支援对话</h1><p class="note">点角色展开支援对象，再点对象跳到对话。名字旁的数字是支援对象数，C·B·A 是可进行的支援等级。</p>'
        '<div class="hub">' + ''.join(hub) + '</div>')
    subs = [(f'support/{sp["slug"]}.html', sp['title']) for sp in sup['subpages']]
    for i, sp in enumerate(sup['subpages']):
        text_page(sp, subs[i][0], pagers(subs, i, '上一位', '下一位'))

    for p in pages:  # 其他：阵亡与撤退台词、系统文本
        if page_path(p).startswith('other/'):
            text_page(p, page_path(p))

    write_data(doc, units, items, glossary, T, who)
    write_home(doc, chapters, epilogue, T, jt, len(applied))
    write_search(doc, found, out_dir)
    write_music(doc, music, T)


def stat_table(head, rows, heat=0):
    """可排序的能力表。head: 列名；rows: [(第一格 HTML, [值...])]，值为数字、HTML 文字、(HTML 文字, 排序值) 或 None（显示「—」）；
    heat: 前几个数值列按大小加底色（成长率）。"""
    text_col = [k == 0 or any(isinstance(r[1][k - 1], (str, tuple)) for r in rows) for k in range(len(head))]  # 文字列表头靠左
    th = ''.join(f'<th{" data-num=1" if k else ""}{" class=l" if k and text_col[k] else ""}>{esc(h)}</th>' for k, h in enumerate(head))
    trs = []
    for first, vals in rows:
        tds = []
        for j, v in enumerate(vals):
            if isinstance(v, tuple):
                tds.append(f'<td class="l" data-v="{v[1]}">{v[0]}</td>')
            elif isinstance(v, str):
                tds.append(f'<td class="l">{v}</td>')
            elif v is None:
                tds.append('<td data-v="-999">—</td>')
            else:
                tds.append(f'<td class="g" style="--v:{v}" data-v="{v}">{v}</td>' if j < heat else f'<td data-v="{v}">{v}</td>')
        trs.append(f'<tr><td>{first}</td>{"".join(tds)}</tr>')
    return f'<div class="tbl"><table class="stat sort"><thead><tr>{th}</tr></thead><tbody>{"".join(trs)}</tbody></table></div>'


def write_data(doc, units, items, glossary, T, who):
    chars, shown, classes = units
    growth_stats = [s for s in STATS if s not in ('体格', '移动')]
    label = lambda k: esc(T(classes[k]['label']))

    # 角色：成长率（同名角色只列一次，成长率相同）+ 初期能力（琳篇另有一条的分开列）
    seen, growth_rows = set(), []
    for c in chars:
        g = [c['growth'][s] for s in growth_stats]
        if c['name'] in seen or not any(g):  # 阿特斯不会升级，成长率全是 0
            continue
        seen.add(c['name'])
        growth_rows.append((who(c['name']), g + [sum(g)]))
    base_rows = [(who(c['name']) + ('<small>琳篇</small>' if c['lyn'] else ''),
                  [label(c['class']), c['lv']] + [c['base'][s] for s in STATS]) for c in chars]
    doc('data/characters.html', '角色资料',
        '<h1>角色资料</h1><div class="note"><p>成长率是每次升级时该项能力 +1 的概率（%）。初期能力是角色加入时的数值，已加上职业基础值；'
        '魔法职业的「力量」即魔力。点表头可以排序。</p><p>琳、威尔、肯特、塞因、芙罗利娜、鲁斯在琳篇和艾利乌德篇（赫克托耳篇）加入时的等级和能力不同，分开列出。</p></div>'
        '<h2>成长率</h2>' + stat_table(['角色', *growth_stats, '合计'], growth_rows, heat=len(growth_stats))
        + '<h2>初期能力</h2>' + stat_table(['角色', '职业', 'Lv', *STATS], base_rows) + SORT_JS, wide=True)

    # 职业：上限（只列不是统一 60/20 的）、转职加成、基础值、职业成长率
    default_cap = {**{s: 20 for s in STATS}, 'HP': 60, '幸运': 30, '移动': None}
    cap_stats = [s for s in STATS if s not in ('幸运', '移动')]
    promo_stats = cap_stats[:-1]
    cap_rows = [(label(c['id']), [c['cap'][s] for s in cap_stats]) for c in shown if c['cap'] != default_cap]
    promo_rows = [(label(c['id']), [label(c['to'])] + [classes[c['to']]['promo'][s] for s in promo_stats])
                  for c in shown if not c['promoted'] and c['to'] in classes and any(classes[c['to']]['promo'].values())]
    base_rows = [(label(c['id']), [c['base'][s] for s in STATS if s != '幸运']) for c in shown]
    growth_rows = [(label(c['id']), [c['growth'][s] for s in growth_stats]) for c in shown]
    parts = [('能力上限', '<p class="note">幸运上限都是 30。未列出的职业上限都是 HP 60、其余 20。</p>'
              + stat_table(['职业', *cap_stats], cap_rows)),
             ('转职加成', '<p class="note">转职时各项能力增加的数值。</p>'
              + stat_table(['转职前', '转职后', *promo_stats], promo_rows)),
             ('基础值', '<p class="note">职业本身的能力，角色的能力 = 职业基础值 + 个人加成。</p>'
              + stat_table(['职业', *[s for s in STATS if s != '幸运']], base_rows)),
             ('职业成长率', '<p class="note">只用于敌方单位升级。我方角色升级只看个人成长率（见角色资料）。</p>'
              + stat_table(['职业', *growth_stats], growth_rows, heat=len(growth_stats)))]
    nav = '<details id="idx" class="jump" open><summary>索引</summary><p>' + \
          ''.join(f'<a href="#s{j}">{h}</a>' for j, (h, _) in enumerate(parts)) + '</p></details>'
    doc('data/classes.html', '职业资料',
        '<h1>职业资料</h1><p class="note">同名职业有男女或角色专属的不同版本，括号里是使用这个版本的角色。点表头可以排序。</p>' + nav
        + ''.join(f'<h2 id="s{j}">{h}<a class="up" href="#idx">↑ 索引</a></h2>{body}' for j, (h, body) in enumerate(parts))
        + SORT_JS, wide=True)

    # 武器与道具：按种类分节；等级按 E < D < C < B < A < S < 专用 排序
    rank = lambda r: (esc(T(r)), [*RANKS.values()].index(r) if r in RANKS.values() else 6) if r else None
    rng = lambda r: (r, r[:1])
    wrap = lambda x: f'<span class="w">{esc(T(x))}</span>' if x else ''
    name = lambda i: f'<img class="ic" src="{ASSET}img/i/{i["icon"]:02x}.png" alt="" loading="lazy">{esc(T(i["name"]))}'

    def weapon_row(i):
        eff = i['effective']
        eff_html = f'<span title="{esc(T("、".join(eff[1])))}">{esc(T(eff[0]))}</span>' if eff else ''
        return (name(i), [rank(i['rank']), i['might'] if i['might'] < 255 else None, i['hit'], i['crit'],  # 月食威力 255 表示特殊
                                    i['weight'], rng(i['range']), i['uses'], i['price'], eff_html, esc(T(i['bonus'])), wrap(i['desc'])])
    parts = []
    for kind in dict.fromkeys(i['type'] for i in items):
        group = [i for i in items if i['type'] == kind]
        if kind == '杖':
            body = stat_table(['名称', '等级', '命中', '重量', '射程', '耐久', '价格', '说明'],
                              [(name(i), [rank(i['rank']), i['hit'], i['weight'], rng(i['range']), i['uses'], i['price'],
                                                    wrap(i['desc'])]) for i in group])
        elif kind == '道具':
            body = stat_table(['名称', '次数', '价格', '能力加成', '说明'],
                              [(name(i), [i['uses'], i['price'], esc(T(i['bonus'])), wrap(i['desc'])]) for i in group])
        else:
            body = stat_table(['名称', '等级', '威力', '命中', '必杀', '重量', '射程', '耐久', '价格', '特效', '能力加成', '说明'],
                              [weapon_row(i) for i in group])
        parts.append((kind, body))
    nav = '<details id="idx" class="jump" open><summary>索引</summary><p>' + \
          ''.join(f'<a href="#s{j}">{h}</a>' for j, (h, _) in enumerate(parts)) + '</p></details>'
    doc('data/items.html', '武器与道具',
        '<h1>武器与道具</h1><p class="note">价格是商店买价（单次价格 × 耐久），「—」表示不能买卖。武器等级是装备需要的熟练度，'
        '「专用」的只有该角色能用。鼠标移到特效上可以看到具体职业。点表头可以排序。</p>' + nav
        + ''.join(f'<h2 id="s{j}">{h}<a class="up" href="#idx">↑ 索引</a></h2>{body}' for j, (h, body) in enumerate(parts))
        + SORT_JS, wide=True)

    # 名词表：人物、职业、道具的名称与说明
    kinds = list(dict.fromkeys(r[0] for r in glossary[1:]))
    body = ['<h1>名词表</h1><details id="idx" class="jump" open><summary>索引</summary><p>'
            + ''.join(f'<a href="#s{j}">{k}</a>' for j, k in enumerate(kinds)) + '</p></details>']
    for j, kind in enumerate(kinds):
        uniq = dict.fromkeys((r[2], r[3]) for r in glossary[1:] if r[0] == kind)  # 同名同说明的重复条目只留一条
        rows = ''.join(f'<tr><td>{esc(T(n))}</td><td>{esc(T(desc))}</td></tr>' for n, desc in uniq)
        body.append(f'<h2 id="s{j}">{esc(kind)}<a class="up" href="#idx">↑ 索引</a></h2>'
                    f'<table><tr><th>名称</th><th>说明</th></tr>{rows}</table>')
    doc('data/names.html', '名词表', ''.join(body))


def write_home(doc, chapters, epilogue, T, jt, n_applied):
    def card(p, img):
        label, _, title = p['title'].partition('　')
        pic = f'<img src="{ASSET}img/{img}.png" alt="" loading="lazy">' if img else '<i></i>'
        return f'<li><a href="{LINK}{page_path(p)}">{pic}<span><small>{esc(T(label))}</small>{esc(T(title or label))}</span></a></li>'

    used = set()

    def first_img(p):  # 章节卡片配图：优先用前面卡片没用过的剧情插画，否则用第一张对话背景
        imgs = list(p.get('bgs', {}).values())
        k = next((k for k in imgs if k.startswith('cg/') and k not in used), next((k for k in imgs if k.startswith('bg/')), None))
        used.add(k)
        return k

    grid = lambda ps: '<ul class="chapters">' + ''.join(card(p, first_img(p)) for p in ps) + '</ul>'
    jt_link = f'<a href="{JINTIAN_URL}" target="_blank">堇天《狼组•火花汉化版错译盘点》</a>'
    if jt:
        intro = (f'在火花 × 狼组汉化版的基础上，采用 {jt_link} 的 {n_applied} 条修正替换错译（修改处以黄色底色标出，并附原文章链接），'
                 '人名统一使用堇天的译名。右下角可切回火花原版。')
    else:
        intro = (f'文本出自火花 × 狼组汉化版，仅供查阅参考，版权归原作及汉化组所有。右下角可切换到「{JINTIAN_LABEL}」：'
                 f'采用 {jt_link} 的修正译文替换原版中的错译。')
    quick = (('支援对话', 'support/index.html'), ('角色成长率', 'data/characters.html'), ('职业上限与成长率', 'data/classes.html'),
             ('武器与道具', 'data/items.html'), ('名词表', 'data/names.html'), ('游戏音乐', 'other/music.html'), ('阵亡与撤退台词', 'other/death.html'), ('结局与后日谈', 'story/epilogue.html'))
    hector = T('赫克托耳')
    body = (f'<figure class="cover"><img src="{ASSET}img/{COVER}.png" alt="艾利乌德、{hector}与琳">'
            f'<figcaption><h1>火焰纹章 烈火之剑</h1><p>火花 × 狼组汉化版全文本{f"，{JINTIAN_LABEL}" if jt else ""}</p></figcaption></figure>'
            f'<p class="note intro">{intro}</p>' + search_form('index.html')
            + '<ul class="quick">' + ''.join(f'<li><a href="{LINK}{href}">{t}</a></li>' for t, href in quick) + '</ul>'
            '<h2>琳篇</h2>' + grid(chapters[:12])
            + f'<h2>艾利乌德篇・{hector}篇</h2>' + grid(chapters[12:]).replace('</ul>', card(epilogue, EPILOGUE_IMG) + '</ul>')
            + '<h2>阅读说明</h2><div class="note">'
            + f'<p>{T("章号中「艾」指艾利乌德篇、「赫」指赫克托耳篇。").replace("「赫」", "「" + T("赫1")[0] + "」")}'
            + T('标有【艾利乌德篇】【赫克托耳篇】的段落只在对应篇章出现；标有【分支】的段落是条件分支，同一分支的几种情况游戏中只会出现一种。') + '</p>'
            '<p>每段开头的 #编号 是游戏内文本编号，可以用来精确定位和引用。</p></div>')
    doc('index.html', '烈火之剑 汉化版文本', body, wide=True)


SEARCH_JS = r"""(function(){
var f=document.querySelector("main form.search"),q=f.q,st=document.getElementById("st"),res=document.getElementById("res"),timer;
function esc(s){return s.replace(/[&<>"]/g,function(c){return{"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]})}
function run(){
  var s=q.value.trim(),D=window.SEARCH_DATA;
  try{history.replaceState(null,"",s?"?q="+encodeURIComponent(s):location.pathname)}catch(_){}
  if(!s){st.textContent="";res.innerHTML="";return}
  if(!D){st.textContent="正在载入文本……";return}
  var terms=s.toLowerCase().split(/\s+/),id=/^#?[0-9a-f]{3,4}$/i.test(s)?("000"+s.replace("#","")).slice(-4).toUpperCase():null,hits=[];
  D.e.forEach(function(e){var low=e[2].toLowerCase();
    if(e[1]==id||terms.every(function(w){return low.indexOf(w)>=0}))hits.push(e)});
  st.textContent=hits.length?"找到 "+hits.length+" 段"+(hits.length>200?"，下面列出前 200 段":""):"没有找到包含「"+s+"」的文本";
  var re=new RegExp(terms.map(function(w){return esc(w).replace(/[.*+?^${}()|[\]\\]/g,"\\$&")}).join("|"),"gi");
  res.innerHTML=hits.slice(0,200).map(function(e){
    var p=D.p[e[0]],x=e[2],k=Math.max(0,x.toLowerCase().indexOf(terms[0])),a=x.lastIndexOf("\n",k)+1,b=k+terms[0].length+90;if(k-a>40)a=k-40;
    var snip=(a?"……":"")+x.slice(a,b).replace(/\n/g,"　")+(b<x.length?"……":"");
    return '<li><a href="'+p[0]+"#t"+e[1]+'"><small>'+esc(p[1])+" #"+e[1]+"</small>"+esc(snip).replace(re,"<mark>$&</mark>")+"</a></li>"}).join("")}
f.onsubmit=function(){run();return false};
q.oninput=function(){clearTimeout(timer);timer=setTimeout(run,200)};
q.value=new URLSearchParams(location.search).get("q")||"";
var js=document.createElement("script");js.src="search-data.js";js.onload=run;document.body.appendChild(js);run();
})()"""


def search_form(path):
    return (f'<form class="search" role="search" action="{LINK}search.html"><input type="search" name="q" '
            f'placeholder="搜索台词、人名、地名或文本编号" aria-label="搜索文本"{" autofocus" if path == "search.html" else ""}>'
            '<button>搜索</button></form>')


def write_search(doc, found, out_dir):
    """全文搜索：全部文本写进 search-data.js（用 script 标签载入，本地直接打开网页也能用），在浏览器里查找。"""
    pages, entries = {}, []
    for path, where, t, s in found:
        entries.append([pages.setdefault((path, where), len(pages)), f'{t:04X}', s])
    with open(os.path.join(out_dir, 'search-data.js'), 'w', encoding='utf-8') as f:
        f.write('window.SEARCH_DATA=' + json.dumps({'p': [list(k) for k in pages], 'e': entries},
                                                   ensure_ascii=False, separators=(',', ':')) + ';\n')
    doc('search.html', '全文搜索', '<h1>全文搜索</h1>' + search_form('search.html')
        + '<p class="note">搜索全部剧情、支援对话、阵亡台词、结局和系统文本。多个关键词用空格隔开，表示同时包含；'
          '也可以输入文本编号（如 0940）。</p><p class="note" id="st"></p><ol class="results" id="res"></ol>'
        + f'<script>{SEARCH_JS}</script>')


MUSIC_BASE = 'https://serenesforest.net/wp-content/uploads/2014/06/'
MUSIC_SRC = 'https://serenesforest.net/music/blazing-sword-game-rip/'
MUSIC_JS = """(function(){
var au=document.getElementById("au"),now=document.getElementById("now"),bs=[].slice.call(document.querySelectorAll(".tracks button")),cur=-1;
function play(i){if(cur>=0)bs[cur].removeAttribute("aria-current");cur=i;bs[i].setAttribute("aria-current","true");
  au.src=bs[i].dataset.src;au.play();now.textContent=bs[i].querySelector("span").textContent+"　"+bs[i].querySelector("b").textContent}
bs.forEach(function(b,i){b.onclick=function(){if(i!=cur)play(i);else if(au.paused)au.play();else au.pause()}});
au.onended=function(){if(cur+1<bs.length)play(cur+1)};
})()"""


def write_music(doc, music, T):
    """游戏音乐：音频直接用 Serenes Forest 的游戏原声录音（外链），本站不存音频。"""
    rows = ''.join(f'<li><button type="button" data-src="{MUSIC_BASE}{esc(m["file"])}"><span>{m["no"]:03d}</span>'
                   f'<b>{esc(m["title"])}</b><small>{esc(T(m["note"]))}</small></button></li>' for m in music)
    doc('other/music.html', '游戏音乐',
        f'<h1>游戏音乐</h1><p class="note">音乐室的全部 100 首，加上 4 段音乐室里没有的短曲。音频是 <a href="{MUSIC_SRC}" target="_blank">Serenes Forest</a> '
        '录制的游戏原声，点曲名后直接从该网站播放，播完自动接下一首。曲名是官方英文名，使用场合译自 Serenes Forest 的资料。</p>'
        '<div class="player"><audio id="au" controls preload="none"></audio><p id="now">点下面的曲名开始播放</p></div>'
        f'<ol class="tracks">{rows}</ol><script>{MUSIC_JS}</script>')


def export_art(rom, tbl, faces, pages, chars, items, site):
    """生成网页用到的图片（docs/img/）：说话人头像 f/（脸部 56×56）、支援和结局角色大头像 p/（96×80）、
    对话背景 bg/ 和剧情插画 cg/（240×160）、道具图标 i/（16×16）。返回 {'face': {名字: 路径}, 'portrait': {名字: 路径}}。"""
    name_pid = {}  # 名字 -> 头像编号：人物表登记的优先，其次开发者头像名单
    for _, nid, a in table(rom, tbl, CHAR_TABLE, 0x34, 4):
        name_pid.setdefault(text(rom, tbl, nid), rom.u16(a + 6))
    for pid, name in sorted(faces.items()):
        if name and pid < 0xC0:
            name_pid.setdefault(name, pid)
    speakers, scenes, portraits = {c['name'] for c in chars}, {COVER, EPILOGUE_IMG}, set()

    def walk(ps):
        for p in ps:
            scenes.update(p.get('bgs', {}).values())
            portraits.add(p.get('who'))
            portraits.update(n for _, _, cards in p.get('endings', []) for c in cards for n in c['who'])
            speakers.update(sp for _, items in p['sections'] for _, _, lines in items for sp, _ in lines if sp)
            walk(p.get('subpages', []))
            for name, _, partners in p.get('hub', []):
                speakers.add(name)
                speakers.update(o for o, _, _ in partners)
    walk(pages)
    art = {'face': {}, 'portrait': {}}
    for sub in ('f', 'p', 'bg', 'cg', 'i'):
        os.makedirs(os.path.join(site, 'img', sub), exist_ok=True)
    for name in speakers | portraits:
        pid = name_pid.get(name)
        face = None if pid is None else fe7gfx.face_crop(rom.d, pid)
        if face is None:
            continue
        face.png(os.path.join(site, 'img', 'f', f'{pid:02x}.png'))
        art['face'][name] = f'img/f/{pid:02x}.png'
        if name in portraits:
            fe7gfx.portrait(rom.d, pid).png(os.path.join(site, 'img', 'p', f'{pid:02x}.png'))
            art['portrait'][name] = f'img/p/{pid:02x}.png'
    for k in scenes:  # 'bg/NN' 对话背景，'cg/NN' 剧情插画
        draw = fe7gfx.background if k.startswith('bg/') else fe7gfx.cg
        draw(rom.d, int(k[3:])).png(os.path.join(site, 'img', k + '.png'), alpha=False)
    for k in {i['icon'] for i in items}:
        fe7gfx.icon(rom.d, k).png(os.path.join(site, 'img', 'i', f'{k:02x}.png'))
    return art
