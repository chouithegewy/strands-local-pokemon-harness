<!--
AWS Builder Center draft metadata

Title: I Tuned the Harness, Not the Model: Playing Pokémon with Strands and a 1.7B Local LLM
Description: A 1.7B local model lost a small Pokémon battle simulator until I changed the state, action space, and safety rails around it. Here is what the experiment taught me about agent harness engineering with Strands.
Suggested tags: strands-agents, generative-ai, local-llm, agentic-ai, python
Hero image: https://raw.githubusercontent.com/chouithegewy/strands-local-pokemon-harness/main/assets/harness-architecture.png
Source repository: https://github.com/chouithegewy/strands-local-pokemon-harness
-->

# I Tuned the Harness, Not the Model: Playing Pokémon with Strands and a 1.7B Local LLM

![A local Pokémon agent architecture in which deterministic code observes and constrains the game before a small model chooses one legal action](https://raw.githubusercontent.com/chouithegewy/strands-local-pokemon-harness/main/assets/harness-architecture.png)

At DEF CON 34 in Las Vegas, I came across **AI Village Plays Pokemon**, a competition where builders created agents and gave them two hours to progress through Pokemon FireRed or LeafGreen. The organizers supplied game infrastructure and sample navigation and battle tools. The point was not simply to put a model in front of a Game Boy screen. It was to build the system around the model.

I found that extremely interesting! Beating the frontier models by implementing a smart harness over a small llm for a specific goal: beat Pokemon!

Frontier-model game demonstrations are impressive, but they can consume a great deal of inference. In an [interview about Claude Plays Pokémon](https://www.josherich.me/podcast/latent-space/how-claude-plays-pok%C3%A9mon-was-made), the project's creator described extensive experimentation as consuming at least thousands of dollars in tokens. I wanted to ask a different question: **How far could I get with a small model that runs entirely on my laptop if I made the harness smarter?**

I started with the [Build a Production AI Agent workshop](https://github.com/aws-samples/sample-strands-agents-hands-on-workshop), replaced its customer-service setting with a game loop, and connected the [Strands Agents SDK](https://strandsagents.com/) to a local `llama.cpp` server. The model was Qwen3 1.7B, quantized to Q4_K_M. The GGUF file was about 1.1 GB.

I did **not** fine-tune the model on Pokémon. I tuned the harness around a general-purpose small model.

The result was more interesting than a simple win. The model first lost a tiny battle simulator while wasting 14,108 tokens. After I changed the observation format and action space, the same model won in 4,055 tokens. That is a single-run result, not a benchmark, but it exposed the part of agent engineering I find most useful: model capability is only one component of system capability.

> This is an independent engineering experiment. I used my own game ROM and do not distribute one. The real-game harness has not completed Pokémon Red.

## Run the implementation

The complete implementation is in [`demo/`](demo/README.md). It includes the
simplified simulator, the Strands planner, both the unfiltered and pruned
evaluation policies, the deterministic baseline, and the bounded PyBoy adapter.
The original simulator traces used for the table below are preserved in
[`results/`](results/README.md).

```bash
python3 -m venv .venv
.venv/bin/pip install -r demo/requirements.txt

# Reproduce the deterministic baseline without a model.
.venv/bin/python demo/harness.py --provider rules

# With llama-server listening on 127.0.0.1:18081:
.venv/bin/python demo/harness.py --provider local --policy unfiltered
.venv/bin/python demo/harness.py --provider local --policy pruned
```

The repository intentionally excludes ROMs, model weights, save states,
ROM-derived navigation maps, and real-game video captures.

## What I built

The prototype has two related environments:

1. An original, simplified battle simulator for fast harness experiments.
2. An instrumented Pokémon Red environment using PyBoy, bounded controller inputs, emulator telemetry, checkpoints, and video capture.

The measured local configuration was intentionally modest:

| Component | Configuration |
|---|---|
| CPU | AMD Ryzen 5 4500U, 6 cores |
| Memory | 15 GiB usable RAM |
| Model | Qwen3 1.7B, Q4_K_M GGUF |
| Model file | 1,107,409,472 bytes |
| Inference | `llama.cpp`, CPU-only, 4 threads |
| Context | 4,096 tokens |
| Agent SDK | Strands Agents for Python |
| Emulator | PyBoy |

No AWS credentials or hosted-model API key were required for these runs. Strands supplied the agent abstraction and model-provider integration; inference stayed on the laptop. Because Strands supports multiple providers, the same design can later be compared with a model on Amazon Bedrock without rewriting the game controller.

## Connect Strands to a local model

I served the quantized model through the OpenAI-compatible API in `llama.cpp`:

```bash
llama-server \
  -m /path/to/Qwen3-1.7B-Q4_K_M.gguf \
  --host 127.0.0.1 \
  --port 18081 \
  --alias pokemon-local \
  -c 4096 \
  -t 4 \
  -tb 4 \
  -ngl 0 \
  --device none \
  --jinja \
  --reasoning off
```

The exact command-line flags can vary by `llama.cpp` build. The important boundaries are that the server listens only on loopback and exposes a model alias the application can select.

Strands can connect to an OpenAI-compatible endpoint through `OpenAIModel`. In my implementation, the candidate IDs become a JSON Schema enum, so I construct a fresh model and agent for each bounded decision:

```python
from strands import Agent
from strands.models.openai import OpenAIModel

def make_agent(action_ids):
    schema = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": action_ids},
            "reason": {"type": "string"},
        },
        "required": ["action", "reason"],
        "additionalProperties": False,
    }

    model = OpenAIModel(
        client_args={
            "base_url": "http://127.0.0.1:18081/v1",
            "api_key": "local-demo",
            "timeout": 30,
            "max_retries": 0,
        },
        model_id="pokemon-local",
        params={
            "temperature": 0,
            "max_tokens": 100,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "game_action",
                    "strict": True,
                    "schema": schema,
                },
            },
        },
    )

    return Agent(
        model=model,
        callback_handler=None,
        retry_strategy=None,
        system_prompt=(
            "Choose exactly one legal action and give a short reason. "
            "Prefer a knockout. Heal before fainting. Avoid repeated switches."
        ),
    )
```

This looks like the important part, but model connectivity turned out to be the easy part. The action boundary mattered much more.

## The first run failed

The simulator exposes attacks, team switches, and healing. In the first version, I gave the model the full game state and every legal action.

The model repeatedly switched Pokemon instead of attacking. Its explanations sounded confident, but often contradicted the numbers in the prompt. Every switch allowed the opponent to attack, so the team eventually fainted without defeating the first opponent.

After 27 model calls, the run ended in a loss:

| Result | Decisions | Reported tokens | Model time |
|---|---:|---:|---:|
| Unfiltered local model | Lost | 14,108 | 194.284 seconds |

This was not a prompt-wording problem. The harness was asking a 1.7B model to reconcile redundant state, infer game mechanics, compare every option, notice loops, and produce valid structured output on every turn.

That was too much undifferentiated work.

## Make the decision smaller

I changed the harness in five ways.

### 1. Convert the world into compact state

The model did not need a transcript of the whole battle. It needed the active Pokemon, the opponent's remaining HP, a short action history, and a table of choices.

```python
compact_state = {
    "turn": observation["turn"],
    "opponent_hp": observation["opponent"]["hp"],
    "active": observation["team"][observation["active"]]["name"],
    "actions": candidates,
}
```

For each action, deterministic code calculated damage, expected incoming damage, and remaining HP. The model compared answers instead of deriving the answers from several nested objects.

### 2. Remove objectively wasteful choices

The application pruned actions before calling the model:

```python
def candidates(observation):
    moves = [
        action for action in observation["legal_actions"]
        if action["id"].startswith("move:")
    ]
    best_damage = max(action["damage"] for action in moves)

    if best_damage >= observation["opponent"]["hp"]:
        return [
            action for action in moves
            if action["damage"] >= observation["opponent"]["hp"]
        ]

    safe_moves = [action for action in moves if action["hp_after"] > 0]
    return safe_moves or moves
```

The full implementation also permits a switch only when the new teammate is safe and materially improves the next attack. Healing is offered only below an HP threshold.

This is substantial domain knowledge, and it should be described honestly. The model did not learn type matchups by playing. The harness calculated them and presented a decision table.

### 3. Constrain the output

The model returned JSON containing one action identifier and a short explanation. The action field was restricted to an enum generated from the current candidate list.

The application then validated the response again before changing state:

```python
allowed = {action["id"] for action in candidates}

if decision.get("action") not in allowed:
    raise ValueError("Model returned an illegal action")
```

A model suggestion is data, not authority. The controller owns the action boundary.

### 4. Keep memory short

Each battle decision used the current observation plus at most four recent actions. A fresh Strands `Agent` handled each request. This prevented a growing conversational history from turning a small tactical choice into a long-context problem.

### 5. Log every transition

For every turn, the harness recorded:

- State before the decision
- Candidate actions after pruning
- Selected action and generated explanation
- State after execution
- Token usage and model latency

Without the failed trace, I might have blamed the model in general. The log showed a specific failure mode: repeated switching caused by a broad and confusing action space.

## The same model won after the harness changed

With compact state, exact forecasts, bounded output, and action pruning, the same local model won all four simulated battles.

| Controller | Result | Decisions | Reported tokens | Model time |
|---|---|---:|---:|---:|
| Local model, unfiltered actions | Lost | 27 | 14,108 | 194.284 seconds |
| Local model, pruned actions | Won | 14 | 4,055 | 53.565 seconds |
| Deterministic rules baseline | Won | 11 | 0 | 0 seconds |

The successful model run used about 71% fewer reported tokens and 72% less model time than the failed run. More importantly, it changed the outcome.

These were single observations on one laptop, not repeated statistical trials. The simulator is also intentionally small. Its value is diagnostic: it makes the contribution of the harness visible.

The rules baseline is equally important. It won in fewer turns with no inference at all. If a complete and reliable rule is available, use code. The model earns its place where the state is ambiguous, goals compete, or the next objective requires judgment.

## Moving from a simulator to a real game

The next step was not to point the model at screenshots and hope. I built an adapter around PyBoy that exposes a small set of trustworthy observations:

- Current map and tile coordinates
- Battle state
- Party count
- Lead Pokemon HP, maximum HP, and level
- Enemy HP
- Badges
- Text decoded from the game's tile map

The adapter accepts only nine bounded inputs: the eight Game Boy buttons plus `wait`. Each request limits button duration, repetitions, and release frames. It records the before-and-after state, saves a checkpoint, and appends frames to an MP4.

I used symbols from the [pret/pokered](https://github.com/pret/pokered) disassembly to locate telemetry in emulator memory. The harness only reads that state; it does not write HP, position, experience, inventory, or event flags.

For movement, deterministic breadth-first search operates over walkable tiles derived from the ROM. It re-observes after every tile and stops on battles, dialogue, scripted movement, map transitions, or a step budget. For the opening area, I added explicit macros for three high-level intents:

- `heal`
- `train`
- `objective`

The local model chooses among those intents from compact telemetry. Deterministic code handles the button-level mechanics underneath.

That division is deliberate:

```text
small model:  choose the next useful objective
harness:      expose valid plans and enforce budgets
controller:   navigate, operate menus, and recover
emulator:     execute buttons and report state
```

The recorded real-game run reached Oak's Lab, selected Squirtle, and stopped at the nickname prompt. PyBoy telemetry confirmed `party_count: 1`.

It did not win a battle. Initial setup and route selection were operator-assisted. It did not beat Pokémon Red.

That boundary is not a footnote; it defines the next engineering work.

## What this taught me about small-model agents

### The model is not the system

The model generated one decision. The harness supplied perception, legal actions, memory, validation, execution, checkpoints, and evidence. Changing those components changed the result without changing model weights.

### Fewer choices can produce more capability

Giving the model every technically legal action felt more agentic, but it made the system worse. Removing actions that were provably wasteful reduced both cost and failure.

### Deterministic code and language models are complements

Pathfinding, damage math, schema validation, and frame budgets are deterministic problems. High-level prioritization is a better place to test model judgment. A good harness puts each kind of work in the right layer.

### Observability is part of the product

Structured traces, token counts, checkpoints, and video made the experiment debuggable. They also prevent accidental overclaiming. “The model selected a starter” and “the agent beat the game” are very different statements.

### Local-first development makes iteration cheap

The unsuccessful run was useful because it did not create an API bill. I could inspect failure, change the action contract, and run again. Strands let me keep the agent interface while using a local OpenAI-compatible endpoint.

## What it would take to beat the game

A full run needs much more application engineering:

1. Broader map coverage and event-aware navigation
2. Reliable dialogue, battle, inventory, and party menu state machines
3. Move selection, capture strategy, and resource management
4. Story-progress tracking and objective decomposition
5. Save-state recovery from known failure modes
6. Repeated evaluations from identical checkpoints
7. A local-versus-Amazon Bedrock comparison using the same traces and budgets

The interesting goal is not to hide those components behind the phrase “the AI played Pokémon.” It is to measure what each component contributes.

## Conclusion

The goal was to learn and explore the space of smart harnesses. That objective was met. Project-based learning is the style I can most confidently attest to: building the system made the abstractions concrete.

The clearest technical result was that the same 1.7B model changed from a loss to a win without retraining or changing its weights. Compact telemetry, exact action forecasts, candidate pruning, structured output, and post-response validation turned an open-ended game problem into a bounded decision. The harness did not make the model larger; it made each model call smaller and more useful.

The real-game run clarified the remaining gap just as usefully. Selecting Squirtle proved that the emulator, telemetry, bounded controls, checkpoints, and high-level planner could work together. It did not prove full-game autonomy. Reliable progress still requires navigation, dialogue, battle, inventory, and story-event state machines; checkpoint recovery; and repeated evaluations from identical starting states. Those are harness-engineering problems, not details that a better prompt can simply erase.

Just scratching the surface supplied me with more questions than I had at the start. That is one of the interesting things about diving deeper into the evolving space of AI: every layer that becomes understandable exposes another layer worth measuring.

And even though my smart harness could not beat Pokémon, maybe it really is about the Pokémon we caught along the way.

I will keep exploring the space, turning those unknowns into smaller, observable, and testable decisions.

## References

- [Public repository for this article and its architecture assets](https://github.com/chouithegewy/strands-local-pokemon-harness)
- [Build a Production AI Agent: Strands Agents Hands-On Workshop](https://github.com/aws-samples/sample-strands-agents-hands-on-workshop)
- [Strands Agents SDK](https://strandsagents.com/)
- [Using an OpenAI-compatible model with Strands](https://strandsagents.com/docs/user-guide/sdk/model-providers/openai/)
- [Qwen3 1.7B model card](https://huggingface.co/Qwen/Qwen3-1.7B)
- [`llama.cpp`](https://github.com/ggml-org/llama.cpp)
- [PyBoy documentation](https://docs.pyboy.dk/)
- [Pokémon Red disassembly](https://github.com/pret/pokered)
- [AI Village Plays Pokemon: DEF CON Edition](https://defcon.outel.org/dcwp/dc34/activities/c-list/)
- [How Claude Plays Pokémon was made](https://www.josherich.me/podcast/latent-space/how-claude-plays-pok%C3%A9mon-was-made)
