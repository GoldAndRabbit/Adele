// 外挂字幕（.ass）在网页上的渲染，目标是和 adele 用 ffmpeg/libass 烧出来的一模一样。（拷自 SubDub web/subs.js，
// v2 改动：Speech 等样式按 Default 的「原文 \N 中文」处理并用样式自己的颜色；SubOverlay 支持时间偏移）
// 只解析我们自己生成的 .ass（adele bzrp 样式）：PlayRes、Default 样式、Dialogue；行内只认 {\fsNN} 和 \N。
//
// 对齐 libass 的几处细节（2026-10-15 对照 libass 渲染帧逐项校准）：
//   - 字号：libass 把字体的 (winAscent + winDescent) 缩放到 \fs，而不是 em。所以 CSS font-size = fs / 比值，
//     比值按字体算：Arial Rounded MT Bold 1.157，PingFang SC（中文回退字体）1.4 —— 同字号下中文比英文小一号
//   - 画布 384x288（4:3）放到 16:9 画面上：字形按画面高度等比缩放、不横向拉伸；换行宽度按画面宽度 - 左右边距
//   - 描边：ScaledBorderAndShadow=yes，每侧 outline × 缩放；CSS stroke 居中，所以宽度给 2 倍、先描边后填充
//   - 行首的 {\fsNN} 一直作用到这条字幕结束（换行不复位）：英文长句缩字号时，下面的中文行也跟着缩
//   - 换行：WrapStyle 0 = 先贪心排，再把词往下挪到两行接近、但上行仍不比下行窄（libass wrap_lines_smart）；
//     用 canvas 量字宽自己断行，CSS 的 text-wrap: balance 会让下行更宽，和 libass 相反。行距 = fs
"use strict";

const SUB_FONTS = {
  latin: { family: '"Arial Rounded MT Bold"', ratio: 1.157 },
  cjk: { family: '"PingFang SC"', ratio: 1.4 },
};
const CJK_RUN = /([　-〿㐀-鿿＀-￯]+)/;

// &HAABBGGRR -> CSS 颜色
function assColor(c) {
  const m = /&H([0-9A-F]{2})?([0-9A-F]{2})([0-9A-F]{2})([0-9A-F]{2})/i.exec(c || "");
  return m ? `#${m[4]}${m[3]}${m[2]}` : "#fff";
}

function parseAss(text) {
  // 多样式：Default（一条里「英文 \\N 中文」，逐句模式）；EN / ZH（段落模式，中英文各自独立的事件）
  const info = { playResX: 384, playResY: 288, styles: {}, events: [] };
  const t = (x) => { const [hh, mm, ss] = x.split(":"); return +hh * 3600 + +mm * 60 + +ss; };
  for (const line of text.split(/\r?\n/)) {
    if (line.startsWith("PlayResX:")) info.playResX = +line.split(":")[1];
    else if (line.startsWith("PlayResY:")) info.playResY = +line.split(":")[1];
    else if (line.startsWith("Style:")) {
      const f = line.slice(6).split(",").map((x) => x.trim());
      info.styles[f[0]] = { size: +f[2], color: assColor(f[3]), outline: +f[16], marginL: +f[19], marginR: +f[20], marginV: +f[21] };
    } else if (line.startsWith("Dialogue:")) {
      const f = line.slice(9).split(",");
      let size = null;   // {\fs} 跨 \N 延续
      const lines = f.slice(9).join(",").split("\\N").map((l) => {
        const m = l.match(/^\s*\{\\fs(\d+)\}/);
        if (m) size = +m[1];
        return { text: l.replace(/\{[^}]*\}/g, "").trim(), size };
      });
      info.events.push({ start: t(f[1].trim()), end: t(f[2].trim()), style: f[3].trim() || "Default", lines });
    }
  }
  const d = info.styles.Default || { size: 23, outline: 1, marginL: 10, marginR: 10, marginV: 50 };
  Object.assign(info, d);
  return info;
}

