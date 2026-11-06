// adele 审核页：纯 JS，无构建（结构拷自 SubDub web/app.js）。
// 路由 #/<场次>（总览）、#/<场次>/<歌>[@秒]（单曲审核）
"use strict";

const $ = (sel, el = document) => el.querySelector(sel);
const h = (tag, attrs = {}, ...kids) => {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null || v === false) continue;
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "value") el.value = v;
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const k of kids.flat()) if (k != null) el.append(k.nodeType ? k : document.createTextNode(k));
  return el;
};
const fmt = (t) => {
  if (t == null) return "–";
  const m = Math.floor(t / 60), s = t - m * 60;
  return `${m}:${s.toFixed(1).padStart(4, "0")}`;
};
const hms = (t) => {
  if (t == null) return "–";
  const H = Math.floor(t / 3600), m = Math.floor((t % 3600) / 60), s = t % 60;
  return `${H}:${String(m).padStart(2, "0")}:${s.toFixed(1).padStart(4, "0")}`;
};
const api = async (p, body) => {
  const r = await fetch(p, body === undefined ? undefined
    : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!r.ok) {
    let msg = `${r.status}`;
    try { msg = (await r.json()).detail || msg; } catch (e) { /* 不是 JSON */ }
    throw new Error(msg);
  }
  return r.json();
};

const REVIEW = { pending: ["待审", "gray"], approved: ["已通过", "ok"], rejected: ["已打回", "bad"], stale: ["通过后有改动", "warn"] };
const STAGE = { new: "未开始", lyrics: "只有歌词", located: "已定位", refined: "字幕已出", packaged: "可审核", hd_done: "高清已出" };
const SHOT = { closeup: "特写", half: "半身", full: "全身", scene: "氛围 / 舞台", cover: "补充" };

const state = { concerts: [], concert: null, song: null, cleanup: [] };

// ---------------------------------------------------------------- sidebar

function searchText(text) {
  return text.normalize("NFKD").toLowerCase().replace(/[^\p{L}\p{N}]/gu, "");
}

function renderNavigation(route) {
  const input = $("#song-search");
  const query = searchText(input.value);
  if (!input.value.trim()) {
    $("#concerts").replaceChildren(...state.concerts.map(x => {
      const total = x.tracks.length;
      const done = x.tracks.filter(track => track.portrait_release_ready).length;
      const rate = total ? Math.round(done / total * 100) : 0;
      return h("a", {href: `#/${x.slug}`, class: "group-link" + (x.slug === route.slug ? " active" : "")},
        h("span", {class:"group-name"}, x.title),
        h("span", {class:"group-metrics"},
          Number(x.fps) > 0 ? h("span", {class:"group-fps", title:"原片帧率"}, `${Number(Number(x.fps).toFixed(2))} fps`) : null,
          h("span", {class:"release-rate", title:`竖屏成片率：${done}/${total} 首`,
            "aria-label":`竖屏成片率 ${rate}%`}, rate + "%")));
    }));
    return;
  }
  const matches = state.concerts.flatMap(group => (group.tracks || [])
    .filter(track => query && searchText(track.title).includes(query))
    .map(track => h("a", {href: `#/${group.slug}/${track.name}`, onclick: () => {
      input.value = "";
      renderNavigation(parseRoute());
    }}, track.title, h("small", {}, [group.title, track.notes].filter(Boolean).join(" · ")))));
  $("#concerts").replaceChildren(...(matches.length ? matches : ["未找到匹配的歌曲"]));
}
$("#song-search").addEventListener("input", () => renderNavigation(parseRoute()));

function renderSidebar(route) {
  const c = state.concert;
  renderNavigation(route);
  const ul = $("#songs");
  if (!c) { ul.replaceChildren(); return; }
  const songs = Object.fromEntries(c.songs.map((s) => [s.name, s]));
  const songNumbers = new Map(c.songs.map((song, index) => [song.name, String(index).padStart(2, "0")]));
  const pool = h("li", {}, h("a", { href: `#/${c.slug}/~covers`, class: route.name === "~covers" ? "active" : null,
    title: "整场演唱会的画面都能给任何一首当封面" }, h("span", { class: "pool-link-label" }, "封面池")));
  const kind = state.concerts.find(x => x.slug === route.slug)?.kind;
  ul.replaceChildren(...(c.has_cover_pool ? [pool] : []), ...c.items.map((it) => {
    if (it.kind !== "song") return h("li", { class: "tape", title: "过场（预录视频），不出成品" }, `~ ${it.title}`);
    const s = songs[it.name];
    const warn = s.start == null || (s.confidence != null && s.confidence < 0.5) || s.needs_refine;
    const source = kind === "artist" ? s.notes : c.info.title;
    const artist = s.artist || c.info.artist;
    const prefix = artist && artist + " - ";
    const note = prefix && source?.toLowerCase().startsWith(prefix.toLowerCase())
      ? source.slice(prefix.length) : source;
    const label = note ? `${it.title} · ${note}` : it.title;
    const badge = (text, ready, status, extraClass = "") => h("span", {
      class: `song-cover-status ${extraClass}${ready ? " selected" : ""}`, title: status, "aria-label": status
    }, text);
    return h("li", {class: "song-row"}, h("a", { href: `#/${c.slug}/${it.name}`, class: route.name === it.name ? "active" : null, title: label },
      h("span", {class:"song-number"}, songNumbers.get(it.name)),
      h("span", { class: "song-list-title" }, it.title),
      h("span", { class: "song-list-badges" },
        badge("封", s.portrait_cover_selected, s.portrait_cover_selected ? "已选竖屏封面" : "待选竖屏封面", "portrait-badge"),
        badge("字", s.subtitles_ready, s.subtitles_ready ? "已产出字幕" : "尚未产出字幕"),
        badge("详", s.post_ready, s.post_ready ? "抖音投稿文案已就绪" : "待补抖音投稿信息"),
        badge("成", s.portrait_release_ready, s.portrait_release_ready ? "已有竖屏成片" : "暂无竖屏成片", "portrait-badge")),
      warn ? h("span", { class: "warn", title: s.needs_refine ? "边界改过，需要重跑精校" : "定位置信度低" }, "⚠") : null));
  }));
}

function postPane(song) {
  const post = song.bili_upload ? JSON.parse(song.bili_upload) : {};
  const draft = song.draft || {};
  const title = post["标题"] || draft.title || "";
  const fields = [["标题", title], ["简介", post["简介"] || draft.intro_text],
    ["标签", post["标签"] || draft.tags], ["分区", post["分区名称"]], ["转载来源", post["转载来源"]],
    ["完整投稿 JSON", song.bili_upload]].filter(([, value]) => value?.length);
  if (!fields.length) return h("div", {class: "post-info"}, "这首歌暂无投稿内容。");

  const rows = fields.map(([label, value]) => {
    const text = Array.isArray(value) ? value.join("、") : value;
    const copy = h("button", {class:"btn mini", onclick: async () => {
      try { await navigator.clipboard.writeText(text); copy.textContent = "已复制"; }
      catch { copy.textContent = "复制失败"; }
    }}, "复制" + label);
    return h("section", {class:"post-field" + (label === "简介" ? " post-description" : "")},
      h("div", {class:"post-field-head"}, h("strong", {}, label),
        label === "标题" ? h("small", {}, Array.from(title).length + " / 80 字符" + (Array.from(title).length > 80 ? " · 超长待精简" : "")) : null, copy),
      label === "完整投稿 JSON" ? h("pre", {class:"json-view"}, text) : h("p", {}, text));
  });
  return h("div", {class:"post-info bili-post-info"}, ...rows);
}

function productDuration(seconds) {
  if (seconds == null) return "—";
  const rounded = Math.round(seconds);
  return `${Math.floor(rounded / 60)}分${rounded % 60}秒`;
}

function productSingleRunTimings(data) {
  // Historical attempts remain in the manifest; show each production stage once.
  const aliases = {bilibili_revision2_render:"bilibili-4k60_render_encode"};
  const stages = [
    ["source_decode_deinterlace_lossless", "原片解码、去隔行、无损保存"],
    ["scene_boundary_detection", "切镜边界检测"],
    ["interpolate50to60_and_lossless_master", "一次插帧与共享母版写入"],
    ["verify_master", "共享母版校验"],
    ["prepare_titles_subtitles_masks", "标题、字幕与渐变素材"],
    ["douyin-1080p60_render_encode", "抖音1080p60合成编码"],
    ["bilibili-4k60_render_encode", "B站4K60合成编码"],
    ["verify_both_outputs_decode_and_audio_clock", "双版成品校验"]
  ];
  const latest = new Map();
  for (const row of data.timings || []) {
    if (Number.isFinite(row.seconds) && row.seconds >= 0) latest.set(aliases[row.stage] || row.stage, row);
  }
  return stages.filter(([stage]) => latest.has(stage)).map(([stage, label]) => ({...latest.get(stage), stage, label}));
}

function productTimingLayout(timings) {
  let elapsed = 0;
  const groups = new Map();
  const rows = timings.map(row => {
    let start = elapsed;
    if (row.parallel_group) {
      if (!groups.has(row.parallel_group)) {
        const members = timings.filter(other => other.parallel_group === row.parallel_group);
        groups.set(row.parallel_group, elapsed);
        elapsed += Math.max(...members.map(other => Math.max(0, other.group_offset_seconds || 0) + other.seconds));
      }
      start = groups.get(row.parallel_group) + Math.max(0, row.group_offset_seconds || 0);
    } else elapsed += row.seconds;
    return {...row, start_seconds:start};
  });
  return {rows, total:elapsed};
}

