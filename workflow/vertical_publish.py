"""Publish one reviewed portrait release using the local PostFlow installation."""
import asyncio
import fcntl
import json
import os
import re
import sys
import subprocess
from pathlib import Path

from workflow.live.paths import read_json
from workflow.vertical_post import cover_attachment, posting_inputs, submission
from workflow.vertical_workflow import revision


def posting_plan(concert, item):
    directory = concert.song_dir(item)
    folder = directory / "vertical"
    record = read_json(folder / "release.json", {})
    video = folder / record.get("file", "")
    if not video.is_file() or not record.get("revision") or record["revision"] != revision(directory):
        raise ValueError("缺少当前版本的竖屏成品，请先核对并生成 --release")
    cover = read_json(folder / "selected.json", {}).get("cover")
    pair = cover_attachment(directory, cover)
    if not pair or not pair.get("wide_path"):
        raise ValueError("请先在精校页选定竖封面及配套横封面")
    meta = submission(*posting_inputs(concert, item, read_json(directory / "post_draft.json", {})))
    if not meta or len(meta["description"].encode("utf-16-le")) > 2000:
        raise ValueError("请先在精校页核对抖音标题和话题")
    duration = float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                              "-of", "default=nw=1:nk=1", str(video)]))
    return dict(meta, track=item["title"], duration=duration, video=str(video.resolve()), portrait=pair["path"], landscape=pair["wide_path"],
                account=os.environ.get("DOUYIN_ACCOUNT", "goldandrabbit"))


async def set_cover(page, label, path):
    area = page.locator('div[class*="coverControl-"]').filter(has_text=label)
    # Topic suggestions can cover the cover picker while the caption still has focus.
    await page.keyboard.press("Escape")
    await page.evaluate("document.activeElement?.blur()")
    box = area.locator('div[class^="cover-"]').first
    await box.wait_for()
    await box.evaluate("el => el.click()")
    dialog = page.locator(".dy-creator-content-modal-body").last
    upload = dialog.locator(".semi-upload:has(.semi-upload-drag-area-main-text) input[type=file]").first
    await upload.set_input_files(path, timeout=30000)
    await dialog.get_by_role("button", name="完成", exact=True).click(timeout=30000)
    if label == "竖封面3:4":
        from playwright.async_api import TimeoutError as PlaywrightTimeout
        try:
            await page.get_by_role("button", name="暂不设置", exact=True).click(timeout=2500)
        except PlaywrightTimeout:
            pass
    await dialog.wait_for(state="hidden", timeout=45000)


async def account_works(ctx):
    """Read every work, including those under review. Never interpret a partial list as absence."""
    page = await ctx.new_page()
    try:
        await page.goto("https://creator.douyin.com/creator-micro/content/manage", wait_until="domcontentloaded")
        tab = page.get_by_role("button", name=re.compile(r"^作品\s*[（(]\d+[）)]$")).first
        await tab.wait_for(timeout=60000)
        total = int(re.search(r"\d+", await tab.inner_text())[0])
        cards = page.locator('div[class^="video-card-content-"]')
        while await cards.count() < total and not await page.get_by_text("没有更多作品", exact=True).is_visible():
            old = await cards.count()
            if old:
                await page.locator('[class^="list-scroll-"]').first.evaluate("el => el.scrollTop = el.scrollHeight")
            await page.wait_for_function("""n => document.querySelectorAll('div[class^="video-card-content-"]').length > n || document.body.innerText.includes("没有更多作品")""",
                                         arg=old, timeout=20000)
        return await cards.all_inner_texts()
    finally:
        await page.close()


def match_work(cards, plan):
    def normalized(text):
        return re.sub(r"[^\w]", "", text.casefold())
    for card in cards:
        lines = card.split("编辑作品")[0].strip().splitlines()
        if not lines:
            continue
        caption = normalized(" ".join(lines[1:]).split("#")[0])
        if normalized(plan["title"]) in caption:
            return True
        track = plan.get("track", "").split(" / ")[0]
        if not track or not re.search(r"(?<![a-z0-9])" + re.escape(track) + r"(?![a-z0-9])",
                                      " ".join(lines[1:]).split("#")[0], re.I):
            continue
        timing = re.fullmatch(r"(\d+):(\d{2})", lines[0])
        if timing and abs(60 * int(timing[1]) + int(timing[2]) - plan["duration"]) < 2:
            return True
        raise ValueError(f"作品管理存在同名曲目，请核对后再投稿：{lines[-1]}")
    return False


