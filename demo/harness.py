"""Bounded game control with Strands + a small local language model.

The bundled arena is an original, simplified battle simulator, not a ROM.
ROM mode exposes PyBoy inputs and symbol-based telemetry for experimentation.
"""
from __future__ import annotations

import argparse
import copy
import io
import json
import time
from collections import Counter, deque
from pathlib import Path
from urllib.parse import urlparse


TYPE_CHART = {
    ("water", "fire"): 2, ("water", "rock"): 2,
    ("fire", "grass"): 2, ("grass", "water"): 2,
    ("grass", "rock"): 2, ("electric", "water"): 2,
    ("fire", "water"): .5, ("water", "grass"): .5,
    ("grass", "fire"): .5, ("electric", "grass"): .5,
}


def monster(name, element, hp, moves):
    return dict(name=name, type=element, hp=hp, max_hp=hp, moves=moves)


class Arena:
    kind = "arena"
    label = "Simplified Pokémon battle simulator · no ROM"

    def __init__(self):
        self.team = [
            monster("Squirtle", "water", 64, [("Water Gun", "water", 16), ("Tackle", "normal", 12)]),
            monster("Bulbasaur", "grass", 64, [("Vine Whip", "grass", 16), ("Tackle", "normal", 12)]),
            monster("Charmander", "fire", 64, [("Ember", "fire", 16), ("Scratch", "normal", 12)]),
        ]
        self.opponents = [
            monster("Geodude", "rock", 55, [("Rock Throw", "rock", 9)]),
            monster("Oddish", "grass", 55, [("Absorb", "grass", 9)]),
            monster("Growlithe", "fire", 55, [("Ember", "fire", 9)]),
            monster("Poliwag", "water", 55, [("Water Gun", "water", 9)]),
        ]
        self.active = self.stage = self.turn = 0
        self.potions = 2
        self.status = "playing"
        self.events = ["Win four battles. The harness calculates type matchups; the model chooses actions."]

    @staticmethod
    def damage(move, target):
        return max(1, int(move[2] * TYPE_CHART.get((move[1], target["type"]), 1)))

    def observe(self):
        foe = self.opponents[min(self.stage, len(self.opponents) - 1)]
        player = self.team[self.active]
        return dict(kind=self.kind, label=self.label, status=self.status,
                    turn=self.turn, stage=self.stage, total_stages=len(self.opponents),
                    active=self.active, team=copy.deepcopy(self.team), opponent=copy.deepcopy(foe),
                    potions=self.potions, events=self.events[-6:],
                    legal_actions=self.actions() if self.status == "playing" else [])

    def actions(self):
        player, foe = self.team[self.active], self.opponents[self.stage]
        result = []
        for i, move in enumerate(player["moves"]):
            damage = self.damage(move, foe)
            reply = 0 if damage >= foe["hp"] else self.damage(foe["moves"][0], player)
            result.append(dict(id=f"move:{i}", label=move[0], damage=damage,
                               incoming_damage=reply, hp_after=max(0, player["hp"] - reply)))
        for i, member in enumerate(self.team):
            if i != self.active and member["hp"] > 0:
                reply = self.damage(foe["moves"][0], member)
                result.append(dict(id=f"switch:{i}", label=f"Switch to {member['name']}",
                                   best_next_damage=max(self.damage(m, foe) for m in member["moves"]),
                                   incoming_damage=reply, hp_after=max(0, member["hp"] - reply)))
        if self.potions and player["hp"] < player["max_hp"]:
            result.append(dict(id="heal", label="Potion (+35 HP)",
                               hp_after=max(0, min(player["max_hp"], player["hp"] + 35)
                                            - self.damage(foe["moves"][0], player))))
        return result

    def step(self, action):
        if action not in {x["id"] for x in self.actions()} or self.status != "playing":
            raise ValueError("Action is not legal in the current state")
        self.turn += 1
        foe = self.opponents[self.stage]
        if action.startswith("switch:"):
            self.active = int(action.split(":")[1])
            self.events.append(f"Switched to {self.team[self.active]['name']}.")
        elif action == "heal":
            p = self.team[self.active]
            p["hp"] = min(p["max_hp"], p["hp"] + 35)
            self.potions -= 1
            self.events.append(f"Healed {p['name']}.")
        else:
            p = self.team[self.active]
            move = p["moves"][int(action.split(":")[1])]
            damage = self.damage(move, foe)
            foe["hp"] = max(0, foe["hp"] - damage)
            self.events.append(f"{p['name']} used {move[0]}: {damage} damage.")
        if foe["hp"] == 0:
            self.events.append(f"Defeated {foe['name']}!")
            self.stage += 1
            if self.stage == len(self.opponents):
                self.status = "won"
            else:
                self.events.append(f"Next opponent: {self.opponents[self.stage]['name']}.")
            return
        p = self.team[self.active]
        hit = self.damage(foe["moves"][0], p)
        p["hp"] = max(0, p["hp"] - hit)
        self.events.append(f"{foe['name']} dealt {hit} damage.")
        if p["hp"] == 0:
            alive = [i for i, m in enumerate(self.team) if m["hp"] > 0]
            if alive:
                self.active = alive[0]
                self.events.append(f"Auto-selected surviving {self.team[self.active]['name']}.")
            else:
                self.status = "lost"
        if self.turn >= 40 and self.status == "playing":
            self.status = "budget_exhausted"

    def close(self):
        pass