function productTimeline(data) {
  const timings = productSingleRunTimings(data);
  if (!timings.length) return null;
  const layout = productTimingLayout(timings);
  const total = layout.total;
  const axisMax = Math.max(300, Math.ceil(total / 300) * 300);
  const ticks = Array.from({length:axisMax / 300 + 1}, (_, i) => i * 300);
  const rows = layout.rows.map(row => {
    const start = row.start_seconds;
    const kind = row.stage.includes("interpolate") ? "interpolation"
      : row.stage.includes("douyin") ? "douyin"
      : row.stage.includes("bilibili") ? "bilibili"
      : row.stage.includes("verify") ? "validation" : "preparation";
    const label = row.label || row.stage;
    return h("div", {class:"production-timeline-row"},
      h("span", {class:"timeline-stage-name", title:label}, label),
      h("div", {class:"production-timeline-track", style:`--tick-step:${300 / axisMax * 100}%`, title:`${label} · ${productDuration(row.seconds)}`},
        h("div", {class:`production-timeline-bar ${kind}${row.seconds / axisMax < .075 ? " compact" + ((start + row.seconds) / axisMax > .93 ? " compact-end" : "") : ""}`,
          style:`left:${start / axisMax * 100}%;width:${row.seconds / axisMax * 100}%`},
          h("span", {class:"timeline-bar-duration"}, productDuration(row.seconds)))));
  });
  return h("section", {class:"production-timeline"},
    h("strong", {}, "单次制作阶段耗时"),
    h("p", {class:"hint"}, `单次流程参考耗时 ${productDuration(total)}`),
    h("p", {class:"hint"}, "按当前版本各有效阶段实测重组，每阶段只计一次，并行阶段重叠计时；不含迁移、试做、历史重做及等待调试。"),
    h("div", {class:"production-timeline-scroll"},
      h("div", {class:"production-timeline-chart"},
        h("div", {class:"production-timeline-scale"}, h("span", {}, "阶段"),
          h("div", {}, ...ticks.map(seconds => h("span", {}, `${seconds / 60}min`)))),
        ...rows)), data.engine ? h("p", {class:"hint"}, data.engine) : null);
}

function productsPlaceholder(c, song) {
  const data = song.products || {};
  const renderProduct = (platform, title) => {
    const item = (data.items || []).find(item => item.platform === platform);
    const content = h("section", {class:platform === "bilibili" ? "product-output product-horizontal" : "product-output product-portrait",
      "aria-label":title}, h("strong", {}, title));
    if (!item) {
      content.append(h("p", {class:"empty"}, data.status === "running" ? (data.stage || "正在制作") : "暂无成品"));
      return content;
    }
    const video = h("video", {src:item.url, controls:true, playsinline:true, preload:"metadata", class:"product-video", "aria-label":title});
    state.cleanup.push(() => { video.pause(); video.removeAttribute("src"); video.load(); });
    if (item.previous) content.append(h("p", {class:"hint"}, "正在更新成品，当前播放上一版"));
    content.append(video,
      h("p", {}, `${item.width}×${item.height} · ${item.fps}fps · ${(item.bytes/1024/1024).toFixed(1)} MiB`),
      h("p", {}, `合成编码 ${productDuration(item.render_seconds)}`),
      revealFinal(c, song, "products/" + item.file),
      h("details", {}, h("summary", {}, "文件路径"), h("p", {}, item.path)));
    return content;
  };
  const horizontal = renderProduct("bilibili", "横屏B站版");
  const portrait = renderProduct("douyin", "竖屏抖音版");
  const videos = [...horizontal.querySelectorAll("video"), ...portrait.querySelectorAll("video")];
  videos.forEach(video => video.addEventListener("play", () => videos.forEach(other => { if (other !== video) other.pause(); })));
  return h("div", {}, h("div", {class:"top stacked-review product-layout"}, horizontal, portrait),
    data.created_local ? h("p", {class:"product-created"}, "制作时间 " + data.created_local) : null,
    productTimeline(data));
}

function postingPane(song) {
  const tabs = h("div", {class:"song-tabs post-tabs", role:"tablist", "aria-label":"投稿平台"});
  const panels = [
    h("section", {role:"tabpanel", "aria-label":"抖音投稿"}, douyinPane(song)),
    h("section", {role:"tabpanel", "aria-label":"B站投稿"}, postPane(song))
  ];
  function select(index) {
    panels.forEach((panel, i) => {
      panel.hidden = i !== index;
      tabs.children[i].setAttribute("aria-selected", String(i === index));
    });
  }
  ["抖音投稿", "B站投稿"].forEach((label, index) =>
    tabs.append(h("button", {role:"tab", class:"platform-logo-tab", title:label, "aria-label":label, onclick:() => select(index)},
      h("img", {src:index === 0 ? "icons/douyin.svg" : "icons/bilibili.svg", alt:"", "aria-hidden":"true"}))));
  select(0);
  return h("div", {class:"posting-platforms"}, tabs, ...panels);
}

// ---------------------------------------------------------------- 总览

// 整场时间轴：每首一块，颜色 = 审核状态；点一块跳到那首。now()：当前播放到整场的哪一秒（单曲页用）
function timeline(c, cur, video, now) {
  const D = c.info.duration || 1;
  const el = h("div", { class: "timeline", title: "整场时间轴（点一块跳到那首）" });
  for (const s of c.songs) {
    if (s.start == null) continue;
    el.append(h("div", {
      class: `blk ${s.review}${cur && s.name === cur.name ? " cur" : ""}`, title: `${s.idx} ${s.title}  ${hms(s.start)}`,
      style: `left:${(s.start / D) * 100}%;width:${Math.max(0.2, ((s.end - s.start) / D) * 100)}%`,
    }));
  }
  const head = h("div", { class: "head", style: "display:none" });
  el.append(head);
  el.addEventListener("click", (e) => {
    const t = ((e.clientX - el.getBoundingClientRect().left) / el.clientWidth) * D;
    const hit = c.songs.find((s) => s.start != null && t >= s.start && t <= s.end);
    if (hit && (!cur || hit.name !== cur.name)) location.hash = `#/${c.slug}/${hit.name}`;
  });
  if (video && now) {
    video.addEventListener("timeupdate", () => { head.style.display = ""; head.style.left = `${(now() / D) * 100}%`; });
  }
  return el;
}

// ---------------------------------------------------------------- 单曲审核
// 布局：上面 左 视频（单曲预览 + 外挂字幕 + 边界微调）/ 右 逐句歌词和翻译；下面 左 候选封面 / 右 投稿信息

function formatLabel(format) {
  return h("small", {class: "video-format"}, format || "规格未知");
}

function revealFinal(c, song, file) {
  return h("button", {type: "button", class: "btn mini reveal-final", onclick: async () => {
    try { await api(`/api/concerts/${c.slug}/songs/${song.name}/reveal_final?file=${encodeURIComponent(file)}`, {}); }
    catch (error) { toast(error.message, false); }
  }}, "打开目录");
}

function douyinPane(song) {
  const post = song.douyin_submission || {};
  const cover = song.douyin_cover;
  function field(label, value, fallback, limit) {
    const copy = value && h("button", {class:"btn mini", onclick: async () => {
      try { await navigator.clipboard.writeText(value); copy.textContent = "已复制"; }
      catch { copy.textContent = "复制失败"; }
    }}, "复制" + label);
    return h("div", {}, h("small", {}, limit ? label + " · " + (value || "").length + " / " + limit + " 字符" : label), h("p", {}, value || fallback), copy);
  }
  return h("aside", {class:"douyin-pane", "aria-label":"抖音投稿信息"},
    h("strong", {}, "抖音投稿信息"),
    field("短标题", post.title, "待补投稿资料", 30),
    field("作品描述", post.description, "待补投稿资料", 1000),
    field("竖封面路径", cover?.path, "待选竖屏封面"),
    field("4:3 横封面路径", cover?.wide_path, "待设计"),
    field("自主声明", post.declaration, "待补投稿资料"),
    h("div", {}, h("small", {}, "发布设置参考"), h("p", {}, post.publish_settings || "待补投稿资料")));
}

