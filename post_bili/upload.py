#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
B 站投稿，两步，中间只看一个完整的投稿 JSON（post/bili_upload.json）：

  1) 生成  python post_bili/upload.py posts/lorde_acl2026/01_royals
     从投稿草稿 + 成品 + 审核页选的封面 + DEFAULTS 拼出要提交的全部字段，写 post/bili_upload.json 并检查。
     已经有这个文件就不覆盖（你可能手改过），要按草稿重新生成加 --rebuild。
  2) 上传  python post_bili/upload.py posts/lorde_acl2026/01_royals --submit
     只读 post/bili_upload.json，原样提交；先检查，有一项不过就不投。

bili_upload.json 的 key 是 B 站投稿页上的名称（视频文件、封面、标题、类型、转载来源、分区、标签、简介、定时发布、
可见范围、Hi-Res无损、杜比音效、UP主水印、禁止转载、充电），值也是投稿页上的说法；要改哪项直接改这个文件。

读（生成时）：
  单曲   post/<name>.json（make_meta.py）           演唱会 post_draft.json（live/package.py）
  成品   post/<name> 4K60FPS Sub-WaterMark.mp4      封面 = post/<name>_cover_picked_<时间>.png 里最新的一张
写：
  post/bili_upload.json   要提交的全部字段
  post/publish.json       稿件号、提交时间、提交的全部字段；有这个文件就不再重复投（--again 才投）
  logs/publish_<时间>.log biliup 的完整输出
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
    "copyright": 1,         # 1 自制 / 2 转载（转载必须有来源）
    "lossless_music": 1,    # Hi-Res 无损：开（成品音轨必须是 FLAC）
    "dolby": 1,             # 杜比音效：开
    "watermark": 0,         # B 站自动加的「UP 主水印」：不加（成品里已经有自己的 logo / 水印）
    "no_reprint": 0,        # 禁止转载声明：只对自制稿有意义，转载稿不开
    "charging_pay": 0,      # 充电：不开
    "is_only_self": 0,      # 仅自己可见：不开（公开）
}
# bili_upload.json 的字段：key 是 B 站投稿页上的名称，值也写成投稿页上的说法；上传前换成接口字段（API）
COPYRIGHT = {"自制": 1, "转载": 2}
VISIBLE = {"公开": 0, "仅自己可见": 1}
SWITCHES = [("Hi-Res无损", "lossless_music"), ("杜比音效", "dolby"), ("UP主水印", "watermark"), ("禁止转载", "no_reprint"),
            ("充电", "charging_pay")]
TID_NAMES = {29: "音乐 > 音乐现场"}   # 分区号 -> 投稿页上的名称（只给人看，提交用分区号）
KEYS = ["视频文件", "封面16:9", "封面4:3", "标题", "类型", "转载来源", "分区", "分区名称", "新版分区", "标签", "简介", "定时发布", "可见范围"] + [k for k, _ in SWITCHES]


def to_page(f):
    """接口字段 -> bili_upload.json（中文 key）。"""
    out = {"视频文件": f["video"], "封面16:9": f["cover"], "封面4:3": f["cover43"], "标题": f["title"],
           "类型": {v: k for k, v in COPYRIGHT.items()}[f["copyright"]], "转载来源": f["source"],
           "分区": f["tid"], "分区名称": TID_NAMES.get(f["tid"], ""), "新版分区": f["tid_v2"], "标签": f["tag"], "简介": f["desc"],
           "定时发布": datetime.fromtimestamp(f["dtime"]).strftime("%Y-%m-%d %H:%M") if f["dtime"] else "",
           "可见范围": {v: k for k, v in VISIBLE.items()}[f["is_only_self"]]}
    out.update({k: bool(f[api]) for k, api in SWITCHES})
    return out


def dump(j):
    """bili_upload.json 的写法：每项一行（标签也横着放一行），行首空一格。"""
    return "{\n" + ",\n".join(f" {json.dumps(k, ensure_ascii=False)}: {json.dumps(v, ensure_ascii=False)}"
                               for k, v in j.items()) + "\n}\n"


