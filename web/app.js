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

function renderSidebar(route) {
  const c = state.concert;
  $("#concerts").replaceChildren(...state.concerts.map((x) =>
    h("a", { href: `#/${x.slug}`, class: x.slug === route.slug && !route.name ? "active" : null },
      h("span", { class: "jn" }, x.title), h("span", { class: "jd" }, `${x.songs} 首`))));
  const ul = $("#songs");
  if (!c) { ul.replaceChildren(); return; }
  const songs = Object.fromEntries(c.songs.map((s) => [s.name, s]));
  ul.replaceChildren(...c.items.map((it) => {
    if (it.kind !== "song") return h("li", { class: "tape", title: "过场（预录视频），不出成品" }, `~ ${it.title}`);
    const s = songs[it.name];
    const warn = s.start == null || (s.confidence != null && s.confidence < 0.5) || s.needs_refine;
    return h("li", {}, h("a", { href: `#/${c.slug}/${it.name}`, class: route.name === it.name ? "active" : null, title: it.title },
      h("span", { class: "ji" }, it.idx),
      h("span", { class: "jn" }, it.title),
      warn ? h("span", { class: "warn", title: s.needs_refine ? "边界改过，需要重跑精校" : "定位置信度低" }, "⚠") : null,
      h("span", { class: "jd" }, s.start != null ? fmt(s.end - s.start) : "")));
  }));
}

// ---------------------------------------------------------------- 总览

function viewOverview() {
  const c = state.concert;
  document.title = c.info.title || c.slug;
  const card = h("div", { class: "card" },
    h("div", { class: "card-head" },
      h("div", { class: "card-title" }, `歌单 ${c.songs.length} 首`, h("small", {}, `整场 ${hms(c.info.duration)}`)),
      h("div", { class: "spacer" }),
      c.info.setlist_url ? h("a", { href: c.info.setlist_url, target: "_blank", rel: "noopener" }, "setlist.fm") : null),
    timeline(c, null, null),
    h("div", { class: "table-wrap", style: "max-height:none" }, h("table", { class: "overview" },
      h("thead", {}, h("tr", {}, ...["#", "封面", "歌名", "开始", "时长", "进度", "审核", "提示"].map((x) => h("th", {}, x)))),
      h("tbody", {}, ...c.songs.map((s) => h("tr", { onclick: () => { location.hash = `#/${c.slug}/${s.name}`; } },
        h("td", { class: "t" }, s.idx),
        h("td", {}, s.thumb ? h("img", { src: s.thumb, loading: "lazy" }) : ""),
        h("td", {}, s.title),
        h("td", { class: "t" }, hms(s.start)),
        h("td", { class: "t" }, s.start != null ? fmt(s.end - s.start) : "–"),
        h("td", {}, STAGE[s.stage]),
        h("td", {}, h("span", { class: `chip ${REVIEW[s.review][1]}` }, REVIEW[s.review][0])),
        h("td", { class: "hint" }, [...s.flags, s.needs_refine ? "边界改过，字幕待重跑" : null].filter(Boolean).join("；"))))))));
  $("#view").replaceChildren(card);
}

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

