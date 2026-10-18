// adele v2 演唱会审核页：纯 JS，无构建（结构拷自 SubDub web/app.js）。
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
const TITLE_MAX = 80;
const SHOT = { closeup: "特写", half: "半身", full: "全身", cover: "补充" };

const state = { concerts: [], concert: null, song: null, cleanup: [] };

// ---------------------------------------------------------------- sidebar

function renderSidebar(route) {
  const c = state.concert;
  // 顶栏的场次切换（侧边栏收起时也能切）
  const pick = $("#concert-pick");
  pick.replaceChildren(...state.concerts.map((x) => h("option", { value: x.slug }, `${x.title}（${x.songs} 首）`)));
  pick.value = route.slug || "";
  pick.onchange = () => { location.hash = `#/${pick.value}`; };
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
      h("span", { class: `dot ${s.review}`, title: REVIEW[s.review][0] }),
      h("span", { class: "ji" }, it.idx),
      h("span", { class: "jn" }, it.title),
      warn ? h("span", { class: "warn", title: s.needs_refine ? "边界改过，需要重跑精校" : "定位置信度低" }, "⚠") : null,
      h("span", { class: "jd" }, s.start != null ? fmt(s.end - s.start) : "")));
  }));
}

function chipsFor(s) {
  const [rl, rc] = REVIEW[s.review];
  return [
    h("span", { class: `chip ${rc}` }, rl),
    h("span", { class: "chip gray" }, STAGE[s.stage] || s.stage),
    s.confidence != null ? h("span", { class: `chip ${s.confidence < 0.5 ? "warn" : "gray"}` }, `定位置信 ${Math.round(s.confidence * 100)}%`) : null,
    ...s.flags.map((f) => h("span", { class: "chip warn" }, f)),
    s.needs_refine ? h("span", { class: "chip warn" }, "边界改过，字幕待重跑") : null,
  ];
}

// ---------------------------------------------------------------- 总览