function portraitReleaseControls(c, s) {
  const review = s.portrait_review;
  if (c.has_cover_pool && !review.selected) {
    return h("div", {class:"pool-selector-hint"}, h("a", {href:"#/" + c.slug + "/~covers"}, "到封面池选帧"));
  }
  const choices = h("div", {class: "portrait-cover-choices"});
  const timing = review.first == null ? "尚无有效歌词" : "首句前保留 " + (review.released?.lead ?? 0.5) + " 秒 · 首句 " + fmt(review.first)
    + " · 成品起点 " + fmt(review.released?.start ?? Math.max(0, review.first - 0.5));
  const dialog = h("dialog", {class: "portrait-cover-dialog", "aria-label": "竖屏封面预览",
    onclick: event => { if (event.target === dialog) dialog.close(); }});
  function preview(url, label) {
    dialog.setAttribute("aria-label", label);
    dialog.replaceChildren(h("img", {src: url, alt: label}),
      h("button", {class: "close-preview", "aria-label": "关闭预览", onclick: () => dialog.close()}, "×"));
    dialog.showModal();
  }
  for (const cover of review.covers.filter(row => !c.has_cover_pool || row.file === review.selected)) {
    const pick = h("button", {type:"button", class:"cover-check", "aria-pressed":String(review.selected === cover.file),
      "aria-label":"选用封面 " + (cover.pool_frame ? "整场 " : "") + fmt(cover.time), title:"选用这张封面", onclick: async () => {
        if (choices.dataset.busy) return;
        choices.dataset.busy = "1";
        try { const result = await api(`/api/concerts/${c.slug}/songs/${s.name}/vertical_cover`, {cover: cover.file}); s.douyin_cover = result.douyin_cover; }
        catch (e) { toast(e.message, false); return; }
        finally { delete choices.dataset.busy; }
        review.selected = cover.file;
        const summary = c.songs.find(item => item.name === s.name);
        if (summary) {
          summary.portrait_cover_selected = true;
          summary.post_ready = Boolean(s.douyin_caption && s.douyin_cover);
        }
        if (state.song === s) {
          document.querySelectorAll(".douyin-pane").forEach(pane => pane.replaceWith(douyinPane(s)));
          if (tabs.children[1].getAttribute("aria-selected") === "true") select(1);
          toast("已更新竖封面和 4:3 横封面");
        }
        if (state.concert === c) renderSidebar(parseRoute());
        for (const option of choices.querySelectorAll(".cover-check")) {
          option.setAttribute("aria-pressed", String(option === pick));
        }
      }}, "✓");
    const button = h("button", {type:"button", class:"cover-preview", title:"放大预览",
      onclick: () => preview(cover.url, "竖屏封面 " + (cover.pool_frame ? "整场 " : "") + fmt(cover.time))}, h("img", {src: cover.url, alt: "竖屏封面 " + (cover.pool_frame ? "整场 " : "") + fmt(cover.time), loading: "lazy"}),
      h("span", {class:"cover-time"}, (cover.pool_frame ? "整场 " : "") + fmt(cover.time)));
    choices.append(h("div", {class:"cover-choice"}, button, c.has_cover_pool ? null : pick));
  }
  const tabs = h("div", {class:"song-tabs", role:"tablist", "aria-label":"封面比例"});
  const panel = h("div", {role:"tabpanel"});
  const labels = ["竖封面3:4", "横封面4:3"];
  function select(index) {
    Array.from(tabs.children).forEach((button, i) => button.setAttribute("aria-selected", String(i === index)));
    panel.setAttribute("aria-label", labels[index]);
    if (index === 0) {
      panel.replaceChildren(review.covers.length ? choices : h("p", {}, "暂无竖屏封面候选"));
    } else if (s.douyin_cover?.wide_path) {
      const name = s.douyin_cover.wide_path.split("/").pop();
      const url = "/media/" + [c.slug, "songs", s.name, "vertical", name].map(encodeURIComponent).join("/");
      panel.replaceChildren(h("button", {class:"wide-cover-preview", type:"button", title:"放大预览",
        onclick: () => preview(url, labels[index])}, h("img", {src:url, alt:s.title + " 4:3 横封面"})));
    } else {
      panel.replaceChildren(h("p", {}, "暂无配套的 4:3 横封面"));
    }
  }
  labels.forEach((label, index) => tabs.append(h("button", {type:"button", role:"tab", onclick: () => select(index)}, label)));
  select(0);
  return h("section", {class:"portrait-release-controls", "aria-label":"竖屏作品封面"}, tabs, panel, dialog,
    review.revision ? h("div", {class:"toolbar"}, h("small", {}, timing)) : null,
    c.has_cover_pool ? h("a", {href:"#/" + c.slug + "/~covers"}, "到整场封面池标记、分配封面") : null);
}

function coverDesignPane(c, s, bili) {
  const raw = h("div", {class:"cover-design-gallery"});
  const ai = h("div", {class:"cover-design-gallery ai-cover-gallery"});
  const variants = Array.from({length:3}, ()=>h("div", {class:"cover-design-variants"}));
  const aiSource = h("aside", {class:"ai-cover-source"});
  const aiStatus = h("p", {class:"hint"});
  const tabs = h("div", {class:"song-tabs", role:"tablist", "aria-label":"封面设计"});
  const panels = [
    h("section", {}, c.has_cover_pool ? h("a", {class:"btn mini", href:"#/"+c.slug+"/~covers"}, "打开整场封面池") : null, raw),
    h("section", {}, h("div", {class:"ai-cover-workspace"}, aiSource, h("div", {class:"ai-cover-results"}, h("h4", {}, "生成结果"), aiStatus, ai))), h("section", {}, variants[0], bili),
    h("section", {}, h("p", {class:"hint"}, "AI 母图直接加字 · 3:4 / 4:3"), variants[2]),
    h("section", {}, variants[1], portraitReleaseControls(c, s))
  ];
  const labels = ["候选帧", "AI 生成", "B站封面", "抖音纯 AI 生成", "抖音旧模板生成"];
  let loaded = false;
  let loading = false;
  async function loadImages() {
    if (loaded || loading) return;
    loading = true;
    raw.replaceChildren(h("p", {class:"hint"}, "正在加载候选帧…"));
    ai.replaceChildren(h("p", {class:"hint"}, "正在加载 AI 生成图…"));
    try {
      const data = await api("/api/concerts/"+c.slug+"/songs/"+s.name+"/cover_design");
      function gallery(target, rows, empty, isFrame) {
        target.replaceChildren(...(rows.length ? rows.map(row =>
          h("button", {class:"cover-design-image", type:"button", title:"点击放大", onclick:()=>lightbox(row.url)},
            row.ratio ? h("span", {class:"cover-ratio-label"}, (row.ratio === "3x4" ? "竖版 " : "横版 ") + row.ratio.replace("x", ":") + (row.dimensions ? " · " + row.dimensions.join(" × ") : "")) : null,
            h("img", {src:row.status === "source_offline" ? undefined : row.url, alt:isFrame ? "候选帧 "+hms(row.t) : row.file, loading:"lazy"}),
            h("span", {}, isFrame ? (SHOT[row.kind] || "画面")+" · 原片 "+hms(row.t)+" · "+(row.origins || []).join(" / ")+(row.status === "source_offline" ? " · 原片离线" : "") : (row.label || row.file).replace(/\.[^.]+$/, ""))))
          : [h("p", {class:"hint"}, empty)]));
      }
      gallery(raw, data.frames, "暂无原片候选帧", true);
      gallery(ai, data.generated, "暂无 AI 生成图", false);
      aiStatus.textContent = (data.failed_candidates || []).map(row=>row.label+"："+row.reason).join("；");
      aiStatus.hidden = !aiStatus.textContent;
      const references = [...new Map(data.generated.filter(row=>row.reference_url).map(row=>[row.reference_url,row])).values()];
      if (references.length) aiSource.replaceChildren(
        h("h4", {}, "已选参考帧"),
        ...references.map(reference=>h("button", {class:"cover-design-image", type:"button", onclick:()=>lightbox(reference.reference_url)},
          h("img", {src:reference.reference_url, alt:"已选原片参考帧"}),
          h("span", {}, (references.length > 1 ? reference.label+" · " : "原片 · ")+hms(reference.source_time)))),
        h("p", {class:"hint"}, "Seedream · 点击图片放大"));
      else aiSource.replaceChildren(h("h4", {}, "参考帧"), h("p", {class:"hint"}, "尚无已选参考帧"));
      ["bili", "douyin", "douyin-ai"].forEach((platform, index)=>{
        const rows = (data.variants || []).filter(row=>row.platform === platform);
        variants[index].replaceChildren(...[...new Set(rows.map(row=>row.master))].map(master=>{
          const grid = h("div", {class:"cover-design-gallery"});
          gallery(grid, rows.filter(row=>row.master === master), "", false);
          const name = data.generated.find(row=>row.file === master)?.label || "AI 母图试排";
          const note = data.generated.find(row=>row.file === master)?.quality_note;
          return h("section", {class:"cover-variant-group"}, h("h4", {}, name), note ? h("p", {class:"hint"}, note) : null, grid);
        }));
        if (!rows.length) variants[index].append(h("p", {class:"hint"}, "暂无预览"));
      });
      for (const panel of variants) panel.querySelectorAll("img").forEach(img=>{img.style.aspectRatio="auto";});
      loaded = true;
    } catch (error) {
      for (const panel of [raw, ai]) panel.replaceChildren(h("p", {class:"hint"}, "加载失败："+error.message),
        h("button", {class:"btn mini", onclick:loadImages}, "重试"));
    } finally { loading = false; }
  }
  function select(index) {
    panels.forEach((panel, i) => {
      panel.hidden = i !== index;
      tabs.children[i].setAttribute("aria-selected", String(i === index));
      tabs.children[i].tabIndex = i === index ? 0 : -1;
    });
    loadImages();
  }
  labels.forEach((label, i) => {
    const id = "cover-design-"+i;
    panels[i].id = id;
    panels[i].setAttribute("role", "tabpanel");
    panels[i].setAttribute("aria-labelledby", id+"-tab");
    tabs.append(h("button", {id:id+"-tab", type:"button", role:"tab", "aria-controls":id,
      onclick:()=>select(i), onkeydown:event=>{
        if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
        event.preventDefault();
        const next = event.key === "Home" ? 0 : event.key === "End" ? 3 : (i + (event.key === "ArrowRight" ? 1 : 3)) % 4;
        select(next); tabs.children[next].focus();
      }}, label));
  });
  select(0);
  return h("div", {class:"cover-design"}, tabs, ...panels);
}