async function viewSong(route) {
  const c = state.concert;
  const s = await api(`/api/concerts/${c.slug}/songs/${route.name}`);
  state.song = s;
  document.title = `${s.idx}. ${s.title}`;
  const head = h("div", { class: "card-head" },
    h("div", { class: "card-title" }, s.title, h("small", {}, `${hms(s.start)} – ${hms(s.end)}（${fmt(s.end - s.start)}）`)),
    h("div", { class: "spacer" }),
    ...(s.genius_urls || []).map((u, i) => h("a", { href: u, target: "_blank", rel: "noopener" }, s.genius_urls.length > 1 ? `歌词 ${i + 1}` : "Genius 歌词")));
  // 布局：上面 左 视频 / 右 歌词和翻译（跟着播放滚动）；下面 左 候选封面 / 右 投稿信息
  const player = await videoPane(c, s, route.at);
  const covers = coverPane(s);
  const form = formPane(c, s, covers);
  // 歌词栏：逐句表格；视频上的字幕用诗意版（和成品一致），这首没有诗意版时用直译版
  const x = s.exp;
  const lyricsPane = h("div", { class: "pane lyrics-pane" },
    x ? expTable(x, player.video, player.offset, player.delay) : h("div", { class: "empty" }, "还没有字幕（refine 阶段）"));
  if (x && player.setAss) await player.setAss(x.ass_poetic || x.ass_literal || x.ass);
  // 注释入口放在歌名旁边：显示这首有几条注释，点开是列表
  const nNotes = x ? x.rows.filter((r) => r.note && !r.removed).length : 0;
  if (nNotes) head.querySelector(".card-title").append(
    h("a", { class: "notes-link", href: "javascript:void 0", onclick: () => showNotes(x, player, s) }, `注释 ${nNotes}`));
  const card = h("div", { class: "card" }, head,
    h("div", { class: "top" }, player.el, lyricsPane),
    player.finals,
    h("div", { class: "bottom" }, covers.el, form));
  $("#view").replaceChildren(card);
}

// 所有顶部注释和对应原文（当前版本）：页面内弹层，点一条跳到那一句
function showNotes(x, player, s) {
  const rows = x ? x.rows.filter((r) => r.note && !r.removed) : [];
  const close = () => { box.remove(); window.removeEventListener("keydown", onKey, true); };
  const onKey = (e) => { if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); close(); } };
  const list = rows.length ? h("table", { class: "notes-list" },
    h("thead", {}, h("tr", {}, h("th", {}, "时间"), h("th", {}, "原文"), h("th", {}, "中文"), h("th", {}, "注释"))),
    h("tbody", {}, ...rows.map((r) => h("tr", { onclick: () => {
      if (player.video) { player.video.currentTime = player.offset + r.start + player.delay(); player.video.play(); }
      close();
    } }, h("td", { class: "t" }, fmtMs(r.start_ms + Math.round((player.offset || 0) * 1000))), h("td", {}, r.text),
      h("td", {}, r.zh2 || r.zh || ""), h("td", { class: "note" }, r.note)))))
    : h("div", { class: "empty" }, "这首没有顶部注释");
  const box = h("div", { class: "lightbox notes-box", onclick: (e) => { if (e.target === box) close(); } },
    h("div", { class: "notes-panel" }, h("div", { class: "notes-title" }, `${s.title} · 顶部注释 ${rows.length} 条`,
      h("button", { class: "lb-close", title: "关闭（Esc）", onclick: close }, "×")), list));
  window.addEventListener("keydown", onKey, true);
  document.body.append(box);
}

