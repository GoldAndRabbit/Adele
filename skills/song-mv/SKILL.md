---
name: song-mv
description: 给一个歌曲视频链接（YouTube 等），产出 4K + 60帧插帧 + 水印 + 原文/中文双语歌词 + FLAC Hi-Res 的成品视频，以及 B 站投稿用的 16:9 / 4:3 封面和元数据 JSON。当用户给出歌曲链接并要求“做视频 / 出 4K60 / 加双语字幕 / 做封面 / 投稿信息”时使用。
---

# 单曲 4K60 双语视频流程

一律用 `.venv/bin/python` 运行；人声分离用 `.venv-sep`（make_mv 会自动调用）。安装见 README。
整场演唱会走 `python -m workflow.live`（方案见 docs/design/concert_pipeline.md），单曲按下面的顺序。

| 步骤 | 命令 | 产物 |
|---|---|---|
| 1. 下载、切片、歌词、人声分离 | `workflow/make_mv.py --name X --url "LINK" --to separate` | `posts/X/` 下 source.mp4、audio.flac、lyrics.txt、vocals.wav |
| 2. 投稿信息（标题、简介、标签） | `workflow/make_meta.py --name X --subtitle-langs "英语,中文" --note "演出名称、日期、场地"` | `posts/X/post/X.json` |
| 3. 字幕：对齐 / 观众合唱 / 讲话断句 / 翻译（直译 + 诗意版）/ 注释 | `-m workflow.song.run post X` | `posts/X/subs/`（lyrics_poetic.ass 是诗意版） |
| 4. 封面 | `workflow/make_cover.py --name X --title "歌名" --subtitle "歌手 · 中英字幕"` | `posts/X/post/cover/` |
| 5. 挂到审核页（字幕预览版 + 封面 + 投稿信息） | `-m workflow.live.singles X` | 审核页「单曲」里多一首（按歌名合并，不影响其他单曲） |
| 6. **用户在审核页看完、确认后**才做 4K 成品 | `-m workflow.song.render post:X` | `posts/X/post/X 4K60FPS Sub-WaterMark.mp4` |

封面和简介都在 4K 之前出，和字幕预览版一起给用户看；字幕、翻译、注释的修改都写进这首的定稿表（zh_fixed.json / zh_notes.json），
不调模型重新生成字幕；用户确认之前不渲染。歌词有现成的（用户给的、OCR 抄下来的、官方简介里的）就事先放到 `posts/X/lyrics.txt`，
第 1 步会跳过 Genius。封面要队徽：`--extra-logo assets/crests/<队>.png`；原视频有频道台标：`--inpaint-static`。

第 6 步会自己补水印计划（workflow/song/watermark.py）、调 make_mv 的 interp（原片已经是 60 帧就不插帧也不抽帧），
渲染 4K + 诗意版字幕 + 左上角 logo + 中间水印 + 原样 FLAC，渲染完删帧。路径约定见 `workflow/paths.py`。

## 硬性要求
- **音轨必须是 FLAC 48kHz/24bit**（B 站 “Hi-Res无损” 标）。render 用 `-c:a copy`，渲染后自动检查，不符直接报错
- **字幕文字只来自参考歌词**（YouTube 官方带时间字幕，或 Genius 歌词文本）；识别结果（Qwen）只用来定位、复核；讲话行用识别文字
- **Claude 不自己写出或改写歌词、不从网页抓歌词贴进对话**：歌词由 `get_ytb_lyrics_from_link.py` 写进本地文件，或用户自己保存；汇报时只给句号、时间点、统计
- 投稿 JSON 里的事实必须有出处（视频简介、用户提供、可查证资料），生成后人工核对；标题 ≤ 80 字，简介 ≤ 2000 字（超了在歌词介绍中间按句号删句）
- 没有用户确认，不做切视频、插帧、加 logo / 水印

## 1. make_mv 参数
- `--name` 短名；`--start/--end` 截取（直播 / 合集）
- 视频有**官方人工字幕**（不是自动字幕）→ `--sub-lang ja` 用它作参考歌词；否则走 Genius（识别不准时 `--song-title/--artist` 或 `--genius-url`）。现场版歌词可能和录音室版不同，提醒用户过一眼
- 需要登录：`--cookies-from-browser chrome`（先征得用户同意）。YouTube 常变，先 `.venv/bin/pip install -U "yt-dlp[default]"`；下载最高 2160p、原声音轨

## 2. 封面（16:9 + 4:3）
```bash
.venv/bin/python workflow/make_cover.py --name X --title "歌名" --subtitle "歌手 · 中日字幕"
.venv/bin/python workflow/make_cover.py --name X --title "歌名" --subtitle "..." --at 65.2 [--text-y 0.80]   # 指定帧
```
- 默认按正脸挑演唱者：正脸特写 `closeup_XX` / 半身 `half_XX` / 全身 `full_XX`，总览图 `candidates_*.jpg` 给用户挑；不够时 `--at` 指定时间补
- 每张同时出 16:9 `cover_XX.jpg` 和 4:3 `cover_XX_4x3.jpg`；画面两角有转播歌名 / 台标用 `--inpaint-corners`；专辑图等外部图 `--image ... --fill extend`
- 用户选定后改名为 `cover_01.jpg` / `cover_01_4x3.jpg`，`posts/X/post/cover/` 只留这两张

## 3. 投稿信息核对
- 标题 `[4K60帧/Hi-Res] 中文名《歌名》英文名 关键词`
- **生成后逐条核对并手改**：模型常把频道口号当演出细节、给罗马字人名乱配汉字、编造材料里没有的事实、用无依据的夸张；不写不确定的成员名字
- 简介只写歌和演出，不写视频制作（字幕收录了什么、画质处理等）

## 4. 投稿到 B 站
- `.venv/bin/python post_bili/upload.py posts/<name>` 只检查并打印要提交的内容；**把输出给用户看，用户确认后**才加 `--submit`
- 第一次投 / 流程改过：加 `--only-self`（仅自己可见），在 B 站上看过效果再公开
- 登录（`bin/biliup -u post_bili/cookies.json login`）要用户自己在终端扫码；细节见 post_bili/README.md