async function viewSong(route) {
  const c = state.concert;
  const s = await api(`/api/concerts/${c.slug}/songs/${route.name}`);
  if (parseRoute().slug !== route.slug || parseRoute().name !== route.name) return;
  state.song = s;
  document.title = "演唱会";
  const artist = s.artist || c.info.artist;
  const groupedSingle = c.slug.startsWith("artist_") || c.slug === "singles" || c.slug.startsWith("singles_");
  const source = groupedSingle ? s.notes : c.info.title;
  const version = /^official music video$/i.test(source || "") ? "官方 MV" : source;
  const context = [artist && !version?.toLowerCase().startsWith(artist.toLowerCase()) ? artist : null, version]
    .filter(Boolean).join(" · ");
  const head = h("div", { class: "card-head" },
    h("div", {class:"source-specs", "aria-label":"原片规格"},
      ...(s.source_format?.files || [s.source_format || {}]).map(file =>
        h("div", {class:"source-file-specs"},
          ...[["filename", "原始文件"], ["resolution", "原片分辨率"], ["fps", "原片帧率"], ["audio", "原片音频格式"]].map(([key, label]) => {
            const value = (file[key] || "未知") + (key === "filename" && file.size_gb != null ? ` · ${file.size_gb} GB` : "");
            return h("span", {class:"source-spec" + (key === "filename" ? " source-filename" : ""), title:label + " " + value}, value);
          })))),
    h("div", { class: "card-title" }, s.title, context ? h("small", {}, context) : null),
    h("div", { class: "spacer" }),
    ...(s.genius_urls || []).map((u, i) => h("a", { href: u, target: "_blank", rel: "noopener" }, s.genius_urls.length > 1 ? `歌词 ${i + 1}` : "Genius 歌词")));
  // 布局：上面 左 视频 / 右 歌词和翻译（跟着播放滚动）；中间 成品 + B 站投稿 JSON；下面 候选封面（没有成品时 JSON + 封面一行）
  const player = await videoPane(c, s, route.at);
  const covers = coverPane(s);
  // 歌词栏：逐句表格；视频上的字幕用诗意版（和成品一致），这首没有诗意版时用直译版
  const x = s.exp;
  if (x && player.setAss) await player.setAss(x.ass_poetic || x.ass_literal || x.ass);
  // 注释入口放在歌名旁边：显示这首有几条注释，点开是列表
  const nNotes = x ? x.rows.filter((r) => r.note && !r.removed).length : 0;
  if (nNotes) head.querySelector(".card-title").append(
    h("a", { class: "notes-link", href: "javascript:void 0", onclick: () => { selectTab(0); watermarks.querySelector(".note-block").scrollIntoView({block:"nearest"}); } }, `注释 ${nNotes}`));
  const portrait = s.vertical_preview;
  const players = [];
  let portraitPane, livePortrait;
  if (s.browser_portrait) {
    const live = livePortrait = browserPortrait({...s.browser_portrait, watermark:s.watermark});
    player.addPeer?.(live.video);
    players.push({video: live.video, offset: -s.browser_portrait.start, delay: () => 0,
      start: s.browser_portrait.start});
    state.cleanup.push(live.destroy);
    portraitPane = live.el;
  } else if (portrait) {
    const portraitVideo = portrait ? h("video", {controls: true, playsinline: true, preload: "metadata",
      src: portrait.url, "aria-label": s.title + "竖屏预览"}) : null;
    if (portraitVideo) {
      player.addPeer?.(portraitVideo);
      players.push({video: portraitVideo, offset: -portrait.start, delay: () => 0,
        start: portrait.start, end: portrait.start + portrait.duration});
      state.cleanup.push(() => { portraitVideo.pause(); portraitVideo.removeAttribute("src"); portraitVideo.load(); });
    }
    portraitPane = h("div", {class: "pane portrait-player"},
      portraitVideo, portraitVideo && formatLabel(portrait.format),
      s.source_note ? h("small", {}, s.source_note) : null);
  }
  const originalPanes = [];
  const originals = s.originals || (s.source_review && s.preview
    ? [{key: "ts", label: "TS 原片片段", url: s.preview, format: s.preview_format, start: 0}] : []);
  for (const source of originals) {
    const shared = livePortrait && source.url === s.browser_portrait.url;
    const video = shared ? livePortrait.video : source.url ? h("video", {src: source.url, controls: true, playsinline: true,
      preload: "metadata", "aria-label": s.title + " " + source.label}) : null;
    if (shared) {
      video.classList.remove("browser-portrait-source");
      video.classList.add("shared-review-source");
      video.removeAttribute("aria-hidden");
      video.setAttribute("aria-label", s.title + " 横竖同步预览");
      video.controls = true;
    }
    if (video && !shared) {
      player.addPeer?.(video);
      // The old cut has a different clock: do not seek it with TS subtitle times.
      if (source.key === "ts") players.push({video, offset: -source.start, delay: () => 0, start: source.start});
      state.cleanup.push(() => { video.pause(); video.removeAttribute("src"); video.load(); });
    }
    const marks = (s.source_differences || []).map(difference => {
      const [start, end] = difference[source.key];
      return h("div", {class: "source-difference"},
        h("button", {class: "btn mini", disabled: !video, onclick: () => {
          video.currentTime = Math.max(0, start - source.start);
          video.scrollIntoView({block: "nearest"});
        }}, `${fmt(start)}–${fmt(end)}`), h("small", {}, difference.label));
    });
    let originalStage = video;
    if (shared && x) {
      if (s.browser_portrait.horizontal_caption_band) {
        const band = horizontalCaptionBand(video, s.browser_portrait);
        originalStage = band.el;
        state.cleanup.push(band.destroy);
      } else {
        originalStage = h("div", {class:"stage"},video);
        const ass = parseAss(await (await fetch(x.ass_poetic || x.ass_literal || x.ass, {cache:"no-store"})).text());
        new SubOverlay(originalStage, video, ass, -source.start);
      }
    }
    originalPanes.push(h("div", {class: "pane original-player"},
      originalStage || h("div", {class: "empty"}, "原片播放文件准备中，稍后刷新"),
      source.start ? h("small", {}, `此片段从单曲 ${fmt(source.start)} 开始`) : null,
      marks.length ? h("small", {}, "差异核对窗口 · 单曲片段时间（点击跳转）") : null, marks));
  }
  let finishedVideos;
  const comparisons = s.review_mode === "browser" ? [] : [
    [s.portrait_nonts60, "非 TS 成品插帧 · 1080 × 1920 · 60 fps", s.portrait_review?.released?.start ?? 0, "vertical/compare-nonts-1080p60.mp4", s.portrait_nonts60_format],
    [s.portrait_ts60, "TS 原片 · 1080 × 1920 · 60 fps", s.portrait_review?.released?.start ?? 0, "vertical/compare-ts-1080p60.mp4", s.portrait_ts60_format],
    [s.portrait_60, "竖屏对比 · 720 × 1280 · 60 fps 插帧版", 0, "vertical/compare-720p60.mp4", s.portrait_60_format],
  ];
  for (const [src, title, start, file, format] of comparisons) {
    if (!src) continue;
    const video = h("video", {src, controls: true, playsinline: true, preload: "none",
      class: "final-video portrait-comparison", "aria-label": title});
    player.addPeer?.(video);
    players.push({video, offset: -start, start, delay: () => 0});
    state.cleanup.push(() => { video.pause(); video.removeAttribute("src"); video.load(); });
    finishedVideos ??= h("div", {class: "portrait-comparisons"});
    finishedVideos.append(h("div", {class: "final-wrap portrait-final"},
      h("div", {class: "final-title"}, title), video, formatLabel(format), revealFinal(c, s, file)));
  }
  const released = s.portrait_review?.released;
  let releasePane;
  if (released) {
    const video = h("video", {src: released.url, controls: true, playsinline: true, preload: "none",
      poster: s.portrait_review.covers.find(c => c.file === released.cover)?.url,
      class: "final-video portrait-comparison", "aria-label": "审核通过的竖屏成品"});
    player.addPeer?.(video);
    players.push({video, offset: -released.start, delay: () => 0, start: released.start,
      end: s.slice ? s.slice[1] - s.slice[0] : undefined});
    state.cleanup.push(() => { video.pause(); video.removeAttribute("src"); video.load(); });
    releasePane = h("div", {class: "pane portrait-player"}, video, formatLabel(released.format), released.previous ? h("small", {}, "上一版成品") : null, revealFinal(c, s, "vertical/" + released.file));
    if (s.originals) {
      finishedVideos ??= h("div", {class:"portrait-comparisons"});
      finishedVideos.append(releasePane);
      releasePane = null;
    }
  }
  const lyricsPane = targets => h("div", {class: "pane lyrics-pane"},
    x ? expTable(x, targets) : h("div", {class: "empty"}, "还没有字幕（refine 阶段）"));
  const reviewLyrics = lyricsPane(players);
  const reviewPortrait = h("div", {class:"review-right"},
    portraitPane || h("div", {class:"empty"}, "暂无竖屏预览"), releasePane);
  const watermarks = h("div", {class:"review-notes preview-watermarks"}, watermarkPane(s), notesPane(s));
  const horizontalGroup = h("div", {class:"review-horizontal-group"},
    watermarks, h("div", {class:"review-horizontal-videos"}, ...originalPanes));
  const reviewLeft = h("div", {class:"review-left"}, horizontalGroup, reviewLyrics);
  const reviewPosting = h("div", {class:"review-posting"}, postingPane(s));
  const reviewLayout = originalPanes.length
    ? h("div", {class:"top stacked-review"}, reviewLeft, reviewPortrait, reviewPosting)
    : h("div", {class:releasePane ? "top vertical-review with-release" : "top vertical-review"},
        portraitPane || h("div", {class:"empty"}, "暂无竖屏预览"), releasePane, reviewLyrics, reviewPosting, watermarks);
  const sections = [["字幕预览", h("section", {}, reviewLayout, finishedVideos)]];
  sections.push(["产物", h("section", {}, productsPlaceholder(c, s))],
    ["封面设计", h("section", {}, coverDesignPane(c, s, covers.el))]);
  const panels = sections.map(([, panel]) => panel);
  const tabs = h("div", {class: "song-tabs", role: "tablist", "aria-label": "单曲审核"});
  function selectTab(index) {
    state.activeReviewVideo = index === 0 ? players[0]?.video : null;
    panels.forEach((panel, i) => {
      panel.hidden = i !== index;
      panel.setAttribute("role", "tabpanel");
      tabs.children[i].setAttribute("aria-selected", String(i === index));
      if (panel.hidden) panel.querySelectorAll("video").forEach(video => video.pause());
    });
  }
  sections.forEach(([label], i) =>
    tabs.append(h("button", {role: "tab", onclick: () => selectTab(i)}, label)));
  if (parseRoute().slug !== route.slug || parseRoute().name !== route.name) return;
  selectTab(0);
  if (route.at != null && players[0]?.video) {
    players[0].video.currentTime = Math.max(0, players[0].offset + route.at + players[0].delay());
  }
  const headerTools = h("div", {class:"review-header-tools"}, tabs, head.querySelector(".source-specs"));
  headerTools.append(...head.childNodes);
  head.append(headerTools);
  const card = h("div", {class: "card"}, head, ...panels);
  if (parseRoute().slug !== route.slug || parseRoute().name !== route.name) return;
  $("#view").replaceChildren(card);
  if (originalPanes.length) {
    const observer = new ResizeObserver(() => {
      const height = reviewPortrait.getBoundingClientRect().height;
      if (height > 0) {
        reviewLeft.style.height = height + "px";
        reviewPosting.style.maxHeight = height + "px";
        watermarks.style.maxHeight = originalPanes[0].getBoundingClientRect().height + "px";
      }
    });
    observer.observe(reviewPortrait);
    state.cleanup.push(() => observer.disconnect());
  }

}