def from_page(j):
    """bili_upload.json（中文 key）-> 接口字段；写错的值直接报错退出。"""
    missing = [k for k in KEYS if k not in j]
    if missing:
        sys.exit(f"bili_upload.json 缺：{missing}")
    if j["类型"] not in COPYRIGHT or j["可见范围"] not in VISIBLE:
        sys.exit(f"类型只能是 {'/'.join(COPYRIGHT)}，可见范围只能是 {'/'.join(VISIBLE)}")
    f = {"video": j["视频文件"], "cover": j["封面16:9"], "cover43": j["封面4:3"], "title": j["标题"], "copyright": COPYRIGHT[j["类型"]],
         "source": j["转载来源"] or "", "tid": int(j["分区"]), "tid_v2": j["新版分区"] or None, "tag": list(j["标签"]),
         "desc": j["简介"], "dtime": dtime_of(j["定时发布"]) if j["定时发布"] else None, "is_only_self": VISIBLE[j["可见范围"]]}
    f.update({api: int(bool(j[k])) for k, api in SWITCHES})
    return f


# 标签固定格式：{歌手中文名} {歌手英文名} {演唱会名} + 下面这几个
TAGS_FIXED = ["欧美音乐", "Billboard", "格莱美", "演唱会", "双语字幕", "欧美现场"]
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
    """返回 (投稿 JSON, 转载来源, (歌手中文名, 歌手英文名, 演唱会名))。
    单曲用 post/<name>.json，演唱会里的一首用 post_draft.json（歌手、演唱会名看 concert.json）。"""
    single = read_json(d / "post" / f"{d.name}.json")
    if single:
        song = single.get("song") or {}
        names = (song.get("artist_zh"), song.get("artist"), (single.get("performance") or {}).get("event"))
        return single, (single.get("source") or {}).get("url") or "", names
    draft = read_json(d / "post_draft.json")
    if draft:
        concert = read_json(ROOT / "concerts" / d.parent.name / "concert.json", {})
        names = (concert.get("artist_zh"), concert.get("artist"), concert.get("title_zh") or concert.get("title"))
        return draft, concert.get("source_url") or "", names
    sys.exit(f"{d} 下没有投稿 JSON（单曲 post/{d.name}.json，演唱会 post_draft.json）")


def description(post):
    """简介：演唱会草稿有现成的 intro_text；单曲把歌曲 / 演出 / 歌词三段介绍用空行连起来。"""
    if post.get("intro_text"):
        return post["intro_text"].strip()
    intro = post.get("intro") or {}
    return "\n\n".join(x.strip() for x in (intro.get("song"), intro.get("performance"), intro.get("lyrics")) if x)


def picked_cover(d, post, r43=False):
    """审核页选定的封面（16:9：post/<name>_cover_picked_<日时分>.png，4:3：..._cover_picked_4x3_<日时分>.png，取最新）；
    没有再用投稿 JSON 里的 files.cover / files.cover_4x3。"""
    picks = sorted(p for p in (d / "post").glob(f"{d.name}_cover_picked_*.png") if ("_4x3_" in p.name) == r43)
    if picks:
        return picks[-1]
    cover = (post.get("files") or {}).get("cover_4x3" if r43 else "cover")
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


def tags_of(names):
    """标签：{歌手中文名} {歌手英文名} {演唱会名} + TAGS_FIXED；去重、去空；超过 20 字的 B 站不收，去掉并打印。"""
    tags = list(dict.fromkeys(t.strip() for t in [*names, *TAGS_FIXED] if t and t.strip()))
    long = [t for t in tags if len(t) > TAG_LEN]
    if long:
        print(f"注意：标签超过 {TAG_LEN} 字，去掉：{long}")
    return [t for t in tags if t not in long][:TAG_MAX]


def dtime_of(at):
    """--at "2026-10-25 20:00"（本机时区）-> 10 位时间戳；必须晚于现在 4 小时。"""
    return int(datetime.strptime(at, "%Y-%m-%d %H:%M").timestamp())


def generate(d, a):
    """从投稿草稿、成品、封面和 DEFAULTS 拼出完整的投稿内容（bili_upload.json 的格式）。"""
    post, source, names = load_post(d)
    video = d / "post" / f"{d.name} 4K60FPS Sub-WaterMark.mp4"
    cover = Path(a.cover).resolve() if a.cover else picked_cover(d, post)
    rel = lambda p: str(p.relative_to(ROOT)) if p else None
    f = {**DEFAULTS, "video": rel(video), "cover": rel(cover), "cover43": rel(picked_cover(d, post, r43=True)), "title": post.get("title") or "", "desc": description(post),
         "tag": tags_of(names), "source": a.source if a.source is not None else source,
         "dtime": int(datetime.strptime(a.at, "%Y-%m-%d %H:%M").timestamp()) if a.at else None}
    if a.tid:
        f["tid"] = a.tid
    if a.tid_v2:
        f["tid_v2"] = a.tid_v2
    if a.only_self:
        f["is_only_self"] = 1
    return to_page(f)


