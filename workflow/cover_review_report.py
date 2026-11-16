"""Write an offline before/after contact sheet for a reviewed cover batch."""
import argparse
from collections import Counter
from html import escape
import json
import hashlib
from pathlib import Path

from workflow.live.paths import read_json


def report(directory):
    rows = read_json(directory/'repairs.json')
    body = []
    methods = Counter()
    full_ai = 0
    cases = set()
    failures = []
    for row in rows:
        folder = f"case-{row['index']:02}"
        stage = directory/folder/'stage'
        revision = read_json(stage/'stage.json', {})
        receipt = read_json(stage/'verified.json', {})
        if (not receipt or not revision or receipt['master'] != revision['master']['file']
                or receipt['review_hash'] != hashlib.sha256((stage/'stage.json').read_bytes()).hexdigest()):
            failures.append(row['name'])
            continue
        master = revision['master']
        methods[master['label']] += 1
        # Older releases have model provenance but predate artwork_method.
        is_full = master.get('artwork_method') == 'full_ai' if 'artwork_method' in master else (
            'fibo' in master.get('model', '').lower() and not master.get('postprocess'))
        full_ai += int(is_full)
        if row.get('case'):
            cases.add(row['case'])
        raw = f'{folder}/raw.jpg'
        old = f'{folder}/before.jpg'
        pictures = [('原封面', old), ('原片选帧', raw), ('无字母图', f'{folder}/stage/art.png')]
        variants = [('B站 16:9','bili-ai-16x9'),('B站 4:3','bili-ai-4x3'),
                    ('抖音 3:4','douyin-ai-3x4'),('抖音 4:3','douyin-ai-4x3')]
        pictures += [(name, f'{folder}/stage/{filename}.jpg') for name, filename in variants]
        cells = []
        for name, path in pictures:
            content = (f'<a href="{path}"><img loading="lazy" src="{path}" alt="{name}"></a>'
                       if (directory/path).is_file() else '<span>此前缺封面</span>')
            cells.append(f'<figure><figcaption>{name}</figcaption>{content}</figure>')
        req = read_json(directory/folder/'request.json')
        start = (req.get('slice') or [0])[0]
        seconds = revision['source_time']-start
        label = f"反馈 {row['case']}" if row.get('case') else '补充曲目'
        details = {k:master[k] for k in ('label','model','runtime','precision','source_time','generation_seconds',
                   'elapsed_seconds','peak_process_gb','started_at','finished_at','prompt','postprocess') if k in master}
        details.update(reviewed=receipt['verified_at'], master=master['file'])
        ui = 'http://127.0.0.1:8160/#/'+row['route']+'/'+row['name']
        body.append(f'<article><h2>{escape(row["title"])} <small>{label}</small></h2>'
                    f'<p>{escape(row["note"])} · {escape(row["name"])} · 单曲 {int(seconds//60)}:{seconds%60:04.1f}'
                    f' · {escape(master["label"])}</p><div class="grid">{"".join(cells)}</div>'
                    f'<p><a href="{ui}">打开歌曲</a>　<a href="{folder}/selection/shortlist.jpg">候选帧试排</a>'
                    f'　<a href="{folder}/stage/review.jpg">原片、处理输入与四版对照</a></p>'
                    f'<details><summary>运行记录</summary><pre>{escape(json.dumps(details,ensure_ascii=False,indent=2))}</pre></details></article>')
    summary = f'{len(cases)} 条反馈 · {len(body)} 个视频版本 · {len(body)*4} 张已验证封面 · {full_ai} 个完整 AI 母图'
    doc = f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>封面修复对照</title><style>
*{{box-sizing:border-box}}body{{margin:0;padding:24px;background:#14171d;color:#f4f4f4;font:16px system-ui}}
article{{border-top:1px solid #46505e;padding:12px 0 20px}}h1,h2,p{{margin:9px 0}}h2{{font-size:20px}}
small,p,figcaption{{color:#b4bdca}}a{{color:#9dc7ff}}.grid{{display:grid;grid-template-columns:repeat(7,minmax(0,1fr));gap:8px}}
figure{{margin:0}}img{{width:100%;height:clamp(110px,13vw,215px);object-fit:contain;object-position:top center}}
figcaption{{font-size:13px;margin:8px 0}}pre{{white-space:pre-wrap;overflow-wrap:anywhere}}
@media(max-width:760px){{.grid{{grid-template-columns:repeat(2,minmax(0,1fr))}}img{{height:175px}}}}
</style><h1>封面修复对照</h1><p>{summary}</p>{''.join(body)}</html>'''
    (directory/'index.html').write_text(doc, encoding='utf-8')
    return {'summary':summary, 'methods':dict(methods), 'outstanding':failures}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    print(json.dumps(report(parser.parse_args().directory), ensure_ascii=False, indent=2))
