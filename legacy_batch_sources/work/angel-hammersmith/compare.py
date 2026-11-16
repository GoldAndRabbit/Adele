import json,re,unicodedata
from pathlib import Path
def key(s):return ' '.join(re.findall(r'[^\W_]+',unicodedata.normalize('NFKC',s).casefold().replace('’',"'"),re.U))
def lines(n):
 d=Path('posts')/n
 return {key(u['orig']):u for u in json.loads((d/'subs/translation/result.json').read_text())['units'] if u['type']=='歌词' and not u.get('dropped')}
if __name__=='__main__':
 a,b=map(lines,['the_angel_live','the_angel_gunnertv']);both=a.keys()&b.keys();print(len(a),len(b),len(both));print([(a[k]['orig'],a[k]['v3_final'],b[k]['v3_final'],a[k]['locked'],b[k]['locked']) for k in both if a[k]['v3_final']!=b[k]['v3_final']][:12]);print('fixed',[(d.name,len(json.loads((d/'zh_fixed.json').read_text()))) for d in Path('posts').glob('the_angel*') if (d/'zh_fixed.json').exists()])