def check(f):
    """提交前检查：有一项不过就不投。返回 (成品规格, 问题列表)。"""
    errors, spec = [], ""
    title, desc, tags = f.get("title") or "", f.get("desc") or "", f.get("tag") or []
    if not title or len(title) > TITLE_MAX:
        errors.append(f"标题 {len(title)} 字（要 1~{TITLE_MAX} 字）")
    if not desc or len(desc) > DESC_MAX:
        errors.append(f"简介 {len(desc)} 字（要 1~{DESC_MAX} 字）")
    if len(tags) > TAG_MAX or any(len(t) > TAG_LEN for t in tags):
        errors.append(f"标签最多 {TAG_MAX} 个、每个不超过 {TAG_LEN} 字")
    if f.get("copyright") == 2 and not f.get("source"):
        errors.append("类型是「转载」必须填「转载来源」；不填来源就把类型改成「自制」")
    if not f.get("cover") or not (ROOT / f["cover"]).exists():
        errors.append("没有 16:9 封面：先在审核页选封面，或在 bili_upload.json 里填「封面16:9」")
    if not f.get("cover43") or not (ROOT / f["cover43"]).exists():
        errors.append("没有 4:3 封面：先在审核页选封面，或在 bili_upload.json 里填「封面4:3」")
    if f.get("dtime") and f["dtime"] - time.time() < DTIME_MIN:
        errors.append("定时发布离现在不到 4 小时，B 站不收")
    video = ROOT / (f.get("video") or "")
    if not f.get("video") or not video.exists():
        errors.append(f"成品不存在：{f.get('video')}")
    else:
        spec, problems = check_spec(video)
        errors += problems
    return spec, errors


def bili_cookies():
    if not COOKIES.exists():
        sys.exit("还没登录：在终端跑 bin/biliup -u post_bili/cookies.json login")
    return {c["name"]: c["value"] for c in read_json(COOKIES)["cookie_info"]["cookies"]}