class RomGame:
    kind = "rom"
    label = "PyBoy ROM experiment · full-game completion unverified"
    BUTTONS = ("up", "down", "left", "right", "a", "b", "start", "select", "wait")

    def __init__(self, rom, symbols, state=None, max_steps=200):
        from pyboy import PyBoy
        self.pyboy = PyBoy(str(rom), window="null", sound_emulated=False, symbols=str(symbols))
        self.pyboy.set_emulation_speed(0)
        if state:
            with open(state, "rb") as f:
                self.pyboy.load_state(f)
        else:
            self.pyboy.tick(120)
        self.turn = 0
        self.max_steps = max_steps
        self.status = "playing"
        self.events = ["Use a prepared checkpoint and matching .sym file for meaningful text-model control."]
        self.visited = Counter()
        self.checkpoint = None
        self.save_checkpoint()

    def read(self, name, width=1):
        try:
            _, address = self.pyboy.symbol_lookup(name)
            return int.from_bytes(bytes(self.pyboy.memory[address:address + width]), "big")
        except (ValueError, KeyError):
            return None

    def observe(self):
        labels = {"map": "wCurMap", "x": "wXCoord", "y": "wYCoord",
                  "in_battle": "wIsInBattle", "badges_bits": "wObtainedBadges",
                  "party_count": "wPartyCount"}
        telemetry = {k: self.read(v) for k, v in labels.items()}
        for field, symbol in [("lead_hp", "wPartyMon1HP"), ("lead_max_hp", "wPartyMon1MaxHP"),
                              ("enemy_hp", "wEnemyMonHP")]:
            telemetry[field] = self.read(symbol, 2)
        key = (telemetry["map"], telemetry["x"], telemetry["y"])
        return dict(kind=self.kind, label=self.label, status=self.status, turn=self.turn,
                    telemetry=telemetry, visits_here=self.visited[key], events=self.events[-6:],
                    screen="/api/screen", legal_actions=[dict(id=b, label=b) for b in self.BUTTONS]
                    if self.status == "playing" else [])

    def step(self, action):
        if self.status != "playing" or action not in self.BUTTONS:
            raise ValueError("Invalid or unavailable button")
        if action != "wait":
            self.pyboy.button(action, 8)
        self.pyboy.tick(24)
        self.turn += 1
        telemetry = self.observe()["telemetry"]
        key = (telemetry["map"], telemetry["x"], telemetry["y"])
        self.visited[key] += 1
        self.events.append(f"Pressed {action}; map {key[0]}, tile {key[1:]}")
        if self.turn >= self.max_steps:
            self.status = "budget_exhausted"

    def save_checkpoint(self):
        self.checkpoint = io.BytesIO()
        self.pyboy.save_state(self.checkpoint)

    def restore_checkpoint(self):
        self.checkpoint.seek(0)
        self.pyboy.load_state(self.checkpoint)
        self.turn = 0
        self.status = "playing"
        self.visited.clear()
        self.events.append("Restored checkpoint.")

    def screen_png(self):
        data = io.BytesIO()
        self.pyboy.screen.image.save(data, format="PNG")
        return data.getvalue()

    def close(self):
        self.pyboy.stop(save=False)


