"""Actual Pokémon Red control, telemetry, checkpointing and frame capture.

Serves only loopback. Frame inputs are bounded; no memory writes or game cheats.
"""
import argparse
import hashlib
import io
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from PIL import Image, ImageDraw, ImageFont
from pyboy import PyBoy
import imageio_ffmpeg

ROOT = Path(__file__).resolve().parent
ROM_SHA1 = 'ea9bcae617fdf159b045185467ae58b2e4a48b9a'


def load_font(size, bold=False):
    name = 'DejaVuSans-Bold.ttf' if bold else 'DejaVuSans.ttf'
    try:
        return ImageFont.truetype(name, size)
    except OSError:
        return ImageFont.load_default()


class GameLab:
    def __init__(self, rom, symbols, output, state_path=None):
        if hashlib.sha1(Path(rom).read_bytes()).hexdigest() != ROM_SHA1:
            raise ValueError('This telemetry/navigation profile requires the verified English Pokémon Red ROM')
        self.out = Path(output); self.out.mkdir(parents=True, exist_ok=True)
        self.p = PyBoy(str(rom), window='null', sound_emulated=False,
                       symbols=str(symbols))
        self.p.set_emulation_speed(0)
        if state_path:
            with open(state_path, 'rb') as f:
                self.p.load_state(f)
        self.lock = threading.RLock()
        self.frames = 0
        self.macro = 'objective'
        self.reason = 'Start a new game; obtain a starter Pokémon.'
        self.calls = 0
        self.last_action = 'boot'
        self.last_buttons = []
        self.font = load_font(24)
        self.small = load_font(18)
        self.title = load_font(34, bold=True)
        self.writer = imageio_ffmpeg.write_frames(str(self.out/'pokemon-red-direct.mp4'),
            (1280,720), fps=15, codec='libx264', quality=7, pix_fmt_in='rgb24',
            output_params=['-movflags','+faststart'], ffmpeg_log_level='error')
        self.writer.send(None)
        self.closed = False
        self.capture()

    def read(self, symbol, width=1):
        _, a = self.p.symbol_lookup(symbol)
        return int.from_bytes(bytes(self.p.memory[a:a+width]), 'big')

    def state(self):
        result = {key:self.read(symbol) for key,symbol in {
            'map':'wCurMap','x':'wXCoord','y':'wYCoord','battle':'wIsInBattle',
            'party_count':'wPartyCount','badges':'wObtainedBadges',
            'menu':'wCurrentMenuItem','joy_ignore':'wJoyIgnore',
            'level':'wPartyMon1Level', 'text_box':'wTextBoxID'}.items()}
        for k,s in [('hp','wPartyMon1HP'),('max_hp','wPartyMon1MaxHP'),('enemy_hp','wEnemyMonHP')]:
            result[k]=self.read(s,2)
        result.update(frames=self.frames, video_seconds=round(self.frames/60,2),
                      macro=self.macro,reason=self.reason,model_calls=self.calls,
                      last_action=self.last_action,screen_text=self.screen_text())
        return result

    def screen_text(self):
        # The game's tile IDs encode its text alphabet; no vision model required.
        chars = {0x7f:' ',0xe3:'-',0xe6:'?',0xe7:'!',0xe8:'.',0xf3:'/',0xef:'♂',0xf5:'♀',0xe0:"'",0xf4:',',0xf0:'¥'}
        chars.update({0x80+i:chr(65+i) for i in range(26)})
        chars.update({0xa0+i:chr(97+i) for i in range(26)})
        chars.update({0xf6+i:str(i) for i in range(10)})
        _, start = self.p.symbol_lookup('wTileMap')
        vals=self.p.memory[start:start+360]
        rows=[''.join(chars.get(v,' ') for v in vals[y*20:(y+1)*20]).rstrip() for y in range(18)]
        return '\n'.join(r.strip() for r in rows if any(c.isalpha() for c in r))

    def capture(self):
        s=self.state()
        canvas=Image.new('RGB',(1280,720),'#101826');d=ImageDraw.Draw(canvas)
        d.text((34,22),'SMALL MODEL / REAL POKÉMON RED',font=self.title,fill='#f4f7fb')
        screen=self.p.screen.image.convert('RGB').resize((640,576),Image.Resampling.NEAREST)
        canvas.paste(screen,(32,102))
        d.text((720,110),'HEAL   TRAIN   OBJECTIVE',font=self.font,fill='#ffad42')
        d.text((720,172),'Current plan: '+self.macro.upper(),font=self.font,fill='#7ce0c0')
        import textwrap
        y=225
        for line in textwrap.wrap(self.reason,38)[:5]:
            d.text((720,y),line,font=self.small,fill='#d0dbea');y+=29
        for line in [f"Map {s['map']} | tile ({s['x']}, {s['y']})",
                     f"HP {s['hp']}/{s['max_hp']} | level {s['level']}",
                     f"Party {s['party_count']} | badges {s['badges'].bit_count()}",
                     f"Strands + Qwen3 1.7B | calls {self.calls}",
                     f"Input: {self.last_action}",
                     f"Game time: {self.frames/60:.1f}s"]:
            d.text((720,y+25),line,font=self.small,fill='#acbbce');y+=35
        d.text((720,654),'Actual emulator frames · no memory writes',font=self.small,fill='#7ce0c0')
        self.writer.send(canvas.tobytes())
        # Also provide an OBS Image source; OBS refreshes changed files once/second.
        tmp=self.out/'live.tmp.png';canvas.save(tmp);tmp.replace(self.out/'live.png')
        self.p.screen.image.save(self.out/'screen.png')

    def tick(self, frames):
        for _ in range(0,frames,4):
            self.p.tick(4)
            self.frames+=4
            self.capture()

    def act(self, button='wait', frames=24, repeat=1, release=8):
        if self.closed: raise ValueError('Recording is closed')
        if button not in ['wait','a','b','start','select','up','down','left','right']:
            raise ValueError('Unsupported button')
        if not 1<=repeat<=100 or not 4<=frames<=600 or not 0<=release<=120:
            raise ValueError('Input exceeds frame/repetition budget')
        with self.lock:
            before=self.state()
            for _ in range(repeat):
                self.last_action=f'{button} ({frames} frames)'
                if button!='wait':self.p.button_press(button)
                self.tick(frames)
                if button!='wait':self.p.button_release(button)
                if release:self.tick(release)
            after=self.state()
            with (self.out/'inputs.jsonl').open('a') as f:
                f.write(json.dumps(dict(button=button,frames=frames,repeat=repeat,release=release,before=before,after=after))+'\n')
            with (self.out/'latest.state').open('wb') as f:self.p.save_state(f)
            (self.out/'state.json').write_text(json.dumps(after,indent=2))
            return after

    def close(self):
        with self.lock:
            if self.closed:return
            self.writer.close()
            with (self.out/'final.state').open('wb') as f:self.p.save_state(f)
            self.p.stop(save=False)
            self.closed=True


