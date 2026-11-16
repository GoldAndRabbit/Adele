# 投稿信息统一流程

演唱会入口使用 `workflow.live.package.draft_meta`。它调用 `workflow.make_meta.generate_intro`，依据本曲资料、参考歌词与实际预览画面生成歌曲、演出、歌词三部分。先写完整初稿，短稿保留后补写，超长稿按完整句子删减到 1800–2000 字符。已有合格正文直接复用；占位文字不视为完成。

`post_draft.json` 的 `intro.song`、`intro.performance`、`intro.lyrics` 是正文来源，`intro_text` 为兼容字段。三部分齐备时，以三部分拼接结果为准。人工审核的 `review.json` 中明确设置的标题、简介和标签优先。

B站自动标题统一调用 `workflow.bili_title`，顺序固定为「歌手中文名 英文歌名 歌手中文昵称 歌手英文名 中文歌名 演出信息 关键词」，字段间用空格，不再添加点号。单曲和串烧共用此顺序；多人和串烧的简写先在对应字段内完成。标题最多80字符，演唱会／节目名称必须保留。超出时先从末尾逐项移除通用关键词，再减少昵称、使用已核对的较短演出名称，最后才整项省略中文歌名译名；保留字段的显示顺序不变。歌手、完整英文首曲名与演出信息仍放不下时，要求人工提供经核对的简称，不自动删掉演出信息或硬截词。整场演出名已包含在歌名字段中的不重复添加；不强制78–80字或规格前缀。已人工填写的标题经过导出、封面同步、投稿预检仍保留；已导出资料和线上历史标题的同步是独立步骤，不能把修改生成器等同于同步已完成。

`workflow.delivery_bundle.write_bundle` 是两平台共同导出入口。`post/bili_upload.json`、`vertical/douyin_submission.json`、`delivery_bundle.json` 都是派生产物，不得把其中的旧正文作为下一轮生成的输入。重建时更新标题、正文、标签和有效封面，保留可见范围、定时等投稿设置。抖音描述从同一份最终 B 站正文的首段派生。

审核页、完整投稿 JSON、复制内容和后续发布都使用 `submission_records`。封面发布经 `sync_cover_release` 调用同一个导出入口，因此新增封面不能把旧简介写回去。以实际导出的正文与页面 API 为验收依据，不能只统计草稿是否存在。标准打包与投稿前检查均拒绝不足 1800 字符的占位简介；审核修改仍保留原文，但未满足格式的版本不得自动视为投稿就绪。

封面统一走 `workflow.fibo_concert` / `workflow.reviewed_cover`：本曲原帧比较、FIBO 原始 AI 母图、四版试排、视觉复核、摘要校验发布、同步路径。替换生成器需要用户明确指示；已弃用的试图只保留备份，不在正式 masters/variants 清单中选用。

所有本机分离和 FIBO 批处理在加载模型前共用内置盘 `~/Library/Caches/adele/separator.lock`，每台同时只运行一个重型模型任务。不同 Mac 可各运行一个任务。

回归检查：`.venv/bin/python -m unittest tests.test_posting_content_flow tests.test_posting_cover tests.test_review tests.test_bili_title_budget tests.test_bili_metadata_title`。
