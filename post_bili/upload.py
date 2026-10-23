#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
B 站投稿：投稿 JSON + 成品视频 + 审核页选定的封面 -> bin/biliup upload。
默认只检查并打印要提交的内容，加 --submit 才真的上传（投出去就是公开发布，先给人看过再加）。

单曲    python post_bili/upload.py posts/agua_madrid_official
演唱会  python post_bili/upload.py posts/lorde_acl2026/01_royals
先自己看 python post_bili/upload.py posts/agua_madrid_official --only-self --submit
定时    python post_bili/upload.py posts/agua_madrid_official --at "2026-10-25 20:00" --submit

读：
  单曲   post/<name>.json（make_meta.py）           转载来源 = source.url
  演唱会 post_draft.json（live/package.py）         转载来源 = concerts/<场次>/concert.json 的 source_url
  成品   post/<name> 4K60FPS Sub-WaterMark.mp4      封面 = post/<name>_cover_picked_<时间>.png 里最新的一张
写：
  post/publish.json   稿件号、提交时间、提交的全部字段；有这个文件就不再重复投（--again 才投）
  logs/publish_<时间>.log   biliup 的完整输出
"""

import argparse
import json
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BILIUP = ROOT / "bin" / "biliup"
COOKIES = ROOT / "post_bili" / "cookies.json"

# 每次投稿固定的选项（对应 B 站投稿页上的勾选项），要改默认就改这里；字段名是 B 站投稿接口的
DEFAULTS = {
    "tid": 29,              # 分区：音乐 > 音乐现场（旧版分区号）
    "tid_v2": None,         # 新版分区号：登录后 --types 查出「音乐」对应的再填；None 不提交
    "copyright": 2,         # 1 自制 / 2 转载（转载必须有来源）
    "lossless_music": 1,    # Hi-Res 无损：开（成品音轨必须是 FLAC）
    "dolby": 1,             # 杜比音效：开
    "watermark": 0,         # B 站自动加的「UP 主水印」：不加（成品里已经有自己的 logo / 水印）
    "no_reprint": 0,        # 禁止转载声明：只对自制稿有意义，转载稿不开
    "charging_pay": 0,      # 充电：不开
}
TITLE_MAX = 80
DESC_MAX = 2000
TAG_MAX, TAG_LEN = 12, 20   # B 站最多 12 个标签，每个不超过 20 字
DTIME_MIN = 4 * 3600        # 定时发布至少在提交后 4 小时


def read_json(p, default=None):
    p = Path(p)
    return json.loads(p.read_text()) if p.exists() else default


def song_dir(arg):
    """posts/<名> 或 posts/<场次>/<歌>，也接受省掉 posts/ 的写法。"""
    for d in (Path(arg), ROOT / arg, ROOT / "posts" / arg):
        if d.is_dir():
            return d.resolve()
    sys.exit(f"找不到歌曲目录：{arg}")


def load_post(d):
    """返回 (投稿 JSON, 转载来源)。单曲用 post/<name>.json，演唱会里的一首用 post_draft.json。"""
    single = read_json(d / "post" / f"{d.name}.json")
    if single:
        return single, (single.get("source") or {}).get("url") or ""
    draft = read_json(d / "post_draft.json")
    if draft:
        concert = read_json(ROOT / "concerts" / d.parent.name / "concert.json", {})
        return draft, concert.get("source_url") or ""
    sys.exit(f"{d} 下没有投稿 JSON（单曲 post/{d.name}.json，演唱会 post_draft.json）")


def description(post):
    """简介：演唱会草稿有现成的 intro_text；单曲把歌曲 / 演出 / 歌词三段介绍用空行连起来。"""
    if post.get("intro_text"):
        return post["intro_text"].strip()
    intro = post.get("intro") or {}
    return "\n\n".join(x.strip() for x in (intro.get("song"), intro.get("performance"), intro.get("lyrics")) if x)


def picked_cover(d, post):
    """审核页选定的 16:9 封面（post/<name>_cover_picked_<日时分>.png，取最新）；没有再用投稿 JSON 里的 files.cover。"""
    picks = sorted(p for p in (d / "post").glob(f"{d.name}_cover_picked_*.png") if "_4x3_" not in p.name)
    if picks:
        return picks[-1]
    cover = (post.get("files") or {}).get("cover")
    return ROOT / cover if cover and (ROOT / cover).exists() else None


def probe(video):
    """成品规格：分辨率、帧率、音频编码和采样参数。"""
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                        "stream=codec_type,codec_name,width,height,r_frame_rate,sample_rate,bits_per_raw_sample,sample_fmt",
                        "-of", "json", str(video)], capture_output=True, text=True)
    streams = json.loads(r.stdout or "{}").get("streams", [])
    v = next((s for s in streams if s["codec_type"] == "video"), {})
    a = next((s for s in streams if s["codec_type"] == "audio"), {})
    return v, a


def check_spec(video):
    """4K60 + FLAC 48kHz/24bit（Hi-Res 必须 FLAC）。不对就报错，不投。"""
    v, a = probe(video)
    num, den = (v.get("r_frame_rate") or "0/1").split("/")
    fps = float(num) / float(den or 1)
    bits = a.get("bits_per_raw_sample") or ("24" if a.get("sample_fmt") == "s32" else "")
    problems = []
    if (v.get("width"), v.get("height")) != (3840, 2160):
        problems.append(f"分辨率 {v.get('width')}x{v.get('height')}，不是 3840x2160")
    if abs(fps - 60) > 0.1:
        problems.append(f"帧率 {fps:.2f}，不是 60")
    if a.get("codec_name") != "flac":
        problems.append(f"音频 {a.get('codec_name')}，不是 FLAC（Hi-Res 必须 FLAC）")
    if a.get("sample_rate") != "48000" or str(bits) != "24":
        problems.append(f"音频 {a.get('sample_rate')}Hz / {bits or '?'}bit，不是 48kHz/24bit")
    return f"{v.get('width')}x{v.get('height')} {fps:.0f}fps · {a.get('codec_name')} {a.get('sample_rate')}Hz/{bits}bit", problems


def tags_of(post):
    """去重；超过 20 字的 B 站不收，去掉；超过 12 个只留前 12 个。去掉的都打印出来。"""
    tags = list(dict.fromkeys(t.strip() for t in post.get("tags") or [] if t and t.strip()))
    long = [t for t in tags if len(t) > TAG_LEN]
    if long:
        print(f"注意：标签超过 {TAG_LEN} 字，去掉：{long}")
        tags = [t for t in tags if t not in long]
    if len(tags) > TAG_MAX:
        print(f"注意：标签 {len(tags)} 个，B 站最多 {TAG_MAX} 个，去掉最后 {len(tags) - TAG_MAX} 个：{tags[TAG_MAX:]}")
    return tags[:TAG_MAX]


def dtime_of(at):
    """--at "2026-10-25 20:00"（本机时区）-> 10 位时间戳；必须晚于现在 4 小时。"""
    t = int(datetime.strptime(at, "%Y-%m-%d %H:%M").timestamp())
    if t - time.time() < DTIME_MIN:
        sys.exit(f"定时发布 {at} 离现在不到 4 小时，B 站不收")
    return t


def build(d, a):
    """拼出要提交的字段和 biliup 命令；有问题直接退出。"""
    post, source = load_post(d)
    source = a.source or source
    title, desc, tags = post.get("title") or "", description(post), tags_of(post)
    video = d / "post" / f"{d.name} 4K60FPS Sub-WaterMark.mp4"
    cover = Path(a.cover).resolve() if a.cover else picked_cover(d, post)
    errors = []
    if not title or len(title) > TITLE_MAX:
        errors.append(f"标题 {len(title)} 字（要 1~{TITLE_MAX} 字）")
    if not desc or len(desc) > DESC_MAX:
        errors.append(f"简介 {len(desc)} 字（要 1~{DESC_MAX} 字）")
    if not source:
        errors.append("没有转载来源：单曲看 post/<name>.json 的 source.url，演唱会在 concert.json 加 source_url，或用 --source")
    if not cover:
        errors.append("没有封面：先在审核页选封面，或用 --cover 指定")
    spec = ""
    if not video.exists():
        errors.append(f"成品不存在：{video.relative_to(ROOT)}")
    else:
        spec, problems = check_spec(video)
        errors += problems
    opts = {**DEFAULTS, "tid": a.tid or DEFAULTS["tid"], "tid_v2": a.tid_v2 or DEFAULTS["tid_v2"]}
    fields = {
        "title": title, "desc": desc, "tags": tags, "source": source, **opts,
        "only_self": bool(a.only_self), "dtime": dtime_of(a.at) if a.at else None,
        "video": str(video.relative_to(ROOT)), "cover": str(cover.relative_to(ROOT)) if cover else None, "spec": spec,
    }
    cmd = [str(BILIUP), "-u", str(COOKIES), "upload",
           "--title", title, "--desc", desc, "--tag", ",".join(tags), "--cover", str(cover or ""),
           "--tid", str(opts["tid"]), "--copyright", str(opts["copyright"]), "--source", source,
           "--hires", str(opts["lossless_music"]), "--dolby", str(opts["dolby"]),
           "--no-reprint", str(opts["no_reprint"]), "--charging-pay", str(opts["charging_pay"]),
           "--extra-fields", json.dumps({"watermark": {"state": opts["watermark"]}})]   # 水印 biliup 没有单独参数
    if opts["tid_v2"]:
        cmd += ["--tid-v2", str(opts["tid_v2"])]
    if a.only_self:
        cmd += ["--is-only-self", "1"]
    if fields["dtime"]:
        cmd += ["--dtime", str(fields["dtime"])]
    if a.line:
        cmd += ["--line", a.line]
    cmd.append(str(video))
    return fields, cmd, errors


def show(d, f, errors):
    print(f"歌曲目录  {d.relative_to(ROOT)}")
    print(f"成品      {f['video']}  {f['spec']}")
    print(f"封面      {f['cover']}")
    print(f"标题      ({len(f['title'])} 字) {f['title']}")
    print(f"标签      ({len(f['tags'])} 个) {'，'.join(f['tags'])}")
    on = lambda x: "开" if x else "关"
    print(f"分区      tid={f['tid']}" + (f" tid_v2={f['tid_v2']}" if f["tid_v2"] else "")
          + f"   类型 {'转载' if f['copyright'] == 2 else '自制'}   来源 {f['source']}")
    print(f"选项      Hi-Res {on(f['lossless_music'])}   杜比 {on(f['dolby'])}   B 站水印 {on(f['watermark'])}"
          f"   禁止转载 {on(f['no_reprint'])}   充电 {on(f['charging_pay'])}")
    when = datetime.fromtimestamp(f["dtime"]).strftime("%Y-%m-%d %H:%M") if f["dtime"] else "审核通过后立即"
    print(f"可见      {'仅自己可见' if f['only_self'] else '公开'}   发布时间 {when}")
    print(f"简介      ({len(f['desc'])} 字)\n" + "\n".join("  │ " + x for x in f["desc"].splitlines()))
    for e in errors:
        print(f"✗ {e}")


def submit(d, fields, cmd):
    """跑 biliup，输出同时打到终端和 logs/publish_<时间>.log，抓稿件号写 post/publish.json。"""
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log = d / "logs" / f"publish_{stamp}.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    out = []
    with log.open("w") as fh, subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                               text=True, bufsize=1) as p:
        for line in p.stdout:
            sys.stdout.write(line)
            fh.write(line)
            out.append(line)
    text = "".join(out)
    bvid = (re.findall(r"BV[0-9A-Za-z]{10}", text) or [None])[-1]
    aid = (re.findall(r"\baid\W{0,3}(\d+)", text) or [None])[-1]
    if p.returncode != 0 or not (bvid or aid):
        sys.exit(f"上传失败或没拿到稿件号（退出码 {p.returncode}），完整输出见 {log.relative_to(ROOT)}")
    rec = {"bvid": bvid, "aid": int(aid) if aid else None, "submitted_at": datetime.now().isoformat(timespec="seconds"),
           "log": str(log.relative_to(ROOT)), **fields}
    (d / "post" / "publish.json").write_text(json.dumps(rec, ensure_ascii=False, indent=2) + "\n")
    print(f"已提交 {bvid or 'av' + str(aid)}，记录在 {(d / 'post' / 'publish.json').relative_to(ROOT)}")


def types():
    """用登录凭证向 B 站要投稿分区表（投稿页用的同一个接口），打印各分区的 id；新版分区（tid_v2）如果返回了也一起打。"""
    import requests
    if not COOKIES.exists():
        sys.exit("还没登录：在终端跑 bin/biliup -u post_bili/cookies.json login")
    jar = {c["name"]: c["value"] for c in read_json(COOKIES)["cookie_info"]["cookies"]}
    r = requests.get("https://member.bilibili.com/x/vupre/web/archive/pre", cookies=jar,
                     headers={"User-Agent": "Mozilla/5.0", "Referer": "https://member.bilibili.com/"}, timeout=20).json()
    if r.get("code") != 0:
        sys.exit(f"B 站返回 {r.get('code')}：{r.get('message')}（登录过期就 renew 或重新 login）")
    data = r.get("data") or {}
    for key in [k for k in data if "type" in k.lower()]:   # typelist 是旧版；新版分区的键名以返回为准
        print(f"== {key}")
        for t in data[key] if isinstance(data[key], list) else []:
            print(f"{t.get('id')}  {t.get('name')}")
            for c in t.get("children") or []:
                print(f"    {c.get('id')}  {c.get('name')}  {(c.get('desc') or '')[:40]}")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("song", nargs="?", help="歌曲目录：posts/<名> 或 posts/<场次>/<歌>")
    p.add_argument("--types", action="store_true", help="查 B 站投稿分区表（要先登录），用来确认 tid / tid_v2")
    p.add_argument("--submit", action="store_true", help="真的上传；不加只检查和打印")
    p.add_argument("--only-self", action="store_true", help="仅自己可见（第一次试投、想先在 B 站上看效果时用）")
    p.add_argument("--at", help='定时发布，本机时间 "YYYY-MM-DD HH:MM"，至少晚于提交 4 小时')
    p.add_argument("--source", help="转载来源，覆盖投稿 JSON / concert.json 里的")
    p.add_argument("--cover", help="封面图，覆盖审核页选定的")
    p.add_argument("--tid", type=int, help=f"投稿分区，默认 {DEFAULTS['tid']}（音乐 > 音乐现场）")
    p.add_argument("--tid-v2", type=int, help="新版投稿分区号，默认用 DEFAULTS 里的")
    p.add_argument("--line", help="上传线路（biliup upload --help 里列的），默认自动选")
    p.add_argument("--again", action="store_true", help="已经有 post/publish.json 也再投一次")
    a = p.parse_args()
    if a.types:
        return types()
    if not a.song:
        p.error("要给歌曲目录")

    d = song_dir(a.song)
    done = read_json(d / "post" / "publish.json")
    if done and not a.again:
        sys.exit(f"已经投过：{done.get('bvid') or done.get('aid')}（{done.get('submitted_at')}），要再投加 --again")
    fields, cmd, errors = build(d, a)
    show(d, fields, errors)
    if errors:
        sys.exit(1)
    if not a.submit:
        print("\n检查通过。确认无误后加 --submit 上传。")
        return
    if not BILIUP.exists():
        sys.exit("没有 bin/biliup，先跑 post_bili/install.sh")
    if not COOKIES.exists():
        sys.exit("还没登录：在终端跑 bin/biliup -u post_bili/cookies.json login")
    submit(d, fields, cmd)


if __name__ == "__main__":
    main()