function notesPane(song) {
  const notes = (song.exp?.rows || []).filter(row => row.note && !row.removed && !row.watermark);
  return h("section", {class:"post-info review-notes notes-only"},
    h("section", {class:"note-block"}, h("h3", {}, "备注"),
      song.notes ? h("p", {}, song.notes) : null,
      ...notes.map(row => h("div", {}, h("strong", {}, `${fmt(row.start)} · ${row.text}`), h("p", {}, row.note))),
      !song.notes && !notes.length ? h("p", {}, "暂无备注") : null));
}

function watermarkPane(song) {
  const marks = song.watermark?.items || [];
  const pct = value => `${Math.round(value * 100)}%`;
  return h("section", {class:"watermark-block"}, h("h3", {}, "水印信息"),
    marks.length ? h("p", {}, `宽度 ${pct(song.watermark.width ?? .12)} · 不透明度 ${pct(song.watermark.opacity ?? .6)}`) : null,
    ...marks.map(mark => h("p", {}, `${fmt(mark.t)} – ${fmt(mark.t + mark.dur)}`,
      h("br"), `距左 ${pct(mark.x)} · 距顶 ${pct(mark.y)}`,
      h("br"), `淡入淡出各 ${mark.fade} 秒`)),
    !marks.length ? h("p", {}, "暂无水印记录") : null);
}

function lightbox(src) {
  const close = () => { box.remove(); window.removeEventListener("keydown", onKey, true); };
  const onKey = (e) => { if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); close(); } };
  const box = h("div", { class: "lightbox", onclick: (e) => { if (e.target === box) close(); } },
    h("img", { src }),
    h("button", { class: "lb-close", title: "关闭（Esc）", onclick: close }, "×"));
  window.addEventListener("keydown", onKey, true);
  document.body.append(box);
}

// 右下角短暂提示（几秒后自动消失）
function toast(msg, ok = true) {
  const el = h("div", { class: `toast${ok ? "" : " err"}` }, msg);
  document.body.append(el);
  setTimeout(() => el.remove(), 4000);
}

// 圆形半透明的向下箭头按钮（SVG 要用 innerHTML，h() 的 createElement 画不出 SVG）
function dlButton(attrs) {
  const el = h("span", attrs);
  el.innerHTML = '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2.4" '
    + 'stroke-linecap="round" stroke-linejoin="round"><path d="M12 4v12M6 11l6 6 6-6M5 20h14"/></svg>';
  return el;
}

function coverPane(s) {
  if (state.concert.has_cover_pool) {
    return { el: h("div", { class: "pane" }, h("div", { class: "section-label" }, "封面",
      h("span", { class: "cover-selection-status" + (s.cover_selected ? " selected" : "") },
        s.cover_selected ? "已选择" : "未选择"))) };
  }
  const entry = s.review_entry || {};
  const st = { chosen: s.selected_cover_id || entry.cover || null, ratio: "169" };
  const box = h("div", { class: "covers" });
  const selectionStatus = h("span", { class: "cover-selection-status", role: "status", "aria-live": "polite" });
  const draw = () => {
    const selected = Boolean(st.chosen || s.cover_selected);
    selectionStatus.textContent = selected ? "已选完封面" : "尚未选择封面";
    selectionStatus.classList.toggle("selected", selected);
    const summary = state.concert?.songs.find((item) => item.name === s.name);
    if (summary && summary.cover_selected !== selected) {
      summary.cover_selected = selected;
      renderSidebar(parseRoute());
    }
    box.className = `covers${st.ratio === "43" ? " r43" : ""}`;
    const card = (x) => {
      const src = st.ratio === "43" && x.file_4x3 ? x.file_4x3 : x.file;
      const top = x.rank != null && x.rank <= 3;
      return h("button", {
        class: `cover${x.id === st.chosen ? " on" : ""}${top ? " best" : ""}`,
        title: `${x.id}${x.score != null ? ` · 分数 ${x.score.toFixed(2)}` : ""}${x.why ? ` · ${x.why}` : ""}（双击看大图）`,
        onclick: async () => {
          if (st.saving) return;
          st.saving = true;
          try {
            await api(`/api/concerts/${parseRoute().slug}/songs/${s.name}/review`, { cover: x.id });
            st.chosen = x.id; s.cover_selected = true; draw();
          } catch (err) { toast(`封面保存失败：${err.message || err}`, false); }
          finally { st.saving = false; }
        },
        ondblclick: () => lightbox(src),
      }, h("img", { src, loading: "lazy" }),
      top ? h("span", { class: "rk" }, `#${x.rank}`) : null,
      x.t != null ? h("span", { class: "ct" }, `${SHOT[x.id.split("_")[0]] || ""} ${hms(x.t)}`.trim()) : null,
      x.id === st.chosen ? h("span", { class: "pick" }, "已选") : null,
      top && x.why ? h("span", { class: "why" }, x.why) : null,
      // 下载：16:9 + 4:3 两张 PNG 存到这首歌的 post/ 目录（按钮在 button 里面，不能再嵌 button）
      dlButton({
        class: "dl", role: "button", title: "下载到 post/（16:9 + 4:3 PNG）",
        ondblclick: (e) => e.stopPropagation(),
        onclick: async (e) => {
          e.stopPropagation();
          const b = e.currentTarget;
          if (b.classList.contains("busy")) return;
          b.classList.add("busy");
          try {
            const r = await api(`/api/concerts/${parseRoute().slug}/songs/${s.name}/cover_download`, { id: x.id });
            st.chosen = x.id; draw();
            toast(`已保存：${r.saved.join("、")}`);
          } catch (err) {
            b.classList.remove("busy");
            toast(`下载失败：${err.message || err}`, false);
          }
        },
      }));
    };
    const groups = [];
    const group = (label, rows) => { if (rows.length) groups.push([label, rows]); };
    const original = s.covers.filter(x => !x.reconstructed);
    const recommended = original.filter(x => x.rank != null && x.rank <= 3);
    group("算法推荐 Top3", recommended);
    const remaining = original.filter(x => !recommended.includes(x));
    for (const kind of [...new Set(remaining.map(x => x.id.split("_")[0]))]) {
      group(SHOT[kind] || "其他候选", remaining.filter(x => x.id.startsWith(kind + "_")));
    }
    group("重构版本", s.covers.filter(x => x.reconstructed));
    box.replaceChildren(...(s.covers.length ? groups.flatMap(([label, xs]) =>
      xs.length ? [label ? h("div", { class: "cover-group" }, label) : null, ...xs.map(card)].filter(Boolean) : [])
      : [h("div", { class: "placeholder" }, "还没有候选封面（package 阶段）")]));
  };
  draw();
  const sw = h("div", { class: "seg", role:"tablist", "aria-label":"B站封面比例" }, ...[["43", "首页推荐封面（4:3）"], ["169", "个人空间封面（16:9）"]].map(([k, l]) =>
    h("button", { class: k === st.ratio ? "on" : null, role:"tab", "aria-selected":String(k === st.ratio), "data-k": k, onclick: () => {
      st.ratio = k; draw();
      sw.querySelectorAll("button").forEach((b) => { b.classList.toggle("on", b.dataset.k === k); b.setAttribute("aria-selected", String(b.dataset.k === k)); });
    } }, l)));
  return { el: h("div", { class: "pane" }, h("div", { class: "section-label" }, "候选封面（点选一张）", selectionStatus, sw), box), state: st };
}

