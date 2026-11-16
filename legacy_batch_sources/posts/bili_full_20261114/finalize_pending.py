import sys
from pathlib import Path
sys.path.insert(0,str(Path.cwd()))
from workflow.live.paths import read_json
from post_bili.finalize_collection import finalize

folder = Path('posts/bili_full_20261114')
targets = [
 ('grammys_2013',9573349),('eminem_detroit_anger_management',9573350),
 ('super_bowl_halftime',9573351),('artist_6164656c65',9573352),
 ('artist_616e64726577207768697465',9573364),('artist_6368617070656c6c20726f616e',9573365),
 ('artist_646973747572626564',9573366),('artist_6564207368656572616e',9573367),
 ('artist_656d696e656d',9573395),('artist_67726163696520616272616d73',9573396),
 ('artist_686b743438',9573452),('artist_6c696e6b696e207061726b',9573468)]
for slug,sid in targets:
 if slug in read_json(folder/'collections_verified.json',{}):continue
 try:
  finalize(folder/'plan.json',slug,sid)
 except (Exception,SystemExit) as error:
  print('待恢复',slug,str(error),flush=True)
