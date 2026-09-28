"""Bounded BFS navigation. Re-observe after every tile; stop for battle or map change."""
import argparse
import json
import os
from collections import deque
from pathlib import Path
from game_control import act,state,plan

MAPS_PATH=Path(os.environ.get('POKEMON_MAPS',Path(__file__).parent/'game_assets/maps.json'))
MAPS=json.loads(MAPS_PATH.read_text())
DIRS=[('up',0,-1),('left',-1,0),('right',1,0),('down',0,1)]

def goto(x,y,budget=100):
    start=state();mapid=start['map'];grid=MAPS[str(mapid)];blocked=set()
    for step in range(budget):
        s=state();pos=(s['x'],s['y']);goal=(x,y)
        if s['battle'] or s['map']!=mapid or pos==goal or s['joy_ignore']:
            return s
        q=deque([(pos,[])]);seen={pos};path=None
        while q:
            cur,route=q.popleft()
            if cur==goal:path=route;break
            for name,dx,dy in DIRS:
                nxt=(cur[0]+dx,cur[1]+dy)
                if nxt in seen or nxt in blocked:continue
                if not (0<=nxt[0]<grid['width'] and 0<=nxt[1]<grid['height']):continue
                if not grid['walk'][nxt[1]][nxt[0]] and nxt!=goal:continue
                seen.add(nxt);q.append((nxt,route+[(name,nxt)]))
        if not path:raise RuntimeError(f'No route from {pos} to {goal}; obstacles {blocked}')
        name,nxt=path[0]
        after=act(name,8,1,16)
        print(json.dumps(dict(step=step,button=name,map=after['map'],x=after['x'],y=after['y'],battle=after['battle'])),flush=True)
        if after['joy_ignore']:
            return after
        if (after['x'],after['y'])==pos and after['map']==mapid:
            if any(word in after['screen_text'] for word in ['OAK ', 'BLUE ', 'POK MON', 'Welcome', 'HP']):
                return after
            after=act(name,8,1,24)
            if (after['x'],after['y'])==pos:
                blocked.add(nxt)
    raise RuntimeError('Navigation step budget exhausted')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('x',type=int);p.add_argument('y',type=int);a=p.parse_args()
    print(json.dumps(goto(a.x,a.y)))
