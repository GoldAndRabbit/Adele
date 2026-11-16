import os,signal,shutil
from pathlib import Path
from workflow.live.paths import Concert,read_json,write_json
c=Concert('grammys_2014');oldnames={'03_invisible','17_one','09_try_just_give_me_a_reason'}
policy=read_json(c.dir/'vertical_source.json');oldsource=str(c.source.resolve());backup=Path('work/grammy-source-policy/before')
backup.mkdir(parents=True,exist_ok=True)
for f in ['vertical_source.json','segments.json','browser_previews.json']:
 if not (backup/f).exists():shutil.copy2(c.dir/f,backup/f)
# Superseded paused workers must not later overwrite the selected 720p timelines.
for pg in [28934,30330,31723]:
 try:os.killpg(pg,signal.SIGKILL)
 except ProcessLookupError:pass
segments=read_json(c.segments)
for it in c.song_items():
 n=it['name'];d=c.song_dir(it);save=backup/n;save.mkdir(exist_ok=True)
 if not (save/'song.json').exists():shutil.copy2(d/'song.json',save/'song.json')
 sel=policy['songs'][n];info=read_json(d/'song.json')
 if n in oldnames:
  original=Path('work/grammy-ts-review/original-metadata')/n
  if not (save/'subs').exists():shutil.copytree(d/'subs',save/'subs')
  for f in ['song.json','watermark.json','content_box.json']:
   if (d/f).exists() and not (save/f).exists():shutil.copy2(d/f,save/f)
   shutil.copy2(original/f,d/f)
  shutil.copytree(original/'subs',d/'subs',dirs_exist_ok=True)
  # Remove TS-only ASR artifacts by preserving the whole migrated folder separately.
  oldfiles={str(f.relative_to(original/'subs')) for f in (original/'subs').rglob('*') if f.is_file()}
  for f in (d/'subs').rglob('*'):
   if f.is_file() and str(f.relative_to(d/'subs')) not in oldfiles:f.unlink()
  for f in ['audio.flac','vocals.wav']:
   if (d/f).exists():
    if not (save/f).exists():shutil.move(d/f,save/f)
    else:(d/f).unlink()
   (d/f).symlink_to((original/f).resolve())
  info=read_json(d/'song.json');sel.update(source=oldsource,kind='720p',slice=info['slice'],fps=29.97002997,
   directory=str(Path('/Volumes/harddisk_5T/adele-workflow/vertical-reviews/grammys_2014/720-reviews')/n))
  ready=(d/'vertical/original-720.mp4').resolve();target=Path(sel['directory']);target.mkdir(parents=True,exist_ok=True)
  out=target/'source.mp4'
  if not out.exists():out.symlink_to(ready)
  write_json(target/'source.json',{'source':oldsource,'mtime':Path(oldsource).stat().st_mtime_ns,'slice':sel['slice']})
  (d/'preview.mp4').unlink(missing_ok=True);(d/'preview.mp4').symlink_to(ready)
  info['preview']=sel['slice']
 else:
  sel.update(source=policy['source'],kind='ts',fps=50)
  # Existing subtitle clocks match these TS bounds, except Chicago already remapped.
  if n!='05_does_anybody_really_know_what_ti':
   # Stale old-source audio is not an input for future TS refinement.
   for f in ['audio.flac','vocals.wav']:
    if (d/f).exists() and not (save/f).exists():shutil.move(d/f,save/f)
  info['slice']=sel['slice']
 info.update(source_file=sel['source'],source_kind=sel['kind'],preview_mode='browser',
  source_review='pending',source_note=('720p 原片' if n in oldnames else 'TS 原片')+' · 实时竖屏预览',
  vertical_preview_fps=30 if n in oldnames else 50)
 write_json(d/'song.json',info)
 for segment in segments['items']:
  if segment['name']==n:
   segment.update(start=sel['slice'][0],end=sel['slice'][1],source_file=sel['source'])
write_json(c.dir/'vertical_source.json',policy);write_json(c.segments,segments)
write_json(c.dir/'browser_previews.json',{'songs':[it['name'] for it in c.song_items()]})
print('Configured',len(c.song_items()),'songs; 720p:',sorted(oldnames))
