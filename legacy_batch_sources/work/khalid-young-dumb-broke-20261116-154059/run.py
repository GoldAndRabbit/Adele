"""One requested MV, using standard preparation modules; no render/upload."""
from pathlib import Path
import sys, os, subprocess, fcntl, time, hashlib, json
from datetime import datetime

ROOT = Path('/Users/gold/repos/adele')
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT/'workflow'))
from workflow.live.paths import Concert, read_json, write_json

BASE = Path(__file__).parent
NAME = 'khalid_young_dumb_broke_mv_ipfjnp1gupc'
D = ROOT/'posts'/NAME
PY = ROOT/'.venv/bin/python'

def state(stage, **extra):
    write_json(BASE/'status.json', dict(stage=stage, updated_at=datetime.now().astimezone().isoformat(),
               scope='review preparation only', human_approved=False, **extra))
    print('STAGE', stage, extra, flush=True)

def command(stage, argv):
    if (BASE/'PAUSED').exists():
        raise RuntimeError('Paused by user')
    state(stage)
    with (BASE/(stage+'.log')).open('a') as log:
        subprocess.run(list(map(str, argv)), cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)

def link(target, source):
    if target.is_symlink() and target.resolve() == source.resolve():
        return
    if target.exists() and not target.is_symlink():
        raise ValueError('Refuse to overwrite non-link '+str(target))
    target.unlink(missing_ok=True)
    target.symlink_to(source.resolve())

def main():
    assert (D/'source.mp4').is_file() and (D/'meta.json').is_file()
    if not (D/'audio.flac').is_file() or not (D/'video_1080.mp4').is_file():
        command('prepare_audio', [PY, 'workflow/make_mv.py', '--name', NAME, '--from', 'prep', '--to', 'prep'])
    state('reference_lyrics')
    from workflow.live.lyrics import fetch_part
    from workflow import llm
    import requests
    llm.load_env()
    if not (D/'lyrics.txt').is_file():
        with requests.Session() as session:
            session.headers['User-Agent']='Mozilla/5.0'
            url, plain, sections, facts = fetch_part(session, 'Young Dumb & Broke', 'Khalid')
        (D/'lyrics.txt').write_text(plain+'\n')
        (D/'lyrics_sections.txt').write_text(sections+'\n')
        (D/'lyrics_source').write_text('reference')
        write_json(D/'lyrics_reference.json',dict(url=url,facts=facts))
    research=read_json(BASE/'research-input.json')
    note=('这是Khalid的2017年官方MV，不是演唱会或现场版。歌手中文署名为哈立德，英文Khalid，不是DJ Khaled。'
          '歌曲Young Dumb & Broke，专辑American Teen；片头和MV封面场次使用专辑名。'
          '简介的第二部分写这支MV，不虚构现场、巡演或观众。只依据以下已搜索资料、视频简介及实际画面。'
          '不要增写榜单名次、销量、未列明的制作人、客串或拍摄日期；歌词解读清楚标明为文本解读。\n'
          +json.dumps(research,ensure_ascii=False))
    if not (D/'post'/f'{NAME}.json').is_file():
        command('posting_copy',[PY,'workflow/make_meta.py','--name',NAME,'--subtitle-langs','英语,中文','--note',note])
    post=read_json(D/'post'/f'{NAME}.json')
    post['song'].update(title='Young Dumb & Broke',artist='Khalid',artist_zh='哈立德',album='American Teen')
    post['performance'].update(event='Official Music Video',event_zh='官方MV',event_en='American Teen MV',date='2017-08-01')
    write_json(D/'post'/f'{NAME}.json',post)
    if not (D/'vocals.wav').is_file():
        command('vocal_separation',[ROOT/'.venv-sep/bin/python',ROOT/'workflow/separate_roformer.py',D/'audio.flac','-o',D/'vocals.wav','--device','mps'])
    if not (D/'subs/lyrics_poetic.ass').is_file():
        command('subtitles',[PY,'-m','workflow.song.run','post',NAME])
    state('review_registration')
    (D/'covers/ai').mkdir(parents=True,exist_ok=True)
    from workflow.live.singles import build
    build([NAME])
    c=Concert('singles');it=c.item(NAME);alias=c.song_dir(it)
    for filename in ['source.mp4','meta.json','audio.flac','vocals.wav','lyrics.txt','lyrics_sections.txt','lyrics_source','title_translation.json']:
        if (D/filename).exists():link(alias/filename,D/filename)
    post=read_json(D/'post'/f'{NAME}.json')
    draft=read_json(alias/'post_draft.json');draft.update(performance=post['performance'],source=post.get('source'),subtitles=post.get('subtitles'))
    write_json(alias/'post_draft.json',draft)
    song=read_json(alias/'song.json');song.update(lang='en',langs=['en'],fps=24000/1001,source_review='pending')
    write_json(alias/'song.json',song)
    from workflow.preview_batch import enable_browser
    enable_browser(c,it)
    from workflow.song.title_translation import resolved
    from workflow.bili_title import for_post
    draft=read_json(alias/'post_draft.json');draft['song']['title_zh']=resolved(alias) or post['song'].get('title_zh')
    draft['title']=for_post(alias,draft);draft['title_full']=for_post(alias,draft,limit=None)
    write_json(alias/'post_draft.json',draft)
    from post_bili.upload import description
    body=description(draft)
    audit=llm.chat_json('核对投稿简介事实，输出JSON {"issues":[具体没有依据的事实或矛盾]}。歌词解读不是史实，正常的歌词意象分析无需外部证明。不能因为用户尚未人工审核就报问题。',
                       json.dumps(dict(research=research,metadata=read_json(D/'meta.json'),description=body),ensure_ascii=False),
                       temperature=0.1,label='MV投稿资料来源核对')
    write_json(alias/'description_research.json',{**research,'description_sha256':hashlib.sha256(body.strip().encode()).hexdigest(),
               'issues':audit.get('issues',[]),'method':'model_source_check','human_approved':False})
    from workflow.subtitle_metadata_batch import prepare_metadata, subtitle_audit
    metadata=prepare_metadata(c,it)
    state('covers',metadata=metadata)
    from workflow.fibo_dual_queue import run as covers
    write_json(BASE/'cover-queue.json',[{'slug':'singles','name':NAME}])
    for attempt in range(3):
        if (BASE/'PAUSED').exists():raise RuntimeError('Paused by user')
        covers(BASE/'cover-queue.json',Path('/Users/gold/Library/Caches/adele/fibo2-edit-turbo-q4'),
               auto_review=True,reselect_rejected=True)
        current=read_json(BASE/'dual-cover-status.json',{}).get('singles/'+NAME,{})
        if current.get('status')=='released_verified':break
    from workflow.delivery_bundle import write_bundle
    write_bundle(c,it)
    metadata=prepare_metadata(c,it)
    state('prepared_for_human_review' if current.get('status')=='released_verified' else 'cover_needs_repair',
          subtitles=subtitle_audit(c,it),metadata=metadata,cover=current,
          link='http://127.0.0.1:8160/#/singles/'+NAME)

if __name__=='__main__':
    with (BASE/'pipeline.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        try:
            main()
        except Exception as exc:
            state('failed',error=str(exc))
            raise
