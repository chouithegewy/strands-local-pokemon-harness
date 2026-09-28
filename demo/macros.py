"""Opening-area action macros. Plans are LLM-selected; these mechanics are code."""
import argparse
import json
from game_control import act,plan,state
from navigate import goto

def report(s):
    print(json.dumps({k:s[k] for k in ['map','x','y','hp','max_hp','level','battle','screen_text']}),flush=True)

def fight(max_inputs=90):
    """Use the first move via normal menus; no opponent/HP memory manipulation."""
    for _ in range(max_inputs):
        s=state()
        if not s['battle']:return s
        s=act('a',12,1,100)
        report(s)
    raise RuntimeError('Battle input budget exhausted')

def leave_lab():
    s=goto(5,11)
    if s['battle']:return fight()
    if s['map']==40:return act('down',8,1,60)
    return s

def heal():
    s=state()
    if s['battle']:fight()
    s=state()
    if s['map']==40:leave_lab()
    s=state()
    if s['map']==12:
        goto(10,35);act('down',8,1,60)
    s=state()
    if s['map']==0:
        goto(5,6);act('up',8,1,60)
    s=state()
    if s['map']!=37:raise RuntimeError('Heal route is only implemented for Pallet and Route 1')
    goto(4,4);act('right',4,1,8)
    for _ in range(24):
        s=act('a',12,1,100);report(s)
        if s['hp']==s['max_hp'] and s['hp']>0:
            # Close the final dialogue before navigation resumes.
            act('b',8,2,60)
            return s
    raise RuntimeError('Heal macro did not observe restored HP')

def train(target=7):
    s=state()
    if s['map']==40:leave_lab()
    if state()['map']==37:
        goto(2,7);act('down',8,1,60)
    if state()['map']==0:
        goto(10,0);act('up',8,1,60)
    if state()['map']!=12:raise RuntimeError('Training route requires Route 1')
    for n in range(120):
        s=state()
        if s['battle']:s=fight()
        if s['level']>=target or s['hp']<s['max_hp']*.4:return s
        if s['y']>29:goto(10,29)
        else:act('left' if n%2 else 'right',24,1,12)
        report(state())
    raise RuntimeError('Training movement budget exhausted')

def run_plan(target=7):
    choice=plan(f'Obtain a starter; safely train to level {target}. Heal below 40 percent HP. Once at target, advance the story.')
    print(json.dumps(choice),flush=True)
    if choice['macro']=='heal':return heal()
    if choice['macro']=='train':return train(target)
    return dict(status='objective needs a story-specific route',state=state())

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('macro',choices=['fight','heal','train','plan','leave-lab']);p.add_argument('--target',type=int,default=7);args=p.parse_args()
    if args.macro=='plan':result=run_plan(args.target)
    elif args.macro=='train':result=train(args.target)
    else:result={'fight':fight,'heal':heal,'leave-lab':leave_lab}[args.macro]()
    print(json.dumps(result))