function viewOverview() {
  const c = state.concert;
  $("#title").textContent = c.info.title || c.slug;
  $("#subtitle").textContent = [c.info.artist, c.info.date, c.info.venue, c.info.city].filter(Boolean).join(" · ");
  const count = (k) => c.songs.filter((s) => s.review === k).length;
  const card = h("div", { class: "card" },
    h("div", { class: "card-head" },
      h("div", { class: "card-title" }, `歌单 ${c.songs.length} 首`, h("small", {}, `整场 ${hms(c.info.duration)}`)),
      h("div", { class: "chips" },
        ...Object.entries(REVIEW).map(([k, [l, cl]]) => h("span", { class: `chip ${cl}` }, `${l} ${count(k)}`))),
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
  $("#title").textContent = `${s.idx}. ${s.title}`;
  $("#subtitle").textContent = [s.artist, s.notes].filter(Boolean).join(" · ");
  const head = h("div", { class: "card-head" },
    h("div", { class: "card-title" }, s.title, h("small", {}, `${hms(s.start)} – ${hms(s.end)}（${fmt(s.end - s.start)}）`)),
    h("div", { class: "chips" }, ...chipsFor(s)),
    h("div", { class: "spacer" }),
    ...(s.genius_urls || []).map((u, i) => h("a", { href: u, target: "_blank", rel: "noopener" }, s.genius_urls.length > 1 ? `歌词 ${i + 1}` : "Genius 歌词")));
  // 布局：上面 左 视频 / 右 歌词和翻译（跟着播放滚动）；下面 左 候选封面 / 右 投稿信息
  const player = await videoPane(c, s, route.at);
  const covers = coverPane(s);
  const form = formPane(c, s, covers, head);
  // 歌词栏：v2 / v1（实验）/ v0（原流程）切换，视频上的字幕和表格一起换
  const lyricsPane = h("div", { class: "pane lyrics-pane" });
  const exps = s.exps || {};
  const modes = [...["v2", "v1"].filter((k) => exps[k]), "v0"];
  const showLines = async (mode) => {
    const table = mode === "v0" ? linesTable(s, player.video, player.offset) : expTable(s, exps[mode], mode, player.video, player.offset);
    if (player.setAss) await player.setAss(mode === "v0" ? s.ass : exps[mode].ass);
    lyricsPane.replaceChildren(...(modes.length > 1 ? [modeSwitch] : []), table);
    modeSwitch.querySelectorAll("button").forEach((b) => b.classList.toggle("on", b.dataset.m === mode));
  };
  const LABEL = { v2: "v2（新实验）", v1: "v1", v0: "v0（原流程）" };
  const modeSwitch = h("div", { class: "seg mode-switch" }, ...modes.map((m) =>
    h("button", { "data-m": m, onclick: () => showLines(m) }, LABEL[m])));
  await showLines(modes[0]);   // 默认看最新的实验，其他的点了才切过去
  const card = h("div", { class: "card" }, head,
    h("div", { class: "top" }, player.el, lyricsPane),
    h("div", { class: "bottom" }, covers.el, form));
  $("#view").replaceChildren(card);
  if (s.job && s.job.running) pollJob(c, s, card.querySelector(".notice"));
}

function coverPane(s) {
  const entry = s.review_entry || {};
  const st = { chosen: entry.cover || null, ratio: "169" };
  const box = h("div", { class: "covers" });
  const draw = () => {
    box.className = `covers${st.ratio === "43" ? " r43" : ""}`;
    box.replaceChildren(...(s.covers.length ? s.covers.map((x) => {
      const src = st.ratio === "43" && x.file_4x3 ? x.file_4x3 : x.file;
      return h("button", {
        class: `cover${x.id === st.chosen ? " on" : ""}`, title: `${x.id}（双击看大图）`,
        onclick: () => { st.chosen = x.id; draw(); },
        ondblclick: () => window.open(src, "_blank"),
      }, h("img", { src, loading: "lazy" }),
      x.t != null ? h("span", { class: "ct" }, `${SHOT[x.id.split("_")[0]] || ""} ${hms(x.t)}`.trim()) : null,
      x.id === st.chosen ? h("span", { class: "pick" }, "已选") : null);
    }) : [h("div", { class: "placeholder" }, "还没有候选封面（package 阶段）")]));
  };
  draw();
  const sw = h("div", { class: "seg" }, ...[["169", "16:9"], ["43", "4:3"]].map(([k, l]) =>
    h("button", { class: k === st.ratio ? "on" : null, "data-k": k, onclick: () => {
      st.ratio = k; draw();
      sw.querySelectorAll("button").forEach((b) => b.classList.toggle("on", b.dataset.k === k));
    } }, l)));
  return { el: h("div", { class: "pane" }, h("div", { class: "section-label" }, "候选封面（点选一张）", sw), box), state: st };
}

function formPane(c, s, covers, head) {
  const entry = s.review_entry || {};
  const draft = s.draft || {};
  const title = h("input", { value: entry.title ?? draft.title ?? "" });
  const cnt = h("span", { class: "cnt" });
  const upd = () => { cnt.textContent = `${title.value.length}/${TITLE_MAX}`; cnt.classList.toggle("over", title.value.length > TITLE_MAX); };
  title.addEventListener("input", upd);
  upd();
  const d = draft.intro || {};
  const oldIntro = [entry.intro_song, entry.intro_performance].filter(Boolean).join("\n\n");
  const intro = h("textarea", { rows: 14 },
    entry.intro ?? (oldIntro || draft.intro_text || [d.song, d.performance].filter(Boolean).join("\n\n")));
  const tags = tagEditor(entry.tags ?? draft.tags ?? []);
  const note = h("input", { value: entry.note || "" });
  const msg = h("span", { class: "hint" }, entry.updated_at ? `上次保存 ${entry.updated_at}` : "");
  const save = async (status) => {
    try {
      const r = await api(`/api/concerts/${c.slug}/songs/${s.name}/review`, {
        status, cover: covers.state.chosen, title: title.value.trim(), intro: intro.value.trim(),
        note: note.value.trim(), tags: tags.values(),
      });
      msg.textContent = `已保存 ${r.entry.updated_at}${status === "approved" ? " · 已通过" : status === "rejected" ? " · 已打回" : ""}`;
      await refreshConcert();
      head.querySelector(".chips").replaceChildren(...chipsFor({ ...s, review: r.review }));
    } catch (err) { msg.textContent = `保存失败：${err.message}`; }
  };
  return h("div", { class: "form" },
    h("div", { class: "section-label" }, "投稿信息"),
    h("label", {}, h("span", {}, "投稿标题 ", cnt), title),
    h("label", {}, "简介（歌曲介绍 + 演出介绍）", intro),
    h("div", { class: "field" }, h("span", {}, "标签"), tags.el),
    h("div", { class: "actions" },
      h("label", { class: "grow" }, "备注（打回原因等）", note),
      h("button", { class: "btn", onclick: () => save(undefined) }, "保存"),
      h("button", { class: "btn ok", onclick: () => save("approved") }, "通过"),
      h("button", { class: "btn bad", onclick: () => save("rejected") }, "打回"),
      msg));
}

// 标签：一个个 tag 显示，× 删除；输入框里回车 / 逗号添加
function tagEditor(init) {
  let list = [...new Set(init.map((x) => String(x).trim()).filter(Boolean))];
  const input = h("input", { class: "tag-input", placeholder: "添加标签，回车" });
  const box = h("div", { class: "tags", onclick: () => input.focus() });
  const draw = () => box.replaceChildren(...list.map((t) => h("span", { class: "tag" }, t,
    h("button", { class: "x", title: "删除", onclick: (e) => { e.stopPropagation(); list = list.filter((x) => x !== t); draw(); } }, "×"))), input);
  const add = () => {
    for (const t of input.value.split(/[,，、]+/).map((x) => x.trim()).filter(Boolean)) if (!list.includes(t)) list.push(t);
    input.value = "";
    draw();
    input.focus();
  };
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === "," || e.key === "，") { e.preventDefault(); add(); }
    else if (e.key === "Backspace" && !input.value && list.length) { list.pop(); draw(); input.focus(); }
  });
  input.addEventListener("blur", () => { if (input.value.trim()) add(); });
  draw();
  return { el: box, values: () => [...list] };
}

