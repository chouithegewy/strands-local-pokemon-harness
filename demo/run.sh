#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
PYTHON="$PWD/.venv/bin/python"
MODEL_PATH="${POKEMON_MODEL:-}"
SERVER_BIN="${LLAMA_SERVER:-$(command -v llama-server || true)}"
mkdir -p demo/runs
model_pid=''
cleanup() { if [[ -n "$model_pid" ]]; then kill "$model_pid" 2>/dev/null || true; fi; }
trap cleanup EXIT
if [[ ! -x "$PYTHON" ]]; then
  echo 'Install first: python3 -m venv .venv && .venv/bin/pip install -r demo/requirements.txt' >&2
  exit 1
fi
if [[ " ${*:-} " != *' --provider rules '* && " ${*:-} " != *' --provider bedrock '* ]]; then
  if ! "$PYTHON" -c 'import urllib.request; urllib.request.urlopen("http://127.0.0.1:18081/health", timeout=2)' 2>/dev/null; then
    [[ -n "$SERVER_BIN" && -n "$MODEL_PATH" && -f "$MODEL_PATH" ]] || { echo 'Set LLAMA_SERVER and POKEMON_MODEL to your local executable and GGUF.' >&2; exit 1; }
    "$SERVER_BIN" -m "$MODEL_PATH" --host 127.0.0.1 --port 18081 --alias pokemon-local \
      -c 4096 -t 4 -tb 4 -ngl 0 --device none --jinja --reasoning off >demo/runs/llama-server.log 2>&1 &
    model_pid=$!
    "$PYTHON" - <<'PY'
import time, urllib.request
for _ in range(60):
    try:
        urllib.request.urlopen('http://127.0.0.1:18081/health', timeout=1)
        break
    except OSError:
        time.sleep(.5)
else:
    raise SystemExit('Model failed to start; see demo/runs/llama-server.log')
PY
  fi
fi
"$PYTHON" demo/server.py "$@"