class SubRenderer {
  constructor(box, ass) {
    Object.assign(this, { box, ass, mode: "both", active: [] });
    this.layers = {};
  }
  layer(style) {
    if (!this.layers[style]) {
      const el = document.createElement("div");
      el.className = "subs";
      this.box.append(el);
      this.layers[style] = el;
    }
    return this.layers[style];
  }
  setAss(ass) {
    this.ass = ass;
    Object.values(this.layers).forEach((el) => el.replaceChildren());
    this.place();
    this.render(this.active, true);
  }
  // W×H：播放区域大小；ar：画面宽高比。画面按 contain 居中显示。
  layout(W, H, ar) {
    Object.assign(this, { W, H, ar });
    this.place();
    this.render(this.active, true);
  }
  place() {
    if (!this.W) return;
    const a = this.ass, { W, H, ar } = this;
    const pw = Math.min(W, H * ar), ph = Math.min(H, W / ar);
    this.kx = pw / a.playResX;
    this.ky = ph / a.playResY;
    this.ph = ph;
    for (const [name, st] of Object.entries(a.styles)) {
      const inner = pw - (st.marginL + st.marginR) * this.kx;   // 换行宽度
      const el = this.layer(name), s = el.style;
      s.color = st.color || "#fff";
      s.width = `${inner}px`;
      s.left = `${(W - inner) / 2}px`;
      el.baseBottom = (H - ph) / 2 + st.marginV * this.ky;
      s.bottom = `${el.baseBottom}px`;
      s.setProperty("--stroke", `${2 * st.outline * this.ky}px`);
      el.maxW = inner;
    }
  }
  font(part, size) {
    const f = CJK_RUN.test(part) ? SUB_FONTS.cjk : SUB_FONTS.latin;
    return { family: f.family, px: (size * this.ky) / f.ratio };
  }
  run(text, size) {
    // 中文、英文分段，各按自己字体的比值换算字号
    return text.split(CJK_RUN).filter(Boolean).map((part) => {
      const f = this.font(part, size);
      const span = document.createElement("span");
      span.textContent = part;
      span.style.fontFamily = f.family;
      span.style.fontSize = `${f.px}px`;
      return span;
    });
  }
  width(text, size) {
    const ctx = (SubRenderer.ctx ||= document.createElement("canvas").getContext("2d"));
    return text.split(CJK_RUN).filter(Boolean).reduce((w, part) => {
      const f = this.font(part, size);
      ctx.font = `${f.px}px ${f.family}`;
      return w + ctx.measureText(part).width;
    }, 0);
  }
  wrap(text, size) {
    // 可断点：英文在空格处，中文每个字之间
    const toks = text.match(/[\u3000-\u303f\u3400-\u9fff\uff00-\uffef][，。！？、；：”’）]*|[^\s\u3000-\u303f\u3400-\u9fff\uff00-\uffef]+\s*|\s+/g) || [];
    const W = (ts) => this.width(ts.join("").trimEnd(), size);
    const lines = [[]];
    for (const tk of toks) {                       // 1. 贪心
      const cur = lines[lines.length - 1];
      if (cur.length && W([...cur, tk]) > this.maxW) lines.push([tk]);
      else cur.push(tk);
    }
    for (let i = 0; i + 1 < lines.length; i++) {  // 2. 往下挪词，直到两行接近且上行不窄于下行
      for (;;) {
        const a = lines[i], b = lines[i + 1];
        if (a.length < 2) break;
        const na = a.slice(0, -1), nb = [a[a.length - 1], ...b];
        const before = Math.abs(W(a) - W(b)), after = Math.abs(W(na) - W(nb));
        if (W(nb) > this.maxW || after >= before || W(na) < W(nb)) break;
        lines[i] = na; lines[i + 1] = nb;
      }
    }
    return lines.map((l) => l.join("").trim());
  }
  render(evs, force = false) {
    evs = evs || [];
    const key = evs.map((e) => e.start + e.style).join("|") + this.mode;
    if (!force && key === this.key) return;
    this.key = key;
    this.active = evs;
    if (!this.ky) return;
    const show = { EN: this.mode !== "zh", ZH: this.mode !== "en" };
    for (const [name, el] of Object.entries(this.layers)) {
      const st = this.ass.styles[name] || this.ass;
      const kids = [];
      if (this.mode !== "off") {
        for (const e of evs.filter((x) => x.style === name)) {
          let lines = e.lines;
          if (!(name in show)) lines = this.mode === "en" ? [lines[0]] : this.mode === "zh" ? [lines[1]] : lines;
          else if (!show[name]) lines = [];
          for (const l of lines.filter((l) => l && l.text)) {
            const size = l.size || st.size;
            this.maxW = el.maxW;
            for (const text of this.wrap(l.text, size)) {
              const div = document.createElement("div");
              div.style.lineHeight = `${size * this.ky}px`;
              div.style.fontSize = `${this.font("a", size).px}px`;   // 行的 strut 和英文同字号，否则基线对齐会把行距撑大
              div.append(...this.run(text, size));
              kids.push(div);
            }
          }
        }
      }
      el.replaceChildren(...kids);
    }
    // 同时出现的几条（标题 + 开场讲话等）像 libass 一样上下错开：先出现的贴底，后出现的往上叠，不重叠
    let lift = 0;
    for (const name of this.stackOrder(evs)) {
      const el = this.layers[name];
      el.style.bottom = `${el.baseBottom + lift}px`;
      if (el.childElementCount) lift += el.offsetHeight;
    }
  }
  stackOrder(evs) {
    const first = {};
    evs.forEach((e) => { if (!(e.style in first) || e.start < first[e.style]) first[e.style] = e.start; });
    return Object.keys(this.layers).sort((a, b) => (first[a] ?? 1e9) - (first[b] ?? 1e9));
  }
  setMode(m) { this.mode = m; this.render(this.active, true); }

}

// 跟着 <video> 走：尺寸变化重新排版，时间变化切换字幕条
class SubOverlay extends SubRenderer {
  // offset：字幕时间 0 对应视频的这一秒（整场视频上预览单曲字幕）
  constructor(box, video, ass, offset = 0) {
    super(box, ass);
    Object.assign(this, { video, offset });
    const fit = () => this.layout(video.clientWidth, video.clientHeight,
      video.videoWidth && video.videoHeight ? video.videoWidth / video.videoHeight : 16 / 9);
    new ResizeObserver(fit).observe(video);
    video.addEventListener("loadedmetadata", fit);
    const tick = () => {
      const t = video.currentTime - this.offset;
      this.render(this.ass.events.filter((x) => t >= x.start && t < x.end));
    };
    video.addEventListener("timeupdate", tick);
    video.addEventListener("seeked", tick);
    this.tick = tick;
    fit();
  }
}
