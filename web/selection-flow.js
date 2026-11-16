/* 选品流：按 YouTube Popular 原始顺序展示频道视频快照。 */
(() => {
  "use strict";
  const root = document.querySelector("#selection-flow");
  const node = (tag, className, text) => {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text != null) element.textContent = text;
    return element;
  };
  const link = (text, url) => {
    const element = node("a", "", text);
    element.href = url;
    element.target = "_blank";
    element.rel = "noopener noreferrer";
    return element;
  };
  const previewDialog = node("dialog", "selection-preview-dialog");
  previewDialog.setAttribute("aria-label", "本地视频预览");
  const previewTitle = node("h2", "", "本地视频预览");
  const closePreview = node("button", "btn mini", "关闭");
  closePreview.type = "button";
  closePreview.setAttribute("aria-label", "关闭本地预览");
  const previewHeader = node("div", "selection-preview-heading");
  previewHeader.append(previewTitle, closePreview);
  const previewStatus = node("p", "hint");
  previewStatus.setAttribute("role", "status");
  const previewVideo = node("video", "selection-preview-player");
  previewVideo.controls = true;
  previewVideo.playsInline = true;
  previewVideo.preload = "none";
  previewVideo.hidden = true;
  const retryPreview = node("button", "btn", "重试");
  retryPreview.type = "button";
  retryPreview.hidden = true;
  previewDialog.append(previewHeader, previewStatus, previewVideo, retryPreview);
  document.body.append(previewDialog);
  let previewSession = 0, previewTimer, previewRequest, previewId, previewCompatible = false, retryCompatible = false;
  function stopPreview() {
    previewSession++;
    clearTimeout(previewTimer);
    previewRequest?.abort();
    previewVideo.pause();
    previewVideo.removeAttribute("src");
    previewVideo.load();
    previewVideo.hidden = true;
  }
  async function preparePreview(id, session, start = true) {
    retryPreview.hidden = true;
    previewRequest = new AbortController();
    try {
      const response = await fetch(`/api/selection-downloads/${encodeURIComponent(id)}/preview${previewCompatible ? "?compatible=true" : ""}`, {
        method:start ? "POST" : "GET", signal:previewRequest.signal
      });
      const data = await response.json();
      if (session !== previewSession || !previewDialog.open) return;
      if (!response.ok) throw new Error(data.detail || "预览暂不可用");
      previewTitle.textContent = [data.artist, data.title].filter(Boolean).join(" · ") || "本地视频预览";
      if (data.status === "ready") {
        previewStatus.textContent = "";
        previewVideo.hidden = false;
        previewVideo.src = data.media_url;
        previewVideo.play().catch(error => {
          if (session === previewSession && error.name !== "AbortError") previewStatus.textContent = "点击视频播放按钮开始预览。";
        });
      } else if (data.status === "building") {
        previewStatus.textContent = "正在准备兼容播放版本…";
        previewTimer = setTimeout(() => preparePreview(id, session, false), 2000);
      } else throw new Error("预览准备失败，请重试。");
    } catch (error) {
      if (session !== previewSession || error.name === "AbortError") return;
      previewStatus.textContent = error.message;
      retryPreview.hidden = false;
    }
  }
  function openPreview(id, compatible = false) {
    stopPreview();
    previewCompatible = retryCompatible = compatible;
    retryPreview.textContent = "重试";
    previewId = id;
    previewTitle.textContent = "本地视频预览";
    previewStatus.textContent = "正在加载本地视频…";
    previewDialog.showModal();
    preparePreview(id, previewSession);
  }
  closePreview.addEventListener("click", () => previewDialog.close());
  previewDialog.addEventListener("close", stopPreview);
  previewDialog.addEventListener("click", event => { if (event.target === previewDialog) previewDialog.close(); });
  previewVideo.addEventListener("error", () => {
    if (!previewDialog.open || !previewVideo.hasAttribute("src")) return;
    retryCompatible = true;
    previewStatus.textContent = previewCompatible ? "视频加载失败，请重试。" : "浏览器无法直接播放这份原片，可使用兼容播放。";
    retryPreview.textContent = previewCompatible ? "重试" : "兼容播放";
    retryPreview.hidden = false;
  });
  retryPreview.addEventListener("click", () => openPreview(previewId, retryCompatible));
  new MutationObserver(() => { if (root.hidden && previewDialog.open) previewDialog.close(); }).observe(root, {attributes:true, attributeFilter:["hidden"]});
  window.addEventListener("pagehide", stopPreview);
  const formatViews = value => {
    const match = value.match(/([\d,.]+)\s*(billion|million|thousand)?\s*views?/i);
    if (!match) return value;
    const units = {billion: 1e9, million: 1e6, thousand: 1e3};
    const unit = match[2]?.toLowerCase();
    const count = Number(match[1].replaceAll(",", "")) * (units[unit] || 1);
    return (unit ? "约 " : "") + new Intl.NumberFormat("zh-CN", {notation:"compact", maximumFractionDigits:2}).format(count);
  };
  async function load() {
    root.replaceChildren(node("div", "empty", "正在加载选品资料…"));
    try {
      const response = await fetch("selection-library.json");
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      let downloads = {}, publishedDates = {};
      async function refreshDownloads() {
        try {
          const [response, dates] = await Promise.all([
            fetch("/api/selection-downloads"),
            fetch("selection-dates.json", {cache:"no-cache"}).then(r => r.ok ? r.json() : null).catch(() => null)
          ]);
          publishedDates = dates?.videos || {};
          if (!response.ok) throw new Error();
          downloads = (await response.json()).videos;
          for (const cell of main.querySelectorAll("[data-download-id]")) renderDownload(cell);
        } catch {
          for (const cell of main.querySelectorAll("[data-download-id]")) {
            cell.textContent = "—";
            const status = cell.closest("tr")?.querySelector(".selection-download-status");
            if (status) { status.textContent = "状态暂不可用"; status.className = "selection-download-status"; }
          }
        }
      }
      function renderDownload(cell) {
        const row = downloads[cell.dataset.downloadId];
        const tr = cell.closest("tr");
        if (tr) {
          tr.querySelector(".selection-published-date").textContent = publishedDates[cell.dataset.downloadId]?.date || "—";
          const status = tr.querySelector(".selection-download-status");
          const labels = {completed:"已下载", downloading:"下载中", failed:"下载失败"};
          status.textContent = labels[row?.status] || "待下载";
          status.className = "selection-download-status " + (labels[row?.status] ? "download-" + row.status : "download-pending");
          tr.querySelector(".selection-fps").textContent = row?.fps > 0 ? row.fps + " fps" : "—";
          tr.querySelector(".selection-resolution").textContent = row?.resolution || "—";
        }
        if (row?.status === "completed") {
          const play = node("button", "btn mini selection-play", "▶ 播放");
          play.type = "button";
          play.setAttribute("aria-label", "播放本地视频");
          play.addEventListener("click", () => openPreview(cell.dataset.downloadId));
          cell.replaceChildren(play);
        }
        else cell.textContent = "—";
      }
      const sidebar = node("aside", "selection-sidebar");
      sidebar.setAttribute("aria-label", "选品歌手");
      sidebar.append(node("div", "selection-sidebar-title", "歌手"));
      const nav = node("nav", "selection-artists");
      nav.setAttribute("aria-label", "选择歌手");
      sidebar.append(nav);
      const main = node("div", "selection-main");
      const buttons = [];
      function select(artist) {
        if (previewDialog.open) previewDialog.close();
        for (const {button, id} of buttons) {
          if (id === artist.id) button.setAttribute("aria-current", "true");
          else button.removeAttribute("aria-current");
        }
        const header = node("div", "selection-heading");
        const title = node("div");
        title.append(node("h1", "", artist.name), node("p", "hint", `Popular 前 ${artist.popular_limit} 条 筛选 · 保留 ${artist.videos.length} 首歌曲 · 更新于 ${data.fetched_date}`));
        header.append(title, link("YouTube 频道 ↗", artist.channel_url));
        const table = node("table", "selection-table");
        const caption = node("caption", "sr-only", `${artist.name} Popular 前 ${artist.popular_limit} 条中的歌曲视频`);
        const thead = node("thead");
        const headings = node("tr");
        for (const label of ["排名", "本地视频", "下载状态", "歌名", "YouTube 发布时间", "YouTube 原始链接", "视频时长", "分辨率", "帧率", "播放量", "是否为歌曲"]) {
          const th = node("th", "", label);
          th.scope = "col";
          headings.append(th);
        }
        thead.append(headings);
        const tbody = node("tbody");
        for (const video of artist.videos) {
          const tr = node("tr");
          const url = node("td", "selection-url");
          url.append(link(video.url, video.url));
          const preview = node("td", "selection-preview-link");
          preview.dataset.downloadId = video.video_id;
          tr.append(node("td", "selection-rank", String(video.rank).padStart(2, "0")), preview, node("td", "selection-download-status", "待下载"),
            node("td", "selection-song", video.title), node("td", "selection-published-date", publishedDates[video.video_id]?.date || "—"), url, node("td", "selection-duration", video.duration),
            node("td", "selection-resolution", "—"), node("td", "selection-fps", "—"),
            node("td", "selection-views", formatViews(video.views)), node("td", "selection-is-song", "是"));
          renderDownload(preview);
          tbody.append(tr);
        }
        table.append(caption, thead, tbody);
        const wrap = node("div", "selection-table-wrap");
        wrap.append(table);
        const note = node("p", "hint selection-note", "保留 YouTube Popular 原始排名；仅保留至少 2 分钟的歌曲视频，Lyric Video、纯 Audio、采访、幕后花絮等不列入。播放量按频道显示值记录。");
        if (artist.excluded_videos.length) note.textContent += ` 本频道已排除 ${artist.excluded_videos.length} 条不符合条件的视频。`;
        main.replaceChildren(header, wrap, note);
      }
      for (const artist of data.artists) {
        const button = node("button", "selection-artist");
        button.type = "button";
        button.append(node("span", "", artist.name), node("small", "", String(artist.videos.length)));
        button.addEventListener("click", () => select(artist));
        buttons.push({button, id: artist.id});
        nav.append(button);
      }
      root.replaceChildren(sidebar, main);
      select(data.artists[0]);
      refreshDownloads();
      document.querySelector("#selection-tab").addEventListener("click", refreshDownloads);
      setInterval(() => { if (!root.hidden && !document.hidden) refreshDownloads(); }, 30000);
    } catch (error) {
      const retry = node("button", "btn", "重新加载");
      retry.type = "button";
      retry.addEventListener("click", load);
      const message = node("div", "empty", `选品资料加载失败：${error.message} `);
      message.append(retry);
      root.replaceChildren(message);
    }
  }
  load();
})();