async function videoPane(c, s, at) {
  if (!s.preview || !s.preview_span) {
    const el = h("div", { class: "pane" }, h("div", { class: "placeholder" }, "还没有字幕预览版（preview 阶段）"));
    return { el, video: null, offset: 0, setAss: null, delay: () => 0 };
  }
  // 预览视频 = 整场 [clip0, clip1]（歌的前后各多留 10s）；整场时间 = clip0 + 播放时间
  const [clip0, clip1] = s.preview_span;
  const now = () => clip0 + video.currentTime;
  const seekAbs = (t) => { video.currentTime = Math.max(0, Math.min(clip1 - clip0, t - clip0)); };
  const subOffset = (s.slice ? s.slice[0] : s.start) - clip0;   // 字幕时间 0 = 切音频时的片段起点
  const edges = { start: s.start, end: s.end };
  const video = h("video", { src: s.preview, controls: true, preload: "none", playsinline: true,
    controlslist: "nofullscreen", disablepictureinpicture: true });
  // 左上角（logo_corner = right 时右上角）叠朝阳 Adele 的 logo（只是预览：和成品 render.py 一样的比例和位置——宽度约为画面的 10.25%、离画面内容左上角 15/3840；
  // 宽银幕片源上下有黑边，放在内容区域 s.box 里，不放在黑边上；不改视频文件，只是一张图片叠在播放器上）
  const stage = h("div", {class:"stage"}, video);
  // 歌曲中间随机出现的半透明水印（预览）：按 watermark.json 的时间、位置淡入淡出
  const wm = s.watermark && s.watermark.items && s.watermark.items.length ? s.watermark : null;
  if (wm) {
    const wmImg = h("img", { src: "adele-logo.png", class: "preview-wm", alt: "" });
    stage.append(wmImg);
    const frame = () => {
      const t = video.currentTime - subOffset;   // 歌曲内时间
      const it = wm.items.find((x) => t >= x.t && t < x.t + x.dur);
      if (!it) { wmImg.style.opacity = 0; return; }
      const a = Math.min(1, (t - it.t) / it.fade, (it.t + it.dur - t) / it.fade);
      const W = video.clientWidth, H = video.clientHeight;
      const ar = video.videoWidth && video.videoHeight ? video.videoWidth / video.videoHeight : 16 / 9;
      const cw = Math.min(W, H * ar), ch = cw / ar;
      Object.assign(wmImg.style, { left: `${(W - cw) / 2 + cw * it.x}px`, top: `${(H - ch) / 2 + ch * it.y}px`,
        width: `${cw * wm.width}px`, opacity: wm.opacity * Math.max(0, a) });
    };
    const loop = () => { frame(); if (!video.paused && stage.isConnected) requestAnimationFrame(loop); };
    video.addEventListener("play", loop);
    video.addEventListener("seeked", frame);
    video.addEventListener("timeupdate", frame);
  }
  video.addEventListener("loadedmetadata", () => seekAbs(at != null ? (s.slice ? s.slice[0] : s.start) + at : edges.start), { once: true });
  video.addEventListener("dblclick", () => toggleFullscreen(stage));
  state.video = video;

  let overlay = null;   // 字幕叠加层：setAss 第一次调用时建
  const subSwitch = h("div", { class: "seg" }, ...[["both", "双语"], ["off", "关"]].map(([m, label]) =>
    h("button", { "data-m": m, class: m === "both" ? "on" : null, onclick: () => {
      overlay && overlay.setMode(m);
      subSwitch.querySelectorAll("button").forEach((b) => b.classList.toggle("on", b.dataset.m === m));
    } }, label)));

  // 整体提前量：字幕文件里已经统一提前 BAKED_LEAD；切换时整体往后 / 往前挪，播放中立即生效，只影响预览
  const BAKED_LEAD = 0.2;
  const LEADS = [[0.8, "提前 0.8s"], [0, "不提前"]];
  let lead = LEADS[0][0];   // 默认提前 0.8s
  try { const v = parseFloat(localStorage.getItem("subLead")); if (LEADS.some(([x]) => x === v)) lead = v; } catch (e) { /* 无痕模式 */ }
  const applyLead = () => { if (overlay) { overlay.delay = BAKED_LEAD - lead; overlay.tick(); } };
  const leadSwitch = h("div", { class: "seg" }, ...LEADS.map(([v, label]) =>
    h("button", { "data-v": v, class: v === lead ? "on" : null, onclick: () => {
      lead = v;
      try { localStorage.setItem("subLead", String(v)); } catch (e) { /* 无痕模式 */ }
      applyLead();
      leadSwitch.querySelectorAll("button").forEach((b) => b.classList.toggle("on", Number(b.dataset.v) === v));
    } }, label)));
  applyLead();
  const el = h("div", { class: "pane" },
    // 字幕预览版：720p 预览视频 + 网页上叠字幕（只用来核字幕和边界，不是成品；成品 4K 在下面）
    h("div", { class: "pane-title" }, "字幕预览版", h("span", { class: "pane-sub" }, "字幕叠加预览，用来核字幕和起止点")),
    stage, formatLabel(s.preview_format),
    h("div", { class: "toolbar tight" },
      leadSwitch,
      h("div", { class: "spacer" }),
      subSwitch,
      h("button", { class: "btn", onclick: () => toggleFullscreen(stage) }, "⛶")));
  // 成品（4K60、字幕和水印已经烧进画面）：放在预览下方直接播；成品目录里有别的编码版本（对比用）也各放一个播放器。
  // 所有视频同时只播一个
  const players = [video];
  // 整行横跨页面，一行两列：成品视频 + 右边的 B 站投稿 JSON
  const finals = (s.finals || []).length ? h("div", { class: "finals" }) : null;
  const solo = (v) => v.addEventListener("play", () => players.forEach((x) => x !== v && x.pause()));
  solo(video);
  for (const f of s.finals || []) {
    const fin = h("video", { src: f.url, controls: true, preload: "none", playsinline: true, class: "final-video" });
    players.push(fin);
    solo(fin);
    // 成品在本机的完整路径：可以复制，或者直接在 Finder 里定位到这个文件
    const copyBtn = h("button", { class: "btn", onclick: async () => {
      try { await navigator.clipboard.writeText(f.path); copyBtn.textContent = "已复制"; } catch (e) { copyBtn.textContent = "复制失败"; }
      setTimeout(() => { copyBtn.textContent = "复制路径"; }, 1500);
    } }, "复制路径");
    const revealBtn = revealFinal(c, s, f.file);
    // 完整路径默认隐藏（长路径会折行，两列视频就对不齐了），点「显示路径」再展开
    const pathCode = h("code", { hidden: true }, f.path);
    const pathBtn = h("button", { class: "btn", onclick: () => {
      pathCode.hidden = !pathCode.hidden;
      pathBtn.textContent = pathCode.hidden ? "显示路径" : "隐藏路径";
    } }, "显示路径");
    finals.append(h("div", { class: "final-wrap" }, h("div", { class: "final-title" }, `成品 4K60 · ${f.label} · ${f.gb} GB（字幕和水印已烧进画面）`),
      h("div", { class: "final-path" }, pathBtn, copyBtn, revealBtn, pathCode), fin, formatLabel(f.format)));
  }

  // 加载字幕文件，叠在预览视频上
  const setAss = async (url) => {
    if (!url) { if (overlay) { overlay.setAss({ ...overlay.ass, events: [] }); overlay.tick(); } return; }
    const ass = parseAss(await (await fetch(url, { cache: "no-store" })).text());
    if (overlay) overlay.setAss(ass);
    else overlay = new SubOverlay(stage, video, ass, subOffset);
    applyLead();   // 里面会立即画一次（视频可能已经跳到位，暂停时不会再有 timeupdate）
  };
  return { el, finals, video, offset: subOffset, setAss,
    addPeer(peer) { players.push(peer); solo(peer); }, delay: () => BAKED_LEAD - lead };
}

// 逐句表格；每行时间怎么定的（几个来源投票）在「判定」的鼠标悬停说明里
const VERDICT = { ok: ["✓", "ok"], warn: ["黄", "warn"], bad: ["红", "bad"], miss: ["漏", "bad"], title: ["", ""],
  unconfirmed: ["未确认", "bad"], patch: ["补", "warn"], seq: ["顺序", "warn"], calib: ["校", "ok"], live: ["改词", "warn"], wm: ["水印", "wm"], crowd: ["合唱", "ok"], crowdseg: ["检测", "crowdseg"] };
// 语言用国旗显示（鼠标停上去看语言名）
const LANG = { en: ["🇬🇧", "英语"], es: ["🇪🇸", "西班牙语"], it: ["🇮🇹", "意大利语"], pt: ["🇵🇹", "葡萄牙语"], fr: ["🇫🇷", "法语"],
  ja: ["🇯🇵", "日语"], zh: ["🇨🇳", "中文"], ko: ["🇰🇷", "韩语"] };