// 看大图：页面内弹层（不开新标签页——审核页可能是独立窗口，新开的页没法关），× / Esc / 点图外面都能关
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
  const entry = s.review_entry || {};
  const st = { chosen: entry.cover || null, ratio: "169" };
  const box = h("div", { class: "covers" });
  const draw = () => {
    box.className = `covers${st.ratio === "43" ? " r43" : ""}`;
    const card = (x) => {
      const src = st.ratio === "43" && x.file_4x3 ? x.file_4x3 : x.file;
      const top = x.rank != null && x.rank <= 3;
      return h("button", {
        class: `cover${x.id === st.chosen ? " on" : ""}${top ? " best" : ""}`,
        title: `${x.id}${x.score != null ? ` · 分数 ${x.score.toFixed(2)}` : ""}${x.why ? ` · ${x.why}` : ""}（双击看大图）`,
        onclick: () => { st.chosen = x.id; draw(); },
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
    // 排过序（cover_rank）：算法推荐 Top3 一组，其余按分数一组；没排过就照旧按景别平铺
    const ranked = s.covers.some((x) => x.rank != null);
    const groups = ranked
      ? [["算法推荐 Top3", s.covers.filter((x) => x.rank <= 3)], ["其他（按分数）", s.covers.filter((x) => !(x.rank <= 3))]]
      : [[null, s.covers]];
    box.replaceChildren(...(s.covers.length ? groups.flatMap(([label, xs]) =>
      xs.length ? [label ? h("div", { class: "cover-group" }, label) : null, ...xs.map(card)].filter(Boolean) : [])
      : [h("div", { class: "placeholder" }, "还没有候选封面（package 阶段）")]));
  };
  draw();
  const sw = h("div", { class: "seg" }, ...[["169", "16:9"], ["43", "4:3"]].map(([k, l]) =>
    h("button", { class: k === st.ratio ? "on" : null, "data-k": k, onclick: () => {
      st.ratio = k; draw();
      sw.querySelectorAll("button").forEach((b) => b.classList.toggle("on", b.dataset.k === k));
    } }, l)));
  return { el: h("div", { class: "pane" }, h("div", { class: "section-label" }, "候选封面（点选一张）", sw), box), state: st };
}

function formPane(c, s, covers) {
  // 投稿信息只看 B 站投稿 JSON（post/bili_upload.json，放在成品右边）；要改哪项走对话，由我改 JSON
  const entry = s.review_entry || {};
  const note = h("input", { value: entry.note || "" });
  const msg = h("span", { class: "hint" }, entry.updated_at ? `上次保存 ${entry.updated_at}` : "");
  const save = async (status) => {
    try {
      const r = await api(`/api/concerts/${c.slug}/songs/${s.name}/review`, { status, cover: covers.state.chosen, note: note.value.trim() });
      msg.textContent = `已保存 ${r.entry.updated_at}${status === "approved" ? " · 已通过" : status === "rejected" ? " · 已打回" : ""}`;
      await refreshConcert();
    } catch (err) { msg.textContent = `保存失败：${err.message}`; }
  };
  return h("div", { class: "form" },
    h("div", { class: "section-label" }, "审核"),
    h("div", { class: "actions" },
      h("label", { class: "grow" }, "备注（打回原因等）", note),
      h("button", { class: "btn", onclick: () => save(undefined) }, "保存"),
      h("button", { class: "btn ok", onclick: () => save("approved") }, "通过"),
      h("button", { class: "btn bad", onclick: () => save("rejected") }, "打回"),
      msg));
}

// B 站投稿 JSON（post/bili_upload.json）：上传时原样提交的全部字段，只展示（要改走对话）
function biliJson(s) {
  const label = h("div", { class: "json-label" }, "B 站投稿 JSON（上传时原样提交，要改跟我说）");
  const btn = h("button", { class: "btn mini", onclick: async (e) => {
    e.preventDefault();
    try { await navigator.clipboard.writeText(s.bili_upload); btn.textContent = "已复制"; } catch (err) { btn.textContent = "复制失败"; }
    setTimeout(() => { btn.textContent = "复制"; }, 1500);
  } }, "复制");
  label.append(btn);
  return h("div", { class: "bili-json" }, label, h("div", { class: "hint" }, s.bili_upload_path), h("pre", { class: "json-view" }, s.bili_upload));
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
  const video = h("video", { src: s.preview, controls: true, preload: "auto", playsinline: true,
    controlslist: "nofullscreen", disablepictureinpicture: true });
  // 左上角叠朝阳 Adele 的 logo（只是预览：和成品 render.py 一样的比例和位置——宽度约为画面的 10.25%、离画面内容左上角 15/3840；
  // 宽银幕片源上下有黑边，放在内容区域 s.box 里，不放在黑边上；不改视频文件，只是一张图片叠在播放器上）
  const logo = h("img", { src: "adele-logo.png", class: "preview-logo", alt: "" });
  const stage = h("div", { class: "stage" }, video, logo);
  const placeLogo = () => {
    const W = video.clientWidth, H = video.clientHeight;
    const ar = video.videoWidth && video.videoHeight ? video.videoWidth / video.videoHeight : 16 / 9;
    const cw = Math.min(W, H * ar), ch = cw / ar;   // 画面按 contain 居中，算出实际画面区域
    const x0 = (W - cw) / 2, y0 = (H - ch) / 2;
    const b = s.box || { x: 0, y: 0 };
    Object.assign(logo.style, { left: `${x0 + cw * (b.x + 15 / 3840)}px`, top: `${y0 + ch * (b.y + 15 / 2160)}px`, width: `${cw * 0.1025}px` });
  };
  new ResizeObserver(placeLogo).observe(video);
  video.addEventListener("loadedmetadata", placeLogo);
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
    h("div", { class: "pane-title" }, "字幕预览版", h("span", { class: "pane-sub" }, "720p · 字幕叠加预览，用来核字幕和起止点")),
    stage,
    h("div", { class: "toolbar tight" },
      leadSwitch,
      h("div", { class: "spacer" }),
      subSwitch,
      h("button", { class: "btn", onclick: () => toggleFullscreen(stage) }, "⛶")));
  // 成品（4K60、字幕和水印已经烧进画面）：放在预览下方直接播；成品目录里有别的编码版本（对比用）也各放一个播放器。
  // 所有视频同时只播一个
  const players = [video];
  // 整行横跨页面，一行两列：成品视频 + 右边的 B 站投稿 JSON
  const finals = (s.finals || []).length || s.bili_upload ? h("div", { class: "finals" }) : null;
  const solo = (v) => v.addEventListener("play", () => players.forEach((x) => x !== v && x.pause()));
  solo(video);
  for (const f of s.finals || []) {
    const fin = h("video", { src: f.url, controls: true, preload: "metadata", playsinline: true, class: "final-video" });
    players.push(fin);
    solo(fin);
    // 成品在本机的完整路径：可以复制，或者直接在 Finder 里定位到这个文件
    const copyBtn = h("button", { class: "btn", onclick: async () => {
      try { await navigator.clipboard.writeText(f.path); copyBtn.textContent = "已复制"; } catch (e) { copyBtn.textContent = "复制失败"; }
      setTimeout(() => { copyBtn.textContent = "复制路径"; }, 1500);
    } }, "复制路径");
    const revealBtn = h("button", { class: "btn", onclick: () =>
      fetch(`/api/concerts/${c.slug}/songs/${s.name}/reveal_final?file=${encodeURIComponent(f.file)}`, { method: "POST" }) },
      "在 Finder 中显示");
    // 完整路径默认隐藏（长路径会折行，两列视频就对不齐了），点「显示路径」再展开
    const pathCode = h("code", { hidden: true }, f.path);
    const pathBtn = h("button", { class: "btn", onclick: () => {
      pathCode.hidden = !pathCode.hidden;
      pathBtn.textContent = pathCode.hidden ? "显示路径" : "隐藏路径";
    } }, "显示路径");
    finals.append(h("div", { class: "final-wrap" }, h("div", { class: "final-title" }, `成品 4K60 · ${f.label} · ${f.gb} GB（字幕和水印已烧进画面）`),
      h("div", { class: "final-path" }, pathBtn, copyBtn, revealBtn, pathCode), fin));
  }
  if (finals && s.bili_upload) finals.append(biliJson(s));   // 右边：B 站投稿 JSON

  // 加载字幕文件，叠在预览视频上
  const setAss = async (url) => {
    if (!url) { if (overlay) { overlay.setAss({ ...overlay.ass, events: [] }); overlay.tick(); } return; }
    const ass = parseAss(await (await fetch(url, { cache: "no-store" })).text());
    if (overlay) overlay.setAss(ass);
    else overlay = new SubOverlay(stage, video, ass, subOffset);
    applyLead();   // 里面会立即画一次（视频可能已经跳到位，暂停时不会再有 timeupdate）
  };
  return { el, finals, video, offset: subOffset, setAss, delay: () => BAKED_LEAD - lead };
}

// 逐句表格；每行时间怎么定的（几个来源投票）在「判定」的鼠标悬停说明里
const VERDICT = { ok: ["✓", "ok"], warn: ["黄", "warn"], bad: ["红", "bad"], miss: ["漏", "bad"], title: ["", ""],
  unconfirmed: ["未确认", "bad"], patch: ["补", "warn"], seq: ["顺序", "warn"], calib: ["校", "ok"], live: ["改词", "warn"], wm: ["水印", "wm"], crowd: ["合唱", "ok"], crowdseg: ["检测", "crowdseg"] };
// 语言用国旗显示（鼠标停上去看语言名）
const LANG = { en: ["🇬🇧", "英语"], es: ["🇪🇸", "西班牙语"], it: ["🇮🇹", "意大利语"], pt: ["🇵🇹", "葡萄牙语"], fr: ["🇫🇷", "法语"],
  ja: ["🇯🇵", "日语"], zh: ["🇨🇳", "中文"], ko: ["🇰🇷", "韩语"] };
const flag = (l) => (LANG[l] ? LANG[l][0] : l || "");
const langTd = (r) => h("td", { class: "lang", title: LANG[r.lang] ? LANG[r.lang][1] : r.lang || "" }, flag(r.lang));
// 唱法：唱 / 说唱 / 讲话（按音高稳定度 + 语速判断）
const STYLE = { sing: ["唱", ""], rap: ["说唱", "rap"], speech: ["讲话", "speech"], crowd: ["观众合唱?", "crowd"],
  title: ["歌名歌手", ""], wm: ["水印", "wm"], crowd_ok: ["观众合唱", "crowd"], crowdseg: ["合唱检测", "crowdseg"] };
const styleTd = (r) => h("td", { class: `style ${(STYLE[r.style] || ["", ""])[1]}`,
  title: r.style === "crowd" ? `人声左右声道相关性比本首中位低 ${-r.steady}（观众合唱是现场环境话筒收的，左右差别大），而且没有很准地对上 Genius；估计，请审听`
    : r.steady != null ? `音高稳定度 ${r.steady}（唱歌停在音上，高；说唱 / 讲话音高一直在滑，低）` : "" },
  r.speech && r.verdict !== "title" ? "讲话" : (STYLE[r.style] || [""])[0]);
function expTable(x, video, offset, delay = () => 0) {
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
      if (!video || r.start_ms == null) return;
      if (r.watermark) { video.pause(); video.currentTime = offset + (r.start + r.end) / 2; return; }   // 水印：停在 3 秒的正中间
      video.currentTime = offset + r.start + delay(); video.play();
    },
  },
  // 时间按左边播放器的时间显示（预览视频比这首歌多留了开头，字幕时间 + offset 才和播放器对得上）
  h("td", { class: "t", title: r.start_ms != null ? `歌曲内 ${fmtMs(r.start_ms)}` : "" },
    r.start_ms != null ? fmtMs(r.start_ms + Math.round((offset || 0) * 1000)) : "–"),
  langTd(r),
  styleTd(r),
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
    h("thead", {}, h("tr", {}, h("th", {}, "时间"), h("th", { class: "lang" }, "语言"), h("th", { class: "lang" }, "唱法"),
      h("th", { class: "gcol" }, "Genius 原句"), h("th", {}, M.asr),
      h("th", {}, "校准字幕"),
      ...(hasZh3 ? [h("th", { title: `诗意版：${x.zh3_model || ""}` }, "诗意版")] : []),
      h("th", { title: hasZh2 ? `翻译：${x.zh2_model || ""}` : "" }, hasZh3 ? "直译版" : "中文"),
      h("th", {}, "判定"))),
    h("tbody", {}, ...rows)));
  if (video) {
    let last = -1;
    video.addEventListener("timeupdate", () => {
      if (!wrap.isConnected) return;
      const t = video.currentTime - offset - delay();   // 和画面上的字幕用同一个提前量
      const i = data.findIndex((r) => !r.removed && !r.watermark && !r.crowdseg && t >= r.start && t < r.end);
      if (i === last) return;
      if (last >= 0) rows[last].classList.remove("now");
      last = i;
      if (i >= 0) {
        rows[i].classList.add("now");
        wrap.scrollTo({ top: rows[i].offsetTop - wrap.clientHeight / 2, behavior: "smooth" });
      }
    });
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

// ---------------------------------------------------------------- 路由

function parseRoute() {
  const [slug, rest] = location.hash.replace(/^#\/?/, "").split("/");
  const [name, at] = (rest ? decodeURIComponent(rest) : "").split("@");
  return { slug: slug || (state.concerts[0] || {}).slug, name: name || null, at: at ? +at : null };
}

async function refreshConcert(slug) {
  slug = slug || state.concert.slug;
  state.concert = await api(`/api/concerts/${slug}`);
  renderSidebar(parseRoute());
}

async function render() {
  state.cleanup.forEach((f) => f());
  state.cleanup = [];
  if (state.video) { state.video.pause(); state.video.removeAttribute("src"); state.video.load(); state.video = null; }
  const route = parseRoute();
  $("#sidebar").classList.remove("open");
  if (!route.slug) { $("#view").replaceChildren(h("div", { class: "empty" }, "concerts/ 下还没有场次")); return; }
  try {
    await refreshConcert(route.slug);
    if (route.name) await viewSong(route);
    else viewOverview();
  } catch (err) {
    $("#view").replaceChildren(h("div", { class: "empty" }, `加载失败：${err.message}`));
  }
}

// 全屏的是外层容器而不是 <video>，否则叠加的字幕会被挡掉
function toggleFullscreen(el) {
  if (document.fullscreenElement) document.exitFullscreen();
  else if (el && el.requestFullscreen) el.requestFullscreen();
}

// 侧边栏：刷新后默认打开；展开后 10 分钟自动收起（鼠标停在侧边栏上时不收，移开后重新计时）
const SIDE_AUTO_CLOSE = 10 * 60 * 1000;
let sideTimer = null;
function armSideClose() {
  clearTimeout(sideTimer);
  sideTimer = setTimeout(() => {
    if (!$("#sidebar").matches(":hover")) setCollapsed(true);
  }, SIDE_AUTO_CLOSE);
}
function setCollapsed(v) {
  $("#app").classList.toggle("collapsed", v);
  if (v) clearTimeout(sideTimer);
  else armSideClose();
}
setCollapsed(false);
$("#sidebar").addEventListener("mouseleave", () => { if (!$("#app").classList.contains("collapsed")) armSideClose(); });
$("#side-toggle").addEventListener("click", () => { setCollapsed(true); $("#sidebar").classList.remove("open"); });
$("#menu").addEventListener("click", () => {
  if (window.innerWidth <= 720) $("#sidebar").classList.toggle("open");
  else setCollapsed(false);
});
// 快捷键在最外层（捕获阶段）统一处理：空格只做播放/暂停——不让浏览器翻页，也不和视频自带的空格、
// 刚点过的按钮（焦点还在按钮上，空格会再点一次）重复触发
window.addEventListener("keydown", (e) => {
  const tag = (e.target && e.target.tagName) || "";
  if (/INPUT|TEXTAREA|SELECT/.test(tag) || e.metaKey || e.ctrlKey || e.altKey) return;
  const v = state.video;
  if (!v) return;
  if (e.code === "Space" || e.key === " ") {
    e.preventDefault();
    e.stopPropagation();
    if (document.activeElement && document.activeElement !== document.body) document.activeElement.blur();
    if (!e.repeat) (v.paused ? v.play() : v.pause());
  } else if (e.key === "f" || e.key === "F") toggleFullscreen(v.closest(".stage"));
}, true);
window.addEventListener("hashchange", render);

(async () => {
  try { state.concerts = await api("/api/concerts"); } catch (err) { state.concerts = []; }
  render();
})();