def upload_cover(path):
    """封面图传到 B 站（网页投稿页传封面的接口），返回图片地址。biliup 只管 16:9 封面，4:3 封面靠这个先传上去，
    再把地址作为 cover43 塞进投稿字段。图转成 JPEG 再传（PNG 太大）。"""
    import base64
    import io
    import requests
    from PIL import Image
    buf = io.BytesIO()
    Image.open(ROOT / path).convert("RGB").save(buf, "JPEG", quality=95)
    jar = bili_cookies()
    r = requests.post("https://member.bilibili.com/x/vu/web/cover/up", cookies=jar, timeout=60,
                      headers={"User-Agent": "Mozilla/5.0", "Referer": "https://member.bilibili.com/platform/upload/video/frame"},
                      data={"cover": "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode(), "csrf": jar.get("bili_jct", "")})
    j = r.json()
    if j.get("code") != 0 or not (j.get("data") or {}).get("url"):
        sys.exit(f"4:3 封面上传失败：B 站返回 {j.get('code')} {j.get('message')}（登录过期就 renew 或重新 login）")
    return j["data"]["url"]


def command(f, line=None, cover43_url=None):
    """bili_upload.json -> biliup upload 命令。走网页投稿接口（--submit web）：4:3 封面（cover43）和
    UP 主水印（watermark）都是网页投稿页的字段，客户端接口不认；biliup 没有这两项的参数，走 --extra-fields。"""
    extra = {"watermark": {"state": f["watermark"]}}
    if cover43_url:
        extra["cover43"] = cover43_url
    cmd = [str(BILIUP), "-u", str(COOKIES), "upload", "--submit", "web",
           "--title", f["title"], "--desc", f["desc"], "--tag", ",".join(f["tag"]), "--cover", str(ROOT / f["cover"]),
           "--tid", str(f["tid"]), "--copyright", str(f["copyright"]),
           "--hires", str(f["lossless_music"]), "--dolby", str(f["dolby"]),
           "--no-reprint", str(f["no_reprint"]), "--charging-pay", str(f["charging_pay"]),
           "--extra-fields", json.dumps(extra)]
    if f.get("source"):
        cmd += ["--source", f["source"]]
    if f.get("tid_v2"):
        cmd += ["--tid-v2", str(f["tid_v2"])]
    if f.get("is_only_self"):
        cmd += ["--is-only-self", "1"]
    if f.get("dtime"):
        cmd += ["--dtime", str(f["dtime"])]
    if line:
        cmd += ["--line", line]
    return cmd + [str(ROOT / f["video"])]


def show(d, f, spec, errors):
    print(f"投稿 JSON  {(d / 'post' / 'bili_upload.json').relative_to(ROOT)}")
    print(f"成品      {f['video']}  {spec}")
    print(f"封面      16:9 {f['cover']}\n          4:3  {f['cover43']}")
    print(f"标题      ({len(f['title'])} 字) {f['title']}")
    print(f"标签      ({len(f['tag'])} 个) {'，'.join(f['tag'])}")
    on = lambda x: "开" if x else "关"
    print(f"分区      {f['tid']} {TID_NAMES.get(f['tid'], '')}" + (f" tid_v2={f['tid_v2']}" if f["tid_v2"] else "")
          + f"   类型 {'转载' if f['copyright'] == 2 else '自制'}   来源 {f['source'] or '（空）'}")
    print(f"选项      Hi-Res {on(f['lossless_music'])}   杜比 {on(f['dolby'])}   B 站水印 {on(f['watermark'])}"
          f"   禁止转载 {on(f['no_reprint'])}   充电 {on(f['charging_pay'])}")
    when = datetime.fromtimestamp(f["dtime"]).strftime("%Y-%m-%d %H:%M") if f["dtime"] else "审核通过后立即"
    print(f"可见      {'仅自己可见' if f['is_only_self'] else '公开'}   发布时间 {when}")
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
    aid = (re.findall(r"\baid\W{0,3}(?:Number\()?(\d+)", text) or [None])[-1]   # biliup 输出 "aid": Number(117493410567800)
    if p.returncode != 0 or not (bvid or aid):
        sys.exit(f"上传失败或没拿到稿件号（退出码 {p.returncode}），完整输出见 {log.relative_to(ROOT)}")
    rec = {"bvid": bvid, "aid": int(aid) if aid else None, "submitted_at": datetime.now().isoformat(timespec="seconds"),
           "log": str(log.relative_to(ROOT)), **fields}
    (d / "post" / "publish.json").write_text(json.dumps(rec, ensure_ascii=False, indent=2) + "\n")
    print(f"已提交 {bvid or 'av' + str(aid)}，记录在 {(d / 'post' / 'publish.json').relative_to(ROOT)}")


def types():
    """用登录凭证向 B 站要投稿分区表（投稿页用的同一个接口），打印各分区的 id；新版分区（tid_v2）如果返回了也一起打。"""
    import requests
    jar = bili_cookies()
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
    p.add_argument("--submit", action="store_true", help="读 post/bili_upload.json 上传；不加只生成 / 检查")
    p.add_argument("--rebuild", action="store_true", help="已有 bili_upload.json 也按草稿重新生成（手改的会被覆盖）")
    p.add_argument("--only-self", action="store_true", help="生成时：仅自己可见")
    p.add_argument("--at", help='生成时：定时发布，本机时间 "YYYY-MM-DD HH:MM"，至少晚于提交 4 小时')
    p.add_argument("--source", help="生成时：转载来源，覆盖投稿 JSON / concert.json 里的")
    p.add_argument("--cover", help="生成时：封面图，覆盖审核页选定的")
    p.add_argument("--tid", type=int, help=f"生成时：投稿分区，默认 {DEFAULTS['tid']}（音乐 > 音乐现场）")
    p.add_argument("--tid-v2", type=int, help="生成时：新版投稿分区号")
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
    jf = d / "post" / "bili_upload.json"
    if a.submit:
        if not jf.exists():
            sys.exit(f"没有 {jf.relative_to(ROOT)}：先不加 --submit 跑一次生成，看过再上传")
    elif not jf.exists() or a.rebuild:
        jf.write_text(dump(generate(d, a)))
        print(f"已生成 {jf.relative_to(ROOT)}")
    else:
        print(f"已有 {jf.relative_to(ROOT)}，按它检查（要按草稿重新生成加 --rebuild）")
    f = from_page(read_json(jf))
    spec, errors = check(f)
    show(d, f, spec, errors)
    if errors:
        sys.exit(1)
    if not a.submit:
        print("\n检查通过。确认 bili_upload.json 无误后加 --submit 上传。")
        return
    if not BILIUP.exists():
        sys.exit("没有 bin/biliup，先跑 post_bili/install.sh")
    bili_cookies()   # 没登录就退出
    url43 = upload_cover(f["cover43"])
    print(f"4:3 封面已上传：{url43}")
    submit(d, {**f, "cover43_url": url43}, command(f, a.line, url43))


if __name__ == "__main__":
    main()