class Planner:
    def __init__(self, provider="local", endpoint="http://127.0.0.1:18081/v1",
                 model="pokemon-local", policy="pruned"):
        self.provider, self.endpoint, self.model, self.policy = provider, endpoint, model, policy
        self.history = deque(maxlen=4)
        self.calls = self.tokens = 0
        if policy not in {"pruned", "unfiltered"}:
            raise ValueError("Policy must be 'pruned' or 'unfiltered'")
        if provider == "local" and urlparse(endpoint).hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("Local mode requires a loopback model endpoint")

    def choose(self, observation):
        start = time.monotonic()
        actions = self.candidates(observation)
        if not actions:
            raise ValueError("No legal actions remain")
        if self.provider == "rules":
            action = self.rule_action(observation)
            return dict(action=action, reason="Deterministic baseline; no language model called.",
                        source="rules", seconds=0, tokens=0)
        from strands import Agent
        from strands.models.openai import OpenAIModel
        schema = {"type": "object", "properties": {
            "action": {"type": "string", "enum": [a["id"] for a in actions]},
            "reason": {"type": "string"}}, "required": ["action", "reason"], "additionalProperties": False}
        if self.provider == "bedrock":
            from strands.models import BedrockModel
            model = BedrockModel(model_id=self.model, max_tokens=100, temperature=0)
        else:
            model = OpenAIModel(client_args=dict(base_url=self.endpoint, api_key="local-demo",
                                                 timeout=30, max_retries=0),
                                model_id=self.model, params=dict(temperature=0, max_tokens=100,
                                response_format={"type": "json_schema", "json_schema": {
                                    "name": "game_action", "strict": True, "schema": schema}}))
        # A fresh, bounded request per turn. Game state and four decisions are the memory.
        agent = Agent(model=model, callback_handler=None, retry_strategy=None, system_prompt=(
            "You control a game. Choose exactly one legal action. Return JSON with action and a short reason. "
            "In the arena, win every battle while preserving HP. Damage forecasts are exact. "
            "Prefer a knockout. Switch if the new teammate's damage is much higher. "
            "Heal before fainting. Avoid repeated switches. Never invent game progress. "
            "In ROM mode, explore unvisited locations and advance dialogue with a. "
            "The screenshot is for the audience; you receive only telemetry. /no_think"))
        compact = {k: v for k, v in observation.items() if k not in {"label", "screen", "events"}}
        compact["legal_actions"] = actions
        if observation["kind"] == "arena" and self.policy == "pruned":
            # Strip full move lists: give the tiny model the exact decision table,
            # rather than making it reconcile several redundant representations.
            compact = dict(turn=observation["turn"], opponent_hp=observation["opponent"]["hp"],
                           active=observation["team"][observation["active"]]["name"],
                           actions=actions)
        prompt = json.dumps(dict(state=compact, recent=list(self.history)), separators=(",", ":"))
        self.calls += 1
        result = agent(prompt)
        raw = str(result).strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
        decision = json.loads(raw)
        if decision.get("action") not in {a["id"] for a in actions}:
            raise ValueError(f"Model returned an illegal action: {decision!r}")
        usage = result.metrics.accumulated_usage
        tokens = usage.get("totalTokens", 0)
        self.tokens += tokens
        self.history.append(dict(turn=observation["turn"], action=decision["action"]))
        return dict(action=decision["action"], reason=str(decision.get("reason", ""))[:300],
                    source=f"Strands / {self.provider} / {self.model}",
                    seconds=round(time.monotonic() - start, 3), tokens=tokens,
                    candidates=actions, filtered=len(observation["legal_actions"]) - len(actions))

    def candidates(self, obs):
        """Prune wasteful switches/heals; never secretly replace a model decision."""
        actions = obs["legal_actions"]
        if self.policy == "unfiltered":
            return actions
        if obs["kind"] != "arena" or not actions:
            return actions
        moves = [a for a in actions if a["id"].startswith("move:")]
        best = max(a["damage"] for a in moves)
        # An immediately available knockout needs no setup turn.
        if best >= obs["opponent"]["hp"]:
            return [a for a in moves if a["damage"] >= obs["opponent"]["hp"]]
        result = [a for a in moves if a["hp_after"] > 0]
        hp = obs["team"][obs["active"]]["hp"]
        for a in actions:
            if a["id"].startswith("switch:") and a["hp_after"] > 18 and a["best_next_damage"] > best:
                result.append(a)
            elif a["id"] == "heal" and hp <= 30:
                result.append(a)
        return result or moves

    @staticmethod
    def rule_action(obs):
        actions = obs["legal_actions"]
        if obs["kind"] != "arena":
            raise ValueError("Rules baseline only exists for the arena")
        moves = [a for a in actions if a["id"].startswith("move:")]
        best = max(moves, key=lambda a: a["damage"])
        if best["damage"] >= obs["opponent"]["hp"]:
            return best["id"]
        heal = next((a for a in actions if a["id"] == "heal"), None)
        if best["hp_after"] <= 18 and heal:
            return "heal"
        switches = [a for a in actions if a["id"].startswith("switch:") and a["hp_after"] > 18]
        if switches:
            switch = max(switches, key=lambda a: a["best_next_damage"])
            if switch["best_next_damage"] > best["damage"] * 1.5:
                return switch["id"]
        return best["id"]


def evaluate(provider, endpoint, model, policy="pruned"):
    game, planner = Arena(), Planner(provider, endpoint, model, policy)
    records = []
    while game.status == "playing":
        before = game.observe()
        decision = planner.choose(before)
        game.step(decision["action"])
        record = dict(before=before, decision=decision, after=game.observe())
        records.append(record)
        print(json.dumps(dict(turn=game.turn, **decision)), flush=True)
    result = dict(status=game.status, provider=provider, model=model, policy=policy, turns=game.turn,
                  calls=planner.calls, tokens=planner.tokens,
                  seconds=round(sum(r["decision"]["seconds"] for r in records), 3), records=records)
    suffix = "-unfiltered" if policy == "unfiltered" else ""
    out = Path(__file__).parent / "runs" / f"evaluation-{provider}{suffix}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(result, indent=2))
    print(json.dumps({k: v for k, v in result.items() if k != "records"}))
    return 0 if game.status == "won" else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", choices=["local", "rules", "bedrock"], default="local")
    parser.add_argument("--endpoint", default="http://127.0.0.1:18081/v1")
    parser.add_argument("--model", default="pokemon-local")
    parser.add_argument("--policy", choices=["pruned", "unfiltered"], default="pruned")
    args = parser.parse_args()
    raise SystemExit(evaluate(args.provider, args.endpoint, args.model, args.policy))
