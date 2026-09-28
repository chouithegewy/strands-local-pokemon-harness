"""Small command-line client for the local game lab; all operations are logged."""
import argparse
import json
import os
from pathlib import Path
import httpx

ROOT=Path(__file__).resolve().parent
URL=os.environ.get('POKEMON_GAME_URL','http://127.0.0.1:18082')
OUTPUT=Path(os.environ.get('POKEMON_GAME_OUTPUT',ROOT/'runs/real-game'))
MODEL_ENDPOINT=os.environ.get('POKEMON_MODEL_ENDPOINT','http://127.0.0.1:18081/v1')
MODEL_ID=os.environ.get('POKEMON_MODEL_ID','pokemon-local')

def state():
    return httpx.get(URL+'/state',trust_env=False).json()

def act(button='wait',frames=24,repeat=1,release=8):
    r=httpx.post(URL+'/act',json=dict(button=button,frames=frames,repeat=repeat,release=release),timeout=180,trust_env=False)
    r.raise_for_status()
    return r.json()

def plan(objective='Obtain a starter, then train to level 7. Heal if HP is below 40 percent.'):
    from strands import Agent
    from strands.models.openai import OpenAIModel
    before=state()
    choices=['objective'] if not before['party_count'] else ['heal','train','objective']
    schema={'type':'object','properties':{'macro':{'type':'string','enum':choices},'reason':{'type':'string'}},'required':['macro','reason'],'additionalProperties':False}
    model=OpenAIModel(client_args={'base_url':MODEL_ENDPOINT,'api_key':'local-demo','timeout':30,'max_retries':0},model_id=MODEL_ID,params={'temperature':0,'max_tokens':90,'response_format':{'type':'json_schema','json_schema':{'name':'plan','strict':True,'schema':schema}}})
    agent=Agent(model=model,callback_handler=None,retry_strategy=None,system_prompt='Choose a high-level plan for Pokemon Red. HEAL when HP is below 40 percent, TRAIN if healthy but below the target level, otherwise OBJECTIVE. Before obtaining a Pokemon, choose OBJECTIVE. A battle in progress must be resolved before traveling. Give a short reason. Output JSON only. /no_think')
    compact={k:before[k] for k in ['map','x','y','hp','max_hp','level','party_count','battle']}
    response=agent(json.dumps(dict(state=compact,objective=objective)))
    result=json.loads(str(response));result['calls']=before['model_calls']+1
    OUTPUT.mkdir(parents=True,exist_ok=True)
    with (OUTPUT/'plans.jsonl').open('a') as f:
        f.write(json.dumps(dict(before=before,objective=objective,decision=result,usage=response.metrics.accumulated_usage))+'\n')
    httpx.post(URL+'/plan',json=result,trust_env=False).raise_for_status()
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('commands',nargs='*');a=p.parse_args()
    for command in a.commands:
        if command=='plan':print(json.dumps(plan()));continue
        parts=command.split(':')
        print(json.dumps(act(parts[0],*[int(v) for v in parts[1:]])))
    if not a.commands:print(json.dumps(state(),indent=2))