async function videoPane(c, s, at) {
  if (!s.preview || !s.preview_span) {
    const el = h("div", { class: "pane" }, h("div", { class: "placeholder" }, "还没有预览视频（preview 阶段）"));
    return { el, video: null, offset: 0, setAss: null };
  }
  // 预览视频 = 整场 [clip0, clip1]（歌的前后各多留 10s）；整场时间 = clip0 + 播放时间
  const [clip0, clip1] = s.preview_span;
  const now = () => clip0 + video.currentTime;
  const seekAbs = (t) => { video.currentTime = Math.max(0, Math.min(clip1 - clip0, t - clip0)); };
  const subOffset = (s.slice ? s.slice[0] : s.start) - clip0;   // 字幕时间 0 = 切音频时的片段起点
  const edges = { start: s.start, end: s.end };
  const video = h("video", { src: s.preview, controls: true, preload: "auto", playsinline: true,
    controlslist: "nofullscreen", disablepictureinpicture: true });
  const stage = h("div", { class: "stage" }, video);
  video.addEventListener("loadedmetadata", () => seekAbs(at != null ? (s.slice ? s.slice[0] : s.start) + at : edges.start), { once: true });
  video.addEventListener("dblclick", () => toggleFullscreen(stage));
  state.video = video;

  let overlay = null;
  if (s.ass) {
    overlay = new SubOverlay(stage, video, parseAss(await (await fetch(s.ass)).text()), subOffset);
    overlay.tick();   // 视频可能已经跳到位（暂停时不会再有 timeupdate），立即画一次
  }
  const subSwitch = h("div", { class: "seg" }, ...[["both", "双语"], ["off", "关"]].map(([m, label]) =>
    h("button", { "data-m": m, class: m === "both" ? "on" : null, onclick: () => {
      overlay && overlay.setMode(m);
      subSwitch.querySelectorAll("button").forEach((b) => b.classList.toggle("on", b.dataset.m === m));
    } }, label)));

  // 整体提前量：字幕文件里已经统一提前 BAKED_LEAD；切换时整体往后 / 往前挪，播放中立即生效，只影响预览
  const BAKED_LEAD = 0.2;
  let lead = BAKED_LEAD;
  const LEADS = [[0.2, "提前 0.2s"], [0.4, "0.4s"], [0.6, "0.6s"], [0.8, "0.8s"], [0, "不提前"]];
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
    stage,
    h("div", { class: "toolbar tight" },
      leadSwitch,
      h("div", { class: "spacer" }),
      subSwitch,
      h("button", { class: "btn", onclick: () => toggleFullscreen(stage) }, "⛶")));
  // 换一份字幕（原流程 / 新流程）
  const setAss = async (url) => {
    if (!url) { if (overlay) { overlay.setAss({ ...overlay.ass, events: [] }); overlay.tick(); } return; }
    const ass = parseAss(await (await fetch(url, { cache: "no-store" })).text());
    if (overlay) overlay.setAss(ass);
    else overlay = new SubOverlay(stage, video, ass, subOffset);
    applyLead();
  };
  return { el, video, offset: subOffset, setAss };
}