const flag = (l) => (LANG[l] ? LANG[l][0] : l || "");
const langLabel = (r) => h("span", { class: "lang", title: LANG[r.lang] ? LANG[r.lang][1] : r.lang || "" }, flag(r.lang));
// 唱法：唱 / 说唱 / 讲话（按音高稳定度 + 语速判断）
const STYLE = { sing: ["唱", ""], rap: ["说唱", "rap"], speech: ["讲话", "speech"], crowd: ["观众合唱?", "crowd"],
  title: ["歌名歌手", ""], wm: ["水印", "wm"], crowd_ok: ["观众合唱", "crowd"], crowdseg: ["合唱检测", "crowdseg"] };
const styleLabel = (r) => h("span", { class: `style ${(STYLE[r.style] || ["", ""])[1]}`,
  title: r.style === "crowd" ? `人声左右声道相关性比本首中位低 ${-r.steady}（观众合唱是现场环境话筒收的，左右差别大），而且没有很准地对上 Genius；估计，请审听`
    : r.steady != null ? `音高稳定度 ${r.steady}（唱歌停在音上，高；说唱 / 讲话音高一直在滑，低）` : "" },
  r.speech && r.verdict !== "title" ? "讲话" : (STYLE[r.style] || [""])[0]);
function expTable(x, players) {
  const offset = players[0]?.offset || 0;
  const data = x.rows;
  // 直译版中文（只显示，不在页面上编辑：修改都通过对话由我改定稿表）：定稿 / 审校改过的标出来，顶部注释挂在下面
  const zh2Cell = (r) => {
    const issues = r.zh_issues || [];
    const badge = [r.zh_locked ? h("span", { class: "zh-badge locked", title: "你定稿的译法" }, "定稿") : null,
      issues.length ? h("span", { class: "zh-badge rev", title: issues.map((i) => `${i.type}：${i.problem}\n原：${i.from}\n改：${i.fix}`).join("\n\n") },
        "审校改") : null];
    const td = h("td", { class: "zh zh2" },
      r.zh2 || "", ...badge, r.note ? h("div", { class: "note-line" }, r.note) : null);
    return td;
  };
  const hasZh2 = data.some((r) => r.zh2);
  const hasZh3 = data.some((r) => r.zh3);   // 诗意版
  const M = x.models || { asr: "qwen-audio-3.1-asr-flash" };
  const rows = data.map((r) => h("tr", {
    class: [r.removed ? "removed" : "", r.speech ? "speech" : "", `v-${r.verdict}`].join(" ").trim(),
    onclick: () => {
      if (r.start_ms == null) return;
      const active = players.find(p => p.video === state.activeReviewVideo) || players[0];
      const coversTime = p => p?.video && !(r.start < p.start || r.start >= p.end);
      const target = coversTime(active) ? active : players.find(coversTime);
      if (!target) return;
      activate(target);
      if (r.watermark) { target.video.pause(); target.video.currentTime = target.offset + (r.start + r.end) / 2; return; }
      target.video.currentTime = Math.max(0, target.offset + r.start + target.delay());
      target.video.play().catch(error => { if (error.name !== "AbortError") toast(error.message, false); });

    },
  },
  // 时间按左边播放器的时间显示（预览视频比这首歌多留了开头，字幕时间 + offset 才和播放器对得上）
  h("td", { class: "t timing-meta" },
    h("span", {title: r.start_ms != null ? `歌曲内 ${fmtMs(r.start_ms)}` : ""},
      r.start_ms != null ? fmtMs(r.start_ms + Math.round((offset || 0) * 1000)) : "–"),
    langLabel(r), styleLabel(r)),
  h("td", { class: "g gcol" }, r.genius || (r.verdict === "title" || r.speech ? "" : h("span", { class: "none" }, "（Genius 没有）"))),
  h("td", { class: "heard" }, r.verdict === "title" ? h("span", { class: "none" }, r.strategy) : r.qwen || ""),
  h("td", { class: "o" }, r.text || h("span", { class: "none" }, "（没有字幕）"),
    r.credit ? h("div", { class: "credit" }, r.credit) : null,
    // 合唱检测行：这一段排进去的合唱字幕（时间按播放器时间）
    ...(r.crowdseg ? [["合唱字幕", r.crowd_lines]].filter(([, ls]) => ls).map(([label, ls]) =>
      h("div", { class: "seg-lines" }, h("div", { class: "seg-label" }, label),
        ...(ls.length ? ls.map((l) => h("div", {}, h("span", { class: "seg-t" }, fmtMs(Math.round((l.start + (offset || 0)) * 1000))), l.text))
          : [h("div", { class: "none" }, "（没有）")]))) : [])),
  ...(hasZh3 ? [h("td", { class: "zh zh3" }, r.zh3 || "")] : []),
  hasZh2 ? zh2Cell(r) : h("td", { class: "zh" }, r.zh || ""),
  h("td", { class: `vd ${VERDICT[r.verdict] ? VERDICT[r.verdict][1] : ""}`, title: r.strategy },
    (VERDICT[r.verdict] || [""])[0])));
  const wrap = h("div", { class: "table-wrap" }, h("table", { class: "lines-table exp-table" },
    h("thead", {}, h("tr", {}, h("th", {title:"时间 / 语言 / 唱法"}, "时间"),
      h("th", { class: "gcol" }, "Genius 原句"), h("th", {}, M.asr),
      h("th", {}, "校准字幕"),
      ...(hasZh3 ? [h("th", { title: `诗意版：${x.zh3_model || ""}` }, "诗意版")] : []),
      h("th", { title: hasZh2 ? `翻译：${x.zh2_model || ""}` : "" }, hasZh3 ? "直译版" : "中文"),
      h("th", {}, "判定"))),
    h("tbody", {}, ...rows)));
  let last = -1;
  function highlight(player) {
    if (!wrap.isConnected || state.activeReviewVideo !== player.video) return;
    const t = player.video.currentTime - player.offset - player.delay();
    const i = data.findIndex(r => !r.removed && !r.watermark && !r.crowdseg && t >= r.start && t < r.end);
    if (i === last) return;
    if (last >= 0) rows[last].classList.remove("now");
    last = i;
    if (i >= 0) {
      rows[i].classList.add("now");
      wrap.scrollTo({top: rows[i].offsetTop - wrap.clientHeight / 2, behavior: "smooth"});
    }
  }
  function activate(player) {
    state.activeReviewVideo = player.video;
    for (const other of players) if (other !== player) other.video?.pause();
    highlight(player);
  }
  for (const player of players) {
    if (!player.video) continue;
    player.video.addEventListener("play", () => activate(player));
    player.video.addEventListener("pointerdown", () => activate(player));
    player.video.addEventListener("focus", () => activate(player));
    player.video.addEventListener("timeupdate", () => highlight(player));
  }
  const n = (v) => data.filter((r) => r.verdict === v).length;
  const p = x.profile;
  const bits = [`${data.filter((r) => !r.removed && r.verdict !== "title" && !r.watermark && !r.crowdseg).length} 行`,
    data.filter((r) => r.crowdseg && r.text.includes("：观众合唱")).length && `观众合唱 ${data.filter((r) => r.crowdseg && r.text.includes("：观众合唱")).length} 段`,
    data.filter((r) => r.watermark).length && `水印 ${data.filter((r) => r.watermark).length} 次`,
    p ? `语言 ${(p.langs || [p.main]).map(flag).join(" ")}${p.mismatch ? `（识别出来是 ${flag(p.heard_main)}）` : ""}` : "",
    data.filter((r) => r.anchor).length && `锚点 ${data.filter((r) => r.anchor).length}`,
    n("calib") && `校 ${n("calib")}`, n("seq") && `顺序 ${n("seq")}`, n("live") && `现场改词 ${n("live")}`,
    n("warn") && `黄 ${n("warn")}`, n("bad") && `红 ${n("bad")}`, n("patch") && `补 ${n("patch")}`,
    data.filter((r) => r.speech).length && `讲话 ${data.filter((r) => r.speech).length}`,
    data.filter((r) => r.style === "rap").length && `说唱 ${data.filter((r) => r.style === "rap").length}`,
    data.filter((r) => r.style === "crowd").length && `观众合唱? ${data.filter((r) => r.style === "crowd").length}`,
    n("miss") && `漏 ${n("miss")}`, n("unconfirmed") && `未确认 ${n("unconfirmed")}`].filter(Boolean);
  let showG = false;
  try { showG = localStorage.getItem("showGenius") === "1"; } catch (e) { /* 无痕模式 */ }
  wrap.classList.toggle("hide-genius", !showG);
  const gBtn = h("button", { class: "btn mini", title: "展开 / 收起 Genius 原句这一列", onclick: (e) => {
    e.preventDefault(); e.stopPropagation();
    showG = !showG;
    try { localStorage.setItem("showGenius", showG ? "1" : "0"); } catch (err) { /* 无痕模式 */ }
    wrap.classList.toggle("hide-genius", !showG);
    gBtn.textContent = showG ? "收起 Genius 原句" : "展开 Genius 原句";
  } }, showG ? "收起 Genius 原句" : "展开 Genius 原句");
  return h("details", { class: "lines", open: true }, h("summary", {}, bits.join(" · "), " ", gBtn), wrap);
}

const fmtMs = (ms) => `${Math.floor(ms / 60000)}:${String(Math.floor(ms / 1000) % 60).padStart(2, "0")}.${String(ms % 1000).padStart(3, "0")}`;

// ---------------------------------------------------------------- 封面池（整场挑封面）