def main():
    a=argparse.ArgumentParser();a.add_argument('--rom',type=Path,required=True)
    a.add_argument('--symbols',type=Path,required=True,
                   help='matching pokered.sym generated from pret/pokered')
    a.add_argument('--output',type=Path,default=ROOT/'runs/real-game');a.add_argument('--port',type=int,default=18082)
    a.add_argument('--state',type=Path);args=a.parse_args();lab=GameLab(args.rom,args.symbols,args.output,args.state)
    class Handler(BaseHTTPRequestHandler):
        def send(self,data,typ='application/json',status=200):
            if not isinstance(data,bytes):data=json.dumps(data).encode()
            self.send_response(status);self.send_header('Content-Type',typ);self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
        def do_GET(self):
            with lab.lock:
                if self.path=='/state':self.send(lab.state())
                elif self.path in ['/live.png','/screen.png']:
                    self.send((lab.out/self.path[1:]).read_bytes(),'image/png')
                else:self.send({'error':'not found'},status=404)
        def do_POST(self):
            try:
                origin=self.headers.get('Origin')
                if origin and urlparse(origin).hostname not in ['127.0.0.1','localhost']:raise ValueError('Local controls only')
                n=int(self.headers.get('Content-Length',0))
                if n>8192:raise ValueError('Request too large')
                data=json.loads(self.rfile.read(n) or '{}')
                if self.path=='/act':self.send(lab.act(**data))
                elif self.path=='/plan':
                    with lab.lock:
                        lab.macro=data['macro'];lab.reason=data['reason'];lab.calls=data.get('calls',lab.calls)
                        self.send(lab.state())
                elif self.path=='/finish':lab.close();self.send({'ok':True})
                else:self.send({'error':'not found'},status=404)
            except Exception as e:self.send({'error':str(e)},status=400)
        def log_message(self,*_):pass
    server=ThreadingHTTPServer(('127.0.0.1',args.port),Handler)
    print(f'Actual game control: http://127.0.0.1:{args.port}',flush=True)
    try:server.serve_forever()
    finally:lab.close()

if __name__=='__main__':main()