// 实验（v1 / v2）的逐句表格；每行时间怎么定的（几个来源投票）在「判定」的鼠标悬停说明里
const VERDICT = { ok: ["✓", "ok"], warn: ["黄", "warn"], bad: ["红", "bad"], miss: ["漏", "bad"], title: ["", ""],
  unconfirmed: ["未确认", "bad"], patch: ["补", "warn"] };
const LANG = { en: "英", es: "西", it: "意", pt: "葡", fr: "法", ja: "日", zh: "中", ko: "韩" };
const langTd = (r) => h("td", { class: "lang", title: r.lang || "" }, LANG[r.lang] || r.lang || "");
function expTable(s, x, ver, video, offset) {
  const data = x.rows;
  const M = x.models || { asr: "qwen-audio-3.1-asr-flash" };
  const rows = data.map((r) => h("tr", {
    class: [r.removed ? "removed" : "", r.speech ? "speech" : "", `v-${r.verdict}`].join(" ").trim(),
    onclick: () => { if (video && r.start_ms != null) { video.currentTime = offset + r.start; video.play(); } },
  },
  h("td", { class: "t" }, r.start_ms != null ? fmtMs(r.start_ms) : "–"),
  langTd(r),
  h("td", { class: "g" }, r.genius || (r.verdict === "title" || r.speech ? "" : h("span", { class: "none" }, "（Genius 没有）"))),
  h("td", { class: "heard" }, r.verdict === "title" ? h("span", { class: "none" }, r.strategy) : r.qwen || ""),
  h("td", { class: "o" }, r.text || h("span", { class: "none" }, "（没有字幕）")),
  h("td", { class: `vd ${VERDICT[r.verdict] ? VERDICT[r.verdict][1] : ""}`, title: r.strategy },
    r.speech && r.verdict !== "title" ? "讲话" : (VERDICT[r.verdict] || [""])[0]),
  h("td", { class: "zh" }, r.zh || "")));
  const wrap = h("div", { class: "table-wrap" }, h("table", { class: "lines-table exp-table" },
    h("thead", {}, h("tr", {}, h("th", {}, "时间"), h("th", {}, "语言"), h("th", {}, "Genius 原句"), h("th", {}, M.asr),
      h("th", {}, "校准字幕"), h("th", {}, "判定"), h("th", {}, "中文"))),
    h("tbody", {}, ...rows)));
  if (video) {
    let last = -1;
    video.addEventListener("timeupdate", () => {
      if (!wrap.isConnected) return;
      const t = video.currentTime - offset;
      const i = data.findIndex((r) => !r.removed && t >= r.start && t < r.end);
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
  const bits = [`${data.filter((r) => !r.removed && r.verdict !== "title").length} 行`,
    p ? `语言 ${(p.langs || [p.main]).map((l) => LANG[l] || l).join(" / ")}${p.mismatch ? `（识别出来是${LANG[p.heard_main] || p.heard_main}）` : ""}` : "",
    n("warn") && `黄 ${n("warn")}`, n("bad") && `红 ${n("bad")}`, n("patch") && `补 ${n("patch")}`,
    data.filter((r) => r.speech).length && `讲话 ${data.filter((r) => r.speech).length}`,
    n("miss") && `漏 ${n("miss")}`, n("unconfirmed") && `未确认 ${n("unconfirmed")}`].filter(Boolean);
  return h("details", { class: "lines", open: true }, h("summary", {}, bits.join(" · ")), wrap);
}

const fmtMs = (ms) => `${Math.floor(ms / 60000)}:${String(Math.floor(ms / 1000) % 60).padStart(2, "0")}.${String(ms % 1000).padStart(3, "0")}`;

// 逐句表格：毫秒时间 / Genius 原句 / Qwen 复核听到 / 校准字幕（最终版本）/ 校准策略（哪一步来的、被哪些步骤改过）/ 中文
function linesTable(s, video, offset) {
  const legacy = !(s.rows && s.rows.length);   // 还没有逐句来历（老数据，或者正在重跑精校）
  const data = !legacy ? s.rows : s.lines.map((ln) => ({
    start_ms: Math.round(ln.start * 1000), end_ms: Math.round(ln.end * 1000), start: ln.start, end: ln.end,
    genius: null, heard: ln.heard || "", text: ln.orig, strategy: "", zh: ln.zh, removed: false, suspect: ln.suspect,
    speech: ln.style !== "Default",
  }));
  if (!data.length) return h("div", { class: "empty" }, "还没有字幕（refine 阶段）");
  const rows = data.map((r) => h("tr", {
    class: [r.speech ? "speech" : "", r.suspect != null ? "mismatch" : "", r.removed ? "removed" : ""].join(" ").trim() || null,
    onclick: () => { if (video) { video.currentTime = offset + r.start; video.play(); } },
  },
  h("td", { class: "t" }, fmtMs(r.start_ms)),
  langTd(r),
  h("td", { class: "g" }, r.genius || (r.genius === null || r.speech || r.strategy === "片头歌名" ? "" : h("span", { class: "none" }, "（Genius 没有）"))),
  h("td", { class: "heard" }, r.heard || ""),
  h("td", { class: "o" }, r.removed ? h("span", { class: "gone" }, r.was || "") : r.text,
    r.suspect != null ? h("span", { class: "sus", title: "逐句 Qwen 复核：听到的和这句不太像（匹配分）" }, ` 可疑 ${r.suspect}`) : null),
  h("td", { class: "st" }, r.strategy || ""),
  h("td", { class: "zh" }, r.zh || "")));
  const wrap = h("div", { class: "table-wrap" }, h("table", { class: "lines-table" },
    h("thead", {}, h("tr", {}, h("th", {}, "时间"), h("th", {}, "语言"), h("th", {}, "Genius 原句"), h("th", {}, "Qwen 复核听到"),
      h("th", {}, "校准字幕"), h("th", {}, "校准策略"), h("th", {}, "中文"))),
    h("tbody", {}, ...rows)));
  if (video) {
    let last = -1;
    video.addEventListener("timeupdate", () => {
      if (!wrap.isConnected) return;
      const t = video.currentTime - offset;
      const i = data.findIndex((r) => !r.removed && t >= r.start && t < r.end);
      if (i === last) return;
      if (last >= 0) rows[last].classList.remove("now");
      last = i;
      if (i >= 0) {
        rows[i].classList.add("now");
        wrap.scrollTo({ top: rows[i].offsetTop - wrap.clientHeight / 2, behavior: "smooth" });
      }
    });
  }
  const shown = data.filter((r) => !r.removed).length;
  const gone = data.length - shown;
  const nBad = data.filter((r) => r.suspect != null).length;
  return h("details", { class: "lines", open: true },
    h("summary", {}, `逐句字幕 ${shown} 条`, gone ? ` · 去掉 ${gone} 条（灰色）` : "", nBad ? ` · ${nBad} 条可疑（红色）` : ""),
    legacy ? h("div", { class: "notice" }, "这首还没生成逐句来历（可能正在重跑精校），Genius 原句和校准策略暂时空着，跑完刷新") : null,
    wrap);
}

async function rerun(c, s, notice) {
  try {
    await api(`/api/concerts/${c.slug}/songs/${s.name}/rerun`, {});
    pollJob(c, s, notice);
  } catch (err) { alert(`重跑失败：${err.message}`); }
}

function pollJob(c, s, notice) {
  const label = notice ? notice.querySelector(".job") : null;
  const timer = setInterval(async () => {
    const x = await api(`/api/concerts/${c.slug}/songs/${s.name}`);
    if (label && x.job) label.textContent = x.job.running ? `精校中（${x.job.started} 开始）…` : `结束（exit ${x.job.exit}）`;
    if (!x.job || !x.job.running) { clearInterval(timer); await refreshConcert(); render(); }
  }, 5000);
  state.cleanup.push(() => clearInterval(timer));
}

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

// 侧边栏：默认收起，状态记在本机
function setCollapsed(v) {
  $("#app").classList.toggle("collapsed", v);
  try { localStorage.setItem("v2.sideCollapsed", v ? "1" : "0"); } catch (_) { /* 无痕模式等 */ }
}
let sideCollapsed = true;
try { sideCollapsed = localStorage.getItem("v2.sideCollapsed") !== "0"; } catch (_) { /* 默认收起 */ }
setCollapsed(sideCollapsed);
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
