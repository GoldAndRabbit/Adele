"""Explicit subtitle/posting diagnostics; never an implicit delivery gate."""
import hashlib
import re
import pysubs2
from workflow.live.paths import read_json, write_json
from workflow.preview import metadata
from workflow.vertical_post import posting_inputs

def subtitle_audit(c,it):
    d=c.song_dir(it)
    file=next((d/'subs'/n for n in ['lyrics_poetic.ass','lyrics_literal.ass','lyrics.ass'] if (d/'subs'/n).is_file()),None)
    if not file:return {'status':'missing','issues':['缺少双语字幕']}
    try:
        events=[e for e in pysubs2.load(file) if not e.is_comment and e.plaintext.strip()]
    except Exception as e:return {'status':'invalid','issues':[str(e)]}
    issues=[]
    if not events:issues.append('字幕为空')
    if not any(re.search('[\u3400-\u9fff]',e.plaintext) for e in events):issues.append('没有中文字幕')
    if any(e.start<0 or e.end<=e.start for e in events):issues.append('非法时间范围')
    info=read_json(d/'song.json',{})
    selection=read_json(c.dir/'vertical_source.json',{}).get('songs',{}).get(it['name'])
    span=(selection or {}).get('slice') or info.get('slice')
    if span and any(e.end>(span[1]-span[0]+1)*1000 for e in events):issues.append('字幕超出所选片段尾部')
    lines=read_json(d/'subs/lines.json',[])
    unresolved=sum(not r.get('removed') and r.get('verdict') in ['warn','bad'] for r in lines)
    return {'status':'needs_review' if issues else 'structurally_valid','issues':issues,'file':str(file),'events':len(events),'unresolved_alignment_rows':unresolved,'human_approved':False}

def prepare_metadata(c,it):
    d=c.song_dir(it);info=c.load('info') or {};draft=read_json(d/'post_draft.json',{})
    if not draft:
        # Facts only: never invent long introductions, chart history, or aliases.
        draft={'song':{'title':it['title'],'artist':it.get('artist') or info.get('artist'),'artist_zh':info.get('artist_zh')},
               'performance':{'event':info.get('title_zh') or info.get('title'),'event_en':info.get('title_en') or info.get('title_en_short'),'date':info.get('date')},
               'metadata_origin':'existing concert and setlist facts','intro':{},'tags':[]}
        write_json(d/'post_draft.json',draft)
    from workflow.song.title_translation import resolved,save
    title=resolved(d)
    if not title:
        existing=read_json(d/'subs/translation/result.json',{})
        match=re.search(r'《([^》]+)》',existing.get('title_zh',''))
        if match and re.search('[\u3400-\u9fff]',match[1]):
            title=match[1];save(d,{'title':it['title'],'title_zh':title,'artist_zh':draft['song'].get('artist_zh'),'reason':'复用已有字幕译名，不重新翻译'})
    title = title or (draft.get('song') or {}).get('title_zh')
    if title:
        draft['song']['title_zh']=title
        write_json(d/'post_draft.json',draft)
    metadata(c,it)
    bundle=read_json(d/'delivery_bundle.json');post=bundle['douyin'];issues=[]
    if not post or not post.get('title'):issues.append('抖音标题为空')
    if post.get('title_chars',0)>30:issues.append('抖音标题超长')
    if post.get('description_chars',0)>1000:issues.append('抖音描述超长')
    if not post.get('description_body'):issues.append('缺少B站简介首段')
    research = read_json(d / 'description_research.json', {}) or {}
    posting_draft, _, _ = posting_inputs(c, it, draft)
    description = posting_draft['bili_intro']
    if not 1800 <= len(description.strip()) <= 2000:
        issues.append('B站简介须为1800–2000字符的三部分正文')
    if not all((draft.get('intro') or {}).get(key) for key in ('song', 'performance', 'lyrics')):
        issues.append('B站简介缺少创作、演唱会或歌词意象部分')
    if (not research.get('sources') or not research.get('facts') or
            research.get('description_sha256') != hashlib.sha256(description.strip().encode()).hexdigest()):
        issues.append('当前投稿简介待搜索核对')
    elif research.get('issues'):
        issues.append('投稿简介与搜索来源存在待复核差异')
    if not post.get('hashtags'):issues.append('缺少抖音话题')
    if '不允许保存' not in post.get('publish_settings',''):issues.append('保存权限不符')
    if len(bundle['bilibili'].get('标题', '')) > 80:issues.append('B站标题超过80字符，保留全文待缩句')
    if not title:issues.append('中文歌名待确认')
    return {'status':'needs_review' if issues else 'ready','issues':issues,'douyin_title':post.get('title'),'bilibili_title_chars':len(bundle['bilibili'].get('标题', ''))}
