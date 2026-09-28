"""Loopback-only harness dashboard. No cloud calls unless Bedrock is explicit."""
import argparse
import json
import mimetypes
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from harness import Arena, Planner, RomGame

ROOT = Path(__file__).resolve().parent


class Session:
    def __init__(self, args):
        self.args = args
        self.lock = threading.Lock()
        self.busy = False
        self.reset()

    def reset(self):
        if hasattr(self, "game"):
            self.game.close()
        self.game = (RomGame(self.args.rom, self.args.symbols, self.args.state)
                     if self.args.rom else Arena())
        self.planner = Planner(
            self.args.provider, self.args.endpoint, self.args.model, self.args.policy
        )
        self.log = []
        self.error = None
        self.elapsed = 0

    def snapshot(self):
        return dict(game=self.game.observe(), provider=self.args.provider, model=self.args.model,
                    policy=self.args.policy,
                    busy=self.busy, error=self.error, log=self.log[-12:],
                    calls=self.planner.calls, tokens=self.planner.tokens,
                    seconds=round(self.elapsed, 2))

    def step(self):
        with self.lock:
            if self.busy or self.game.status != "playing":
                return
            self.busy = True
            self.error = None
            before = self.game.observe()
        try:
            decision = self.planner.choose(before)
            with self.lock:
                self.game.step(decision["action"])
                self.elapsed += decision["seconds"]
                self.log.append(decision)
                (ROOT / "runs").mkdir(exist_ok=True)
                with (ROOT / "runs" / "dashboard.jsonl").open("a") as f:
                    f.write(json.dumps(dict(time=time.time(), before=before,
                                            decision=decision, after=self.game.observe())) + "\n")
        except Exception as exc:
            with self.lock:
                self.error = f"{type(exc).__name__}: {exc}"
        finally:
            with self.lock:
                self.busy = False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=18080)
    parser.add_argument("--provider", choices=["local", "rules", "bedrock"], default="local")
    parser.add_argument("--endpoint", default="http://127.0.0.1:18081/v1")
    parser.add_argument("--model", default="pokemon-local")
    parser.add_argument("--policy", choices=["pruned", "unfiltered"], default="pruned")
    parser.add_argument("--rom", type=Path)
    parser.add_argument("--symbols", type=Path)
    parser.add_argument("--state", type=Path)
    args = parser.parse_args()
    if args.rom and not args.symbols:
        parser.error("ROM mode requires a matching --symbols file for text-model telemetry")
    if args.provider == "bedrock" and args.model == "pokemon-local":
        parser.error("Specify an accessible Bedrock model ID with --model")
    session = Session(args)

    class Handler(BaseHTTPRequestHandler):
        def send(self, data, content_type="application/json", code=200):
            if not isinstance(data, bytes):
                data = json.dumps(data).encode()
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            path = urlparse(self.path).path
            if path == "/api/state":
                with session.lock:
                    self.send(session.snapshot())
            elif path == "/api/screen" and args.rom:
                with session.lock:
                    self.send(session.game.screen_png(), "image/png")
            else:
                routes = {
                    "/": ROOT / "static" / "index.html",
                    "/real.html": ROOT / "static" / "real.html",
                }
                asset = routes.get(path)
                if asset and asset.is_file():
                    self.send(asset.read_bytes(), mimetypes.guess_type(asset)[0])
                else:
                    self.send({"error": "Not found"}, code=404)

        def do_POST(self):
            expected = f"http://127.0.0.1:{args.port}"
            if self.headers.get("Origin", expected) not in {expected, f"http://localhost:{args.port}"}:
                self.send({"error": "Cross-origin control is disabled"}, code=403)
                return
            if self.path == "/api/step":
                threading.Thread(target=session.step, daemon=True).start()
                self.send({"ok": True})
            elif self.path == "/api/reset":
                with session.lock:
                    if session.busy:
                        self.send({"error": "Wait for the current decision"}, code=409)
                    else:
                        session.reset()
                        self.send({"ok": True})
            else:
                self.send({"error": "Not found"}, code=404)

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"Harness demo: http://127.0.0.1:{args.port} ({args.provider}, {args.policy})", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        session.game.close()
        server.server_close()


if __name__ == "__main__":
    main()
