from workflow.live.paths import *
from workflow.song import watermark as wm
from workflow.letterbox import content_box,logo_corner
import subprocess,numpy as np,cv2
from unittest.mock import patch
c=Concert('an_audience_with_adele_2021')
def faces_at(video,t,offset,det):
 boxes=[]
 for dt in (.2,wm.DUR/2,wm.DUR-.2):
  cmd=['ffmpeg','-nostdin','-loglevel','error','-ss',str(offset+t+dt),'-i',str(video),'-frames:v','1','-vf','scale=640:360','-pix_fmt','bgr24','-f','rawvideo','-']
  frame=subprocess.run(cmd,capture_output=True,check=True).stdout
  assert len(frame)==640*360*3
  det.setInputSize((640,360));_,faces=det.detect(np.frombuffer(frame,np.uint8).reshape(360,640,3))
  for face in ([] if faces is None else faces):
   x,y,w,h=face[:4];boxes.append(((x-w*.5)/640,(y-h*.6)/360,(x+w*1.5)/640,(y+h*1.8)/360))
 return boxes
with patch.object(wm,'faces_at',faces_at):
 for it in c.song_items():
  d=c.song_dir(it);dest=d/'watermark.json'
  if dest.is_file():continue
  a,b=read_json(d/'song.json')['slice']
  plan=wm.plan(it['name'],b-a,c.source,a,wm.speech_spans(d),content_box(d),logo_corner(d))
  if not dest.is_file():write_json(dest,plan)
  print(it['name'],len(plan['items']),flush=True)