async def listed(ctx, plan):
    return match_work(await account_works(ctx), plan)


def save_receipt(path, state, plan):
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(dict(status=state, **plan), ensure_ascii=False, indent=2))
    temp.replace(path)


async def publish(plan, receipt):
    home = Path(os.environ.get("POSTFLOW_HOME", "~/.local/share/postflow-grammy")).expanduser().resolve()
    if not (home / "uploader/douyin_uploader/main.py").is_file():
        raise ValueError("找不到 PostFlow，请设置 POSTFLOW_HOME")
    sys.path[:0] = [str(home), str(home / "vendor")]
    from conf import LOCAL_CHROME_PATH
    from playwright.async_api import async_playwright
    from uploader.douyin_uploader.main import DouYinVideo

    cookie = Path(os.environ.get("DOUYIN_STORAGE_STATE",
                  f"~/.local/share/adele-sau/cookies/douyin_{plan['account']}.json")).expanduser()
    if not cookie.is_file():
        raise ValueError("请先登录抖音或设置 DOUYIN_STORAGE_STATE")

    class PortraitUploader(DouYinVideo):
        async def set_thumbnail(self, page, path):
            await set_cover(page, "竖封面3:4", path)
            await set_cover(page, "横封面4:3", plan["landscape"])

        async def set_aigc_declaration(self, page):
            # PostFlow calls this hook after its own cross-post defaults, before submission.
            for label in ("不同时发布", "不允许", "公开", "立即发布"):
                choice = page.get_by_role("checkbox", name=label, exact=True)
                if not await choice.is_checked():
                    await choice.locator("xpath=ancestor::label[1]").click()
                if not await choice.is_checked():
                    raise RuntimeError(f"发布设置未生效：{label}")
            save_receipt(receipt, "pending", plan)

    headless = os.environ.get("DOUYIN_SHOW_BROWSER") != "1"
    async with async_playwright() as runtime:
        browser = await runtime.chromium.launch(executable_path=LOCAL_CHROME_PATH or None, headless=headless)
        try:
            ctx = await browser.new_context(storage_state=str(cookie))
            page = await ctx.new_page()
            await page.goto("https://creator.douyin.com/creator-micro/home", wait_until="domcontentloaded")
            account_label = re.compile(r"抖音号[：:]\s*" + re.escape(plan["account"]) + r"(?![\w.-])")
            await page.get_by_text(account_label).first.wait_for(timeout=60000)
            prior = read_json(receipt, {})
            if prior.get("account") == plan["account"]:
                if prior["status"] == "confirmed" or await listed(ctx, {**plan, **prior}):
                    if prior["status"] != "confirmed":
                        save_receipt(receipt, "confirmed", {k: v for k, v in prior.items() if k != "status"})
                    print("已有发布回执，跳过", prior["title"])
                    return
                raise RuntimeError("上次已进入发布阶段，作品列表尚未确认。请人工核对后再重试")
            if await listed(ctx, plan):
                save_receipt(receipt, "confirmed", plan)
                print("作品管理里已有此标题，跳过")
                return
            tags = [tag.removeprefix("#") for tag in plan["description"].split()]
            tool = PortraitUploader(plan["title"], plan["video"], tags,
                                    0, str(cookie), plan["portrait"])
            tool.headless = headless
            try:
                await asyncio.wait_for(tool.upload(runtime), timeout=600)
            finally:
                if await listed(ctx, plan):
                    save_receipt(receipt, "confirmed", plan)
            if read_json(receipt, {}).get("status") != "confirmed":
                raise RuntimeError("作品管理尚无对应标题，请核对验证提示和投稿状态")
            print("作品管理已确认", plan["title"])
        finally:
            await browser.close()


def run(concert, item, submit=False):
    folder = concert.song_dir(item) / "vertical"
    if not submit:
        print(json.dumps(posting_plan(concert, item), ensure_ascii=False, indent=2))
        return
    with (folder / ".douyin.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        asyncio.run(publish(posting_plan(concert, item), folder / "douyin-receipt.json"))
