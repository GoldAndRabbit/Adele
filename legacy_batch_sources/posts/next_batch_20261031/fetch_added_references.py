from pathlib import Path
import sys,json,os,requests,re,hashlib,concurrent.futures,unicodedata,time,fcntl
R=Path('/Users/gold/repos/adele');sys.path[:0]=[str(R),str(R/'workflow')]
B=Path(__file__).parent
lock=(B/'reference.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
from bs4 import BeautifulSoup
sets={
'yw7hhsr5uyy':('XLVII','Beyonce','Run the World (Girls)|Love on Top|Crazy in Love|End of Time|Baby Boy|Bootylicious@Destinys Child|Independent Women Part I@Destinys Child|Single Ladies (Put a Ring on It)|Halo'),
'hckfn9jkrr0':('LVI','Dr. Dre','The Next Episode|California Love@2Pac|In da Club@50 Cent|Family Affair@Mary J. Blige|No More Drama@Mary J. Blige|m.A.A.d city@Kendrick Lamar|Alright@Kendrick Lamar|Forgot About Dre|Lose Yourself@Eminem|Still D.R.E.'),
'kdorky_13ak':('LIX','Kendrick Lamar','Bodies|Wacced Out Murals|Squabble Up|Humble|DNA|Euphoria|Man at the Garden|Peekaboo|Luther|All the Stars|Not Like Us|TV Off'),
'g6fuwd4wnd8':('LX','Bad Bunny',"Titi Me Pregunto|Yo Perreo Sola|Safaera|Party|Voy a Llevarte Pa PR|Eoo|Monaco|Die With a Smile@Lady Gaga|Baile Inolvidable|Nuevayol|Lo Que Le Paso a Hawaii|El Apagon|Cafe Con Ron|DTMF"),
'hjbo__1n8li':('LVII','Rihanna','Bitch Better Have My Money|Phresh Out the Runway|Where Have You Been|Only Girl (In the World)|Cockiness (Love It)|We Found Love|S&M|Rude Boy|Kiss It Better|Work|Wild Thoughts@DJ Khaled|Pour It Up|Birthday Cake|Numb|Pose|All of the Lights@Kanye West|Run This Town@Jay-Z|Umbrella|Diamonds'),
'pilcn6vo_ru':('LIV','Shakira',"She Wolf|Dare (La La La)|Empire|Inevitable|Ojos Asi|Whenever Wherever|I Like It@Cardi B|Chantaje|Callaita@Bad Bunny|Hips Dont Lie|We Will Rock You@Queen|Jenny from the Block@Jennifer Lopez|Aint It Funny@Jennifer Lopez|Get Right@Jennifer Lopez|Waiting For Tonight@Jennifer Lopez|Que Calor@Major Lazer|Booty@Jennifer Lopez|El Anillo@Jennifer Lopez|Mi Gente@J Balvin|On the Floor@Jennifer Lopez|Lets Get Loud@Jennifer Lopez|Born in the USA@Bruce Springsteen|Waka Waka (This Time for Africa)"),
'mjrdywp5nye':('LI','Lady Gaga','God Bless America@Irving Berlin|This Land Is Your Land@Woody Guthrie|The Edge of Glory|Poker Face|Born This Way|Telephone|Just Dance|Million Reasons|Bad Romance')}
sets['gdsukphmb3y']=sets['hckfn9jkrr0']
sets={'2z3euy1axdy':('LII','Justin Timberlake',"Filthy|Rock Your Body|SexyBack|My Love|Cry Me a River|Suit & Tie|Until the End of Time|I Would Die 4 U@Prince|Mirrors|Can't Stop the Feeling!"),'jn2kgdpozz4':('XLVIII','Bruno Mars','Billionaire@Travie McCoy|Locked Out of Heaven|Treasure|Runaway Baby|Give It Away@Red Hot Chili Peppers|Just the Way You Are')}
cache=B/'reference_cache';cache.mkdir(exist_ok=True)
def slug(s):return re.sub('[^a-z0-9]','',unicodedata.normalize('NFKD',s).encode('ascii','ignore').decode().lower())
def fetch(pair):
 artist,title=pair;key=hashlib.sha256((artist+'|'+title).encode()).hexdigest()[:16];p=cache/(key+'.json')
 if p.exists():return json.loads(p.read_text())
 errors=[];lyrics=None;url=None
 u='https://api.lyrics.ovh/v1/'+requests.utils.quote(artist,safe='')+'/'+requests.utils.quote(title,safe='')
 try:
  r=requests.get(u,timeout=20);r.raise_for_status();lyrics=r.json().get('lyrics','').strip();url=u
  lyrics=re.sub(r'^Paroles de la chanson[^\n]*\n','',lyrics)
 except Exception as e:errors.append('lyrics.ovh: '+type(e).__name__)
 if not lyrics or len(lyrics)<100:
  a=slug(artist);a={'beyonce':'beyonceknowles','destinyschild':'destinyschild'}.get(a,a)
  u=f'https://www.azlyrics.com/lyrics/{a}/{slug(title)}.html'
  try:
   r=requests.get(u,timeout=20);r.raise_for_status();soup=BeautifulSoup(r.text,'html.parser');div=soup.select_one('.col-xs-12.col-lg-8.text-center')
   candidates=[x.get_text('\n',strip=True) for x in div.find_all('div',recursive=False) if not x.get('class')] if div else []
   lyrics=max(candidates,key=len) if candidates else '';assert len(lyrics)>100;url=u
  except Exception as e:errors.append('AZLyrics: '+type(e).__name__);lyrics=None
 result={'artist':artist,'title':title,'url':url,'lyrics':lyrics,'errors':errors}
 if lyrics:p.write_text(json.dumps(result,ensure_ascii=False,indent=2))
 return result
state=json.loads((B/'reference_status.json').read_text());state.update(pid=os.getpid(),status='running')
def save():state['at']=time.time();(B/'reference_status.json').write_text(json.dumps(state,ensure_ascii=False,indent=2)+'\n')
for short,(roman,artist,titles) in sets.items():
 n='next_20261031_'+short;d=R/'posts'/n
 pairs=[(x.split('@',1)[1] if '@' in x else artist,x.split('@',1)[0]) for x in titles.split('|')]
 evidence={'source':'https://en.wikipedia.org/wiki/Super_Bowl_'+roman+'_halftime_show','status':'candidate_reference_pool_requires_audio_matching','tracks':[{'artist':a,'title':t} for a,t in pairs]}
 (d/'setlist_candidates.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2)+'\n')
 state['current']=n;save()
 with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:results=list(pool.map(fetch,pairs))
 ready=[x for x in results if x['lyrics']];missing=[{'artist':x['artist'],'title':x['title'],'errors':x['errors']} for x in results if not x['lyrics']]
 (d/'reference_pool.json').write_text(json.dumps(results,ensure_ascii=False,indent=2)+'\n')
 # Partial reference pools are never presented as completed subtitles.
 if not missing:
  text='\n\n'.join('['+str(i+1)+' '+x['title']+']\n'+x['lyrics'] for i,x in enumerate(results))
  for fn in ['lyrics.txt','lyrics_sections.txt']:
   if not (d/fn).exists():(d/fn).write_text(text+'\n')
 state['jobs'][n]={'ready_tracks':len(ready),'total_tracks':len(results),'missing':missing,'stage':'references_ready' if not missing else 'partial_references'};save()
state['status']='finished';state['current']=None;save()
