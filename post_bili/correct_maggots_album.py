"""Correct the user-reported album attribution for one explicitly bound archive."""
import argparse
import hashlib
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from post_bili.edit_description import redacted_error, sync_web
from post_bili.sync_titles import PacedSession, now
from workflow.live.paths import read_json, write_json

DIRECTORY = ROOT/'concerts/olivia_acl_lclxvyamuce/songs/04_maggots_for_brains'
FOLDER = ROOT/'posts/bili_album_correction_20261116'
ALBUM = 'you seem pretty sad for a girl so in love'
SOURCE = 'https://store.oliviarodrigo.com/products/you-seem-pretty-sad-for-a-girl-so-in-love-with-a-bonus-track-digital-album'


def corrected_body(before):
    old = '《maggots for brains》是 Olivia Rodrigo 第二张录音室专辑《GUTS》中的一首歌曲，'
    new = f'《maggots for brains》收录于 Olivia Rodrigo 的第三张录音室专辑《{ALBUM}》（2026年6月12日发行），'
    old_context = '她的首张专辑《SOUR》获得了巨大成功，而《GUTS》则进一步展现了她对青春期情感和成长困惑的深刻洞察。《maggots for brains》正是这种风格的典型代表，'
    new_context = '继《SOUR》和《GUTS》之后，她于2026年推出第三张专辑，《maggots for brains》收录其中。歌曲延续了她直白的情绪表达，'
    if before.count(old) != 1 or before.count(old_context) != 1:
        raise ValueError('原文与待纠错版本不同，不能按猜测替换')
    after = before.replace(old,new).replace(old_context,new_context)
    a,b = before.split('\n\n'),after.split('\n\n')
    assert len(a)==len(b)
    assert [i for i,(x,y) in enumerate(zip(a,b)) if x!=y]==[0,5]
    assert 1800<=len(after)<=2000
    return after


def backup(path, label):
    target=FOLDER/'local-before'/label
    target.parent.mkdir(parents=True,exist_ok=True)
    data=read_json(path,{})
    if not target.exists():
        write_json(target,data)
    return data


def sync_local(before,body,*,online_verified=False):
    d=DIRECTORY
    for path in [d/'post_draft.json',d/'post'/(d.name+'.json')]:
        if not path.exists():
            continue
        draft=backup(path,path.name)
        song=draft.setdefault('song',{})
        song.update(album=ALBUM,release_year=2026,album_release_date='2026-06-12')
        intro=draft.get('intro',{})
        old='《maggots for brains》是 Olivia Rodrigo 的一首歌曲，收录于她的第二张录音室专辑《GUTS》中。'
        new=f'《maggots for brains》收录于 Olivia Rodrigo 于2026年6月12日发行的第三张录音室专辑《{ALBUM}》。'
        if isinstance(intro,dict) and old in intro.get('song',''):
            intro['song']=intro['song'].replace(old,new)
        if 'intro_text' in draft:
            if draft['intro_text'] not in (before,body):
                raise ValueError('本地简介另有修改，不能覆盖')
            draft['intro_text']=body
        write_json(path,draft)
    review_path=d.parent.parent/'review.json'
    review=backup(review_path,'review.json')
    entry=review.setdefault('songs',{}).setdefault(d.name,{})
    if entry.get('intro') not in (None,'',before,body):
        raise ValueError('人工简介已有新修改，不能覆盖')
    entry['intro']=body
    write_json(review_path,review)
    page_path=d/'post/bili_upload.json'
    page=backup(page_path,'bili_upload.json')
    if page['简介'] not in (before,body):
        raise ValueError('投稿导出简介已有新修改')
    page['简介']=body
    write_json(page_path,page)
    bundle_path=d/'delivery_bundle.json'
    if bundle_path.exists():
        bundle=backup(bundle_path,'delivery_bundle.json')
        assert bundle['bilibili']['简介'] in (before,body)
        bundle['bilibili']['简介']=body
        write_json(bundle_path,bundle)
    write_json(d/'post/album_correction.json',{'updated_at':now(),'album':ALBUM,'album_number':3,
                                             'release_date':'2026-06-12','sources':[SOURCE],
                                             'online_bvid':'BV16CWk6jEgi',
                                             'status':'verified' if online_verified else 'local_fixed_pending_online'})


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--submit',action='store_true')
    parser.add_argument('--local-only',action='store_true')
    args=parser.parse_args()
    baseline=read_json(FOLDER/'online-before.json')
    if not baseline or baseline['archive']['bvid']!='BV16CWk6jEgi':
        raise ValueError('缺少已绑定的原始线上快照')
    before=baseline['archive']['desc']
    body=corrected_body(before)
    write_json(FOLDER/'correction-plan.json',{'bvid':'BV16CWk6jEgi','album':ALBUM,'album_number':3,
               'release_date':'2026-06-12','source':SOURCE,'before':before,'after':body,
               'changed_paragraphs':[0,5],'covers_unchanged_required':True})
    print('corrected description:',len(before),'->',len(body),'characters; only paragraphs 1 and 6',flush=True)
    if args.local_only:
        sync_local(before,body)
        print('local album facts corrected; online update still pending',flush=True)
        return
    if not args.submit:
        return
    with PacedSession(4) as http:
        result=sync_web(DIRECTORY,body,FOLDER,
                        expected_before_sha256=hashlib.sha256(before.encode()).hexdigest(),session=http)
    sync_local(before,body,online_verified=True)
    # Preserve the title-edit's historical hash while explicitly recording
    # this later, separately authorized description correction.
    proof_path=ROOT/'posts/bili_title_sync_20261116/online-title-updates/BV16CWk6jEgi.json'
    proof=read_json(proof_path)
    if proof:
        proof['authorized_description_sha256']=result['description_sha256']
        proof['authorized_description_correction']={'record':str(FOLDER/'online-description-update.json'),
                                                  'source':SOURCE,'verified_at':now()}
        write_json(proof_path,proof)
    result.update(verified_at=now(),local_synced=True,source=SOURCE)
    write_json(FOLDER/'online-description-update.json',result)
    print('album attribution corrected and verified:',result['bvid'],flush=True)


if __name__=='__main__':
    try:
        main()
    except Exception as exc:
        print(redacted_error(exc),file=sys.stderr)
        raise SystemExit(1)
