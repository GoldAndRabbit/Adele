"""Validate the exact publication copy reviewed for a batch item."""
import hashlib
import json


def fingerprint(title, description, tags):
    fields = json.dumps([title, description, tags], ensure_ascii=False)
    return hashlib.sha256(fields.encode()).hexdigest()


def issues(fields, policy, *, require_review=True):
    title, desc, tags = fields["title"], fields["desc"], fields["tag"]
    errors = []
    if not title.strip() or len(title) > 80:
        errors.append("标题需为1–80字符，超长时按完整字段删减")
    if policy.get("title_format") == "reviewed_current":
        if require_review and policy.get("reviewed_fingerprint") != fingerprint(title, desc, tags):
            errors.append("实际投稿资料尚未通过本批内容核对")
        return errors
    event = policy.get("required_event")
    if not 1800 <= len(desc.strip()) <= 2000 or len([p for p in desc.splitlines() if p.strip()]) < 3:
        errors.append("简介需有歌曲、演出、歌词解读等段落，共 1800–2000 字")
    if len(tags) != 12 or len({t.strip().casefold() for t in tags}) != 12 or any(not t.strip() or len(t) > 20 for t in tags):
        errors.append("需有 12 个不重复且各不超过 20 字的标签")
    if "音乐分享官" not in tags or (event and event not in tags):
        errors.append("标签缺少活动或演出名称")
    if require_review and policy.get("reviewed_fingerprint") != fingerprint(title, desc, tags):
        errors.append("实际投稿资料尚未通过本批内容核对")
    return errors
