"""一键生成：从汉化版 ROM 提取全部文本，写出纯文本版（output/）和网站（docs/）。

用法：python3 build.py [ROM 路径]（默认取 rom/ 目录下的 .gba）
"""
import csv
import glob
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # 用 python3 -I 运行时也能导入同目录模块
from fe7text import (CHAR_TABLE, CLASS_TABLE, ITEM_TABLE, JINTIAN_NAMES, JINTIAN_TYPOS, TEXT_COUNT, Rom, build_pages,
                     face_names, fmt, load_tbl, script, table, text, unit_data, write_txt)
from fe7site import export_art, renamer, write_site


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    rom = Rom(sys.argv[1] if len(sys.argv) > 1 else glob.glob(os.path.join(here, 'rom', '*.gba'))[0])
    tbl = load_tbl(os.path.join(here, 'fe7_cn.tbl'))
    out, site = os.path.join(here, 'output'), os.path.join(here, 'docs')
    os.makedirs(os.path.join(out, '章节'), exist_ok=True)
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

    fixes = {}  # 堇天纠错（jintian.py 生成）：{文本ID: [(原文锚点, 修正行, (cv号, 条目号), 说话人)]}
    jt_path = os.path.join(here, 'jintian.json')
    for r in (json.load(open(jt_path, encoding='utf-8')) if os.path.exists(jt_path) else []):
        fix = [(sp, renamer({**JINTIAN_TYPOS, '玛克': '{军师名}'})(t)) for sp, t in r['fix']]
        for i in r.get('ids', []):
            fixes.setdefault(int(i, 16), []).append((r['anchor'], fix, (r['cv'], r['no']), r.get('speaker')))

    units = unit_data(rom, tbl)
    shutil.rmtree(site, ignore_errors=True)  # docs/ 全部由脚本生成，先清空，免得留下改名前的旧页面
    os.makedirs(site)
    art = export_art(rom, tbl, faces, pages, units[0], site)
    write_site(pages, glossary, units, site, art=art)  # GitHub Pages：main 分支 /docs
    write_site(pages, glossary, units, site, jt={'fixes': fixes, 'names': JINTIAN_NAMES}, art=art)

    # 自检：几处人工核对过的原文和数据
    assert '纵横捭阖' in text(rom, tbl, 0x6CD).replace('\n', '')
    assert '克扣我军饷' in text(rom, tbl, 0x7F).replace('\n', '')
    ch = lambda n: open(glob.glob(os.path.join(out, '章节', f'{n:02d}_*.txt'))[0], encoding='utf-8').read()
    assert '琳：刚才的那些家伙们也叫我『琳迪斯』！\n肯特：！难道说……' in ch(1)  # 跨文本沿用头像
    assert '多尔克斯被干掉了' not in ch(3) and '多尔克斯被干掉了' in ch(4)
    assert pages[0]['bgs'][0x834] == 'cg/00' and pages[2]['bgs'][0x8BE] == 'cg/02'  # 帐篷里的琳、拔剑的琳
    chars, _, classes = units
    lyn = next(c for c in chars if c['name'] == '琳')
    assert list(lyn['growth'].values())[:7] == [70, 40, 60, 60, 55, 20, 30] and lyn['base']['速度'] == 9
    assert next(c for c in chars if c['name'] == '雷万')['lv'] == 5
    assert [classes[8]['cap'][s] for s in ('力量', '技术', '速度')] == [24, 29, 30]  # 利刃领主
    print('完成：', out, site)


if __name__ == '__main__':
    main()
