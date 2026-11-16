(() => {
  "use strict";
  const id = new URLSearchParams(location.search).get("id");
  const title = document.querySelector("#preview-title");
  const status = document.querySelector("#preview-status");
  const video = document.querySelector("#preview-video");
  const retry = document.querySelector("#preview-retry");
  let timer;
  let closed = false;
  async function prepare(start = false) {
    retry.hidden = true;
    try {
      if (!/^[\w-]{11}$/.test(id || "")) throw new Error("无效的视频链接");
      const response = await fetch(`/api/selection-downloads/${id}/preview`, {method:start ? "POST" : "GET"});
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "预览暂不可用");
      if (closed) return;
      title.textContent = `${data.artist} · ${data.title}`;
      document.title = `${data.title} · 本地预览`;
      if (data.status === "ready") {
        status.textContent = "本地预览已就绪，点击播放。";
        video.hidden = false;
        video.src = data.media_url;
        video.addEventListener("error", () => { status.textContent = "视频加载失败，请刷新页面重试。"; }, {once:true});
      } else if (data.status === "building") {
        status.textContent = "正在准备兼容浏览器的预览，首次打开需要稍等…";
        timer = setTimeout(() => prepare(), 2000);
      } else if (data.status === "not_started") {
        await prepare(true);
      } else throw new Error("预览生成失败，请重试。");
    } catch (error) {
      if (closed) return;
      status.textContent = error.message;
      retry.hidden = false;
    }
  }
  retry.addEventListener("click", () => prepare(true));
  window.addEventListener("pagehide", () => { closed = true; clearTimeout(timer); video.pause(); video.removeAttribute("src"); video.load(); });
  prepare(true);
})();
