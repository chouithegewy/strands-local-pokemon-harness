# Local Strands Pokémon harness

This directory contains the code behind the simulator and instrumented Pokémon
Red experiments described in the repository article. Inference uses a local
OpenAI-compatible endpoint by default; no AWS credentials or hosted model are
required unless `--provider bedrock` is selected explicitly.

## Install

```bash
python3 -m venv .venv
.venv/bin/pip install -r demo/requirements.txt
```

Start an OpenAI-compatible `llama.cpp` server with a model you obtained
separately:

```bash
llama-server \
  -m /path/to/model.gguf \
  --host 127.0.0.1 \
  --port 18081 \
  --alias pokemon-local \
  -c 4096 -t 4 -tb 4 -ngl 0 --device none \
  --jinja --reasoning off
```

The exact flags vary by `llama.cpp` build. The harness deliberately accepts a
loopback endpoint only in local mode.

## Reproduce the simulator policies

`harness.py` supports the two policies compared in the article:

```bash
# Full state and every legal action: the historical failure configuration.
.venv/bin/python demo/harness.py --provider local --policy unfiltered

# Compact state, exact forecasts, and candidate pruning.
.venv/bin/python demo/harness.py --provider local --policy pruned

# Deterministic comparison; no model call.
.venv/bin/python demo/harness.py --provider rules
```

Outputs are written to `demo/runs/evaluation-local-unfiltered.json`,
`demo/runs/evaluation-local.json`, and `demo/runs/evaluation-rules.json`.
Fresh model results may differ by model build and runtime. The original
single-run traces reported in the article are preserved under `../results/`.

For the interactive dashboard, either leave the server running separately or
let the launcher start it by setting the paths:

```bash
POKEMON_MODEL=/path/to/model.gguf \
LLAMA_SERVER=/path/to/llama-server \
bash demo/run.sh
```

Open <http://127.0.0.1:18080>. The explicit no-model dashboard is:

```bash
bash demo/run.sh --provider rules
```

`harness.py` creates a fresh Strands `Agent` for each model decision, retains at
most four recent actions, restricts output to the candidate action IDs, and
validates the response before mutating game state. `--policy unfiltered`
exposes the original full observation and all legal choices; `--policy pruned`
uses the compact action table described in the article.

## Instrumented Pokémon Red adapter

The real-game code requires all of the following, none of which are distributed
in this repository:

- A legally obtained English Pokémon Red ROM with SHA-1
  `ea9bcae617fdf159b045185467ae58b2e4a48b9a`.
- A matching `pokered.sym` produced from the
  [`pret/pokered`](https://github.com/pret/pokered) disassembly.
- A local model endpoint if the high-level planner will be used.

Generate opening-area walkability and start the bounded adapter:

```bash
.venv/bin/python demo/build_maps.py \
  --rom '/path/to/Pokemon Red.gb' \
  --symbols /path/to/pokered.sym

.venv/bin/python demo/game_lab.py \
  --rom '/path/to/Pokemon Red.gb' \
  --symbols /path/to/pokered.sym \
  --output demo/runs/real-game
```

In another terminal:

```bash
.venv/bin/python demo/game_control.py plan
.venv/bin/python demo/navigate.py 7 1
.venv/bin/python demo/macros.py plan --target 7
```

Set `POKEMON_GAME_URL`, `POKEMON_GAME_OUTPUT`, `POKEMON_MODEL_ENDPOINT`,
`POKEMON_MODEL_ID`, or `POKEMON_MAPS` to override their loopback/default paths.
Use a fresh output directory for each recording.

The adapter:

- Reads telemetry from emulator memory using matching symbols.
- Accepts only the eight Game Boy buttons plus `wait`, with frame and repetition
  budgets.
- Writes input and plan JSONL logs, PyBoy checkpoints, a structured state file,
  screenshots, and a direct H.264 capture.
- Does not write HP, position, experience, inventory, or event flags.

The recorded September 24, 2026 run reached Oak's Lab, selected Squirtle, and
confirmed `party_count: 1`. Setup and route selection were operator-assisted;
no battle win or full-game completion was demonstrated.

## Tests

The unit tests cover mutation safety, pruning, the unfiltered policy, endpoint
restriction, knockout behavior, and the deterministic baseline:

```bash
PYTHONPATH=demo .venv/bin/python -m unittest demo/tests.py -v
```