// 整场演唱会挑出来的画面（workflow/live/cover_pool.py）：点一下标记「适合做封面」，再点取消；
// 标记完跟我说，我把标记的画面随机分给这次要做的歌（cover_pool assign），每首按当前歌名排好 3:4 竖封面和同帧 4:3 横封面 存成封面
async function viewCoverPool(route) {
  const c = state.concert;
  document.title = "演唱会";
  const { frames, songs, selected = [], quality_stage } = await api(`/api/concerts/${c.slug}/cover_pool`);
  const titleOf = Object.fromEntries(c.songs.map((s) => [s.name, s.title]));
  const st = { kind: "all" };
  const kindBar = h("div", { class: "seg" });
  const count = h("span", { class: "hint" });
  const grid = h("div", { class: "covers pool raw-pool-grid" });
  const upd = () => {
    const n = frames.filter((f) => f.marked).length;
    count.textContent = `共 ${frames.length} 张合格原片候选 · 已标记 ${n} 张 · 待分配 ${songs.length} 首${["checking", "extracting"].includes(quality_stage) ? " · 正在筛选补充" : ""}`;
  };
  const dialog = h("dialog", {class:"pool-frame-dialog", "aria-label":"原片候选帧放大",
    onclick:event=>{if(event.target===dialog)dialog.close();}});
  const buttons = new Map();
  async function toggle(f) {
    if(f.busy)return;
    f.busy=true;
    try {
      await api(`/api/concerts/${c.slug}/cover_pool/mark`, {file:f.file,on:!f.marked});
      f.marked=!f.marked;
      for(const button of buttons.get(f.file)||[]) {
        button.setAttribute("aria-pressed",String(f.marked));
        button.textContent=f.marked?"✓":"选定";
        button.closest(".pool-frame-card")?.classList.toggle("on",f.marked);
      }
      upd();
    } catch(err) {toast(`标记失败：${err.message||err}`,false);}
    finally {f.busy=false;}
  }
  function pickButton(f) {
    const button=h("button",{type:"button",class:"pool-frame-pick","aria-label":"选定原片帧 "+hms(f.t),
      "aria-pressed":String(f.marked),onclick:event=>{event.stopPropagation();toggle(f);}},f.marked?"✓":"选定");
    if(!buttons.has(f.file))buttons.set(f.file,[]);
    buttons.get(f.file).push(button);return button;
  }
  function enlarge(f) {
    dialog.replaceChildren(h("img",{src:f.url,alt:"原片候选帧 "+hms(f.t)}),pickButton(f),
      h("button",{type:"button",class:"pool-frame-close","aria-label":"关闭放大",onclick:()=>dialog.close()},"×"));
    dialog.showModal();
  }
  const card = f => h("div",{class:`cover pool-frame-card${f.marked?" on":""}`,onclick:()=>enlarge(f)},
    h("button",{type:"button",class:"pool-frame-image",title:f.why||"点击放大原片帧"},
      h("img",{src:f.url,alt:"原片候选帧 "+hms(f.t),loading:"lazy"})),
    h("span",{class:"ct"},hms(f.t)),pickButton(f));
  const draw = () => {
    kindBar.replaceChildren(...[["all", "全部"], ["closeup", "特写"], ["half", "半身"], ["scene", "舞台"]].map(([k, l]) =>
      h("button", { class: k === st.kind ? "on" : null, onclick: () => { st.kind = k; draw(); } }, l)));
    const xs = frames.filter((f) => st.kind === "all" || f.kind === st.kind);
    grid.replaceChildren(...(xs.length ? xs.map(card)
      : [h("div", { class: "placeholder" }, frames.length ? "这一类没有画面" : "这场演唱会还没有可挑选的画面")]));
  };
  // 标记完成：标记的画面随机分给要做的歌，每首按歌名排好存成封面；结果列在按钮下面
  const result = h("div", { class: "covers pool selected-portrait-pool" });
  const selectedLabel = h("div", { class: "section-label" });
  const ratioTabs = h("div", {class:"song-tabs",role:"tablist","aria-label":"已选封面比例"});
  let selectedRows = selected;
  let wide = false;
  const showSelected = (rows) => {
    selectedRows = rows;
    selectedLabel.hidden = ratioTabs.hidden = result.hidden = !rows.length;
    selectedLabel.textContent = `已选封面（${rows.length}首）`;
    result.classList.toggle("r43", wide);
    Array.from(ratioTabs.children).forEach((tab, i) => tab.setAttribute("aria-selected", String(Boolean(i) === wide)));
    result.replaceChildren(...rows.filter(x => !wide || x.file_4x3).map(x => {
      const url = wide ? x.file_4x3 : x.file;
      return h("button", {class:"cover", title:x.title, onclick:() => lightbox(url)},
        h("img", {src:url, alt:x.title, loading:"lazy"}), h("span", {class:"ct"}, x.title));
    }));
  };
  ["竖封面3:4", "横封面4:3"].forEach((label, i) => ratioTabs.append(h("button", {type:"button", role:"tab",
    onclick:() => { wide = Boolean(i); showSelected(selectedRows); }}, label)));
  showSelected(selected);
  const done = h("button", { class: "btn ok", onclick: async () => {
    if (done.disabled) return;
    done.disabled = true;
    done.textContent = "分配中…";
    try {
      const r = await api(`/api/concerts/${c.slug}/cover_pool/assign`, {});
      showSelected(r.songs);
      await refreshConcert(c.slug);
      toast(`已分配 ${r.songs.length} 首的封面`);
    } catch (err) { toast(`分配失败：${err.message || err}`, false); }
    done.disabled = false;
    done.textContent = "标记完成";
  } }, "标记完成");
  draw();
  upd();
  $("#view").replaceChildren(h("div", { class: "card" },
    h("div", { class: "card-head" }, h("div", { class: "card-title" }, "封面池",
      h("small", {}, `整场挑出 ${frames.length} 张画面；点击图片放大，右上角选定；标记完成后分配到各首歌曲`))),
    h("div", { class: "pool-body" }, h("div", { class: "pool-head" }, count, kindBar),
      h("div", { class: "actions" }, done, h("span", { class: "hint" }, "从已标记的原片帧分配封面，按各曲歌名生成 3:4 竖封面和同帧 4:3 横封面")),
      grid, selectedLabel, ratioTabs, result, dialog)));
}

// ---------------------------------------------------------------- 路由

function parseRoute() {
  const [slug, rest] = location.hash.replace(/^#\/?/, "").split("/");
  const [name, at] = (rest ? decodeURIComponent(rest) : "").split("@");
  const group = state.concerts.find(x => x.aliases?.includes(slug));
  return { slug: group?.slug || slug || (state.concerts[0] || {}).slug, name: name || null, at: at ? +at : null };
}

async function refreshConcert(slug) {
  slug = slug || state.concert.slug;
  const concert = await api(`/api/concerts/${slug}`);
  if (parseRoute().slug !== slug) return;
  state.concert = concert;
  renderSidebar(parseRoute());
}

async function render() {
  state.cleanup.forEach((f) => f());
  state.cleanup = [];
  if (state.video) { state.video.pause(); state.video.removeAttribute("src"); state.video.load(); state.video = null; }
  state.activeReviewVideo = null;
  const route = parseRoute();
  if (route.name) $("#sidebar").classList.remove("open");
  if (!route.slug) { $("#view").replaceChildren(h("div", { class: "empty" }, "concerts/ 下还没有场次")); return; }
  try {
    const requestedHash = location.hash;
    await refreshConcert(route.slug);
    if (location.hash !== requestedHash) return;
    if (route.name === "~covers" && !state.concert.has_cover_pool) route.name = null;
    if (route.name === "~covers") await viewCoverPool(route);
    else if (route.name) await viewSong(route);
    else {
      const first = state.concert.songs[0];
      if (!first) { $("#view").replaceChildren(h("div", {class:"empty"}, "这场还没有歌曲")); return; }
      route.name = first.name;
      history.replaceState(null, "", `#/${route.slug}/${route.name}`);
      renderSidebar(route);
      await viewSong(route);
    }
  } catch (err) {
    $("#view").replaceChildren(h("div", { class: "empty" }, `加载失败：${err.message}`));
  }
}

// 全屏的是外层容器而不是 <video>，否则叠加的字幕会被挡掉
function toggleFullscreen(el) {
  if (document.fullscreenElement) document.exitFullscreen();
  else if (el && el.requestFullscreen) el.requestFullscreen();
}

$("#menu").addEventListener("click", () => $("#sidebar").classList.toggle("open"));
// 快捷键在最外层（捕获阶段）统一处理：空格只做播放/暂停——不让浏览器翻页，也不和视频自带的空格、
// 刚点过的按钮（焦点还在按钮上，空格会再点一次）重复触发
window.addEventListener("keydown", (e) => {
  if (document.querySelector(".portrait-cover-dialog[open]")) return;
  const tag = (e.target && e.target.tagName) || "";
  if (/INPUT|TEXTAREA|SELECT/.test(tag) || e.metaKey || e.ctrlKey || e.altKey) return;
  const v = state.activeReviewVideo || state.video;
  if (!v || v.closest("[hidden]") || e.target.closest?.(".song-tabs")) return;
  if (e.code === "Space" || e.key === " ") {
    e.preventDefault();
    e.stopPropagation();
    if (document.activeElement && document.activeElement !== document.body) document.activeElement.blur();
    if (!e.repeat) (v.paused ? v.play() : v.pause());
  } else if (e.key === "f" || e.key === "F") toggleFullscreen(v.closest(".stage") || v);
}, true);
window.addEventListener("hashchange", render);

(async () => {
  try { state.concerts = await api("/api/concerts"); } catch (err) { state.concerts = []; }
  render();
})();
