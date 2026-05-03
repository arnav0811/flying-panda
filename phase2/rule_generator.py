"""
Component 4 (GRAY box in architecture diagram): Rule Generator

When the Action Interpreter classifies a player input as 'novel', this module
runs. It generates:

  1. A new ActionRule for the verb (preconditions, effects, target type)
  2. Any new game objects required to satisfy the preconditions, placed in
     a sensible existing room (or a new room, if needed)
  3. Any new rooms required (intermediate or specialty locations)
  4. Retroactive updates to EXISTING rules when the new objects/state vars
     change how older actions should behave

The cascade is bounded:
  - Maximum 3 levels of recursion (climb -> needs ladder -> ladder is locked
    in shed -> needs key -> key on janitor -> END).
  - Maximum 5 new objects + 3 new rooms per top-level cascade.
  - Each generated rule is returned to the engine and the engine decides
    whether to actually add it (commonsense check via the LLM).

The top-level function returns a 'cascade plan' the engine applies atomically.
"""

import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from llm import call_llm_json
from phase2.world_models import (
    WorldState, ActionRule, GameObject, Room
)


SYSTEM_PROMPT = """You are the rule-generation engine for a text adventure
murder mystery. When a player tries to do something the game doesn't have
rules for yet (e.g. "scale the wall", "pick the lock", "set fire to X"),
you invent the rules on the fly.

You must:
- Decide what preconditions the action needs (objects, state variables, location).
- Create any required objects/rooms that don't exist yet, in sensible places.
- Identify retroactive updates: when a new state variable is introduced
  (like 'leaning_against' for a ladder), find existing rules that should
  now check that variable.

You always respond in valid JSON. Never invent a shortcut that lets the player
skip the murder mystery. Make them work for it."""

MAX_CASCADE_DEPTH = 3
MAX_NEW_OBJECTS = 5
MAX_NEW_ROOMS = 3


def generate_rule(action_name: str, raw_target: str | None, player_input: str,
                  world_state: WorldState, depth: int = 0) -> dict:
    """
    Top-level entry. Returns a cascade plan dict like:

      {
        "new_rules":            [ActionRule, ...],
        "updated_rules":        [{"rule_name": "pick_up", "new_preconditions": [...], "reason": "..."}],
        "new_objects":          [GameObject, ...],
        "new_rooms":            [Room, ...],
        "subquest_summary":     "human-readable description of the side-quest the player just unlocked",
        "narrative":            "what the player sees in response to their action",
        "ready_to_execute":     bool,    # if all preconditions are already met
        "missing_preconditions":[strings],
        "depth":                int,
        "blocked":              bool,    # if cap was hit
      }

    The engine inspects this and:
      - applies new_rules / new_objects / new_rooms / updated_rules to world state
      - prints subquest_summary + narrative to the player
      - if ready_to_execute, also runs the new rule's effects
    """
    if depth >= MAX_CASCADE_DEPTH:
        return {
            "new_rules": [], "updated_rules": [], "new_objects": [], "new_rooms": [],
            "subquest_summary": "",
            "narrative": "(That cascade is getting too deep. Try something simpler.)",
            "ready_to_execute": False, "missing_preconditions": [],
            "depth": depth, "blocked": True,
        }

    # ---- Step 1: ask the LLM what the new rule + cascading additions look like
    plan_json = _ask_for_plan(action_name, raw_target, player_input, world_state)

    # ---- Step 2: enforce caps
    if len(plan_json.get("new_objects", [])) > MAX_NEW_OBJECTS:
        plan_json["new_objects"] = plan_json["new_objects"][:MAX_NEW_OBJECTS]
    if len(plan_json.get("new_rooms", [])) > MAX_NEW_ROOMS:
        plan_json["new_rooms"] = plan_json["new_rooms"][:MAX_NEW_ROOMS]

    # ---- Step 3: build the typed structures
    new_rules = []
    for r in plan_json.get("new_rules", []):
        new_rules.append(ActionRule(
            name=r["name"],
            description=r.get("description", ""),
            preconditions=r.get("preconditions", []),
            effects=r.get("effects", []),
            requires_target=r.get("requires_target", False),
            valid_targets=r.get("valid_targets", []),
            is_base=False,
            generated_at_turn=world_state.turn_count,
        ))

    new_objects = []
    for o in plan_json.get("new_objects", []):
        new_objects.append(GameObject(
            id=o["id"],
            name=o["name"],
            description=o.get("description", ""),
            location=o["location"],
            state=o.get("state", {"weight": "light", "is_destructible": True}),
            aliases=o.get("aliases", []),
            is_clue=False,        # generated objects are never story clues
            is_critical_evidence=False,
        ))

    new_rooms = []
    for r in plan_json.get("new_rooms", []):
        new_rooms.append(Room(
            id=r["id"],
            name=r["name"],
            description=r.get("description", ""),
            connections=r.get("connections", {}),
            state=r.get("state", {}),
        ))

    return {
        "new_rules": new_rules,
        "updated_rules": plan_json.get("updated_rules", []),
        "new_objects": new_objects,
        "new_rooms": new_rooms,
        "subquest_summary": plan_json.get("subquest_summary", ""),
        "narrative": plan_json.get("narrative", ""),
        "ready_to_execute": plan_json.get("ready_to_execute", False),
        "missing_preconditions": plan_json.get("missing_preconditions", []),
        "depth": depth,
        "blocked": False,
    }


# ---------------------------------------------------------------------------
# LLM call
# ---------------------------------------------------------------------------

def _ask_for_plan(action_name: str, raw_target: str | None, player_input: str,
                  world_state: WorldState) -> dict:
    rules_summary = _existing_rules_summary(world_state)
    objects_summary = _world_objects_summary(world_state)
    rooms_summary = _rooms_summary(world_state)
    inventory_summary = _inventory_summary(world_state)
    current_room = world_state.get_current_room()

    user_prompt = f"""The player is trying a novel action that the game doesn't
have rules for yet. Generate the rule, the objects/rooms needed, and any
retroactive updates to existing rules.

Player input (raw): "{player_input}"
Proposed action name: {action_name}
Target: {raw_target}
Current room: {current_room.id} ({current_room.name})
Player inventory: {inventory_summary}

Existing rules (do NOT redefine these — but you MAY add preconditions to them):
{rules_summary}

Existing rooms:
{rooms_summary}

Existing objects in the world (a sample):
{objects_summary}

Generate a JSON plan:
{{
  "new_rules": [
    {{
      "name": "snake_case_action",
      "description": "one sentence",
      "preconditions": [
        "human-readable condition 1",
        "human-readable condition 2"
      ],
      "effects": [
        "human-readable effect 1"
      ],
      "requires_target": true|false,
      "valid_targets": ["object_or_npc_ids OR description like 'any vertical surface'"]
    }}
  ],
  "new_objects": [
    {{
      "id": "snake_case_id",
      "name": "display name",
      "description": "what the player sees",
      "location": "an EXISTING room_id, or a new room_id from new_rooms below",
      "state": {{ "weight": "light|medium|heavy", "is_destructible": true, "is_locked": false }},
      "aliases": ["short_name"]
    }}
  ],
  "new_rooms": [
    {{
      "id": "snake_case_id",
      "name": "Display Name",
      "description": "atmospheric 2-sentence description",
      "connections": {{ "north": "existing_room_id" }},
      "state": {{}}
    }}
  ],
  "updated_rules": [
    {{
      "rule_name": "name of existing rule",
      "new_preconditions": ["additional precondition to add"],
      "new_effects": ["additional effect to add"],
      "reason": "why this update is needed (e.g., 'because the new ladder has a leaning_against state, the drop rule must clear it before allowing the drop')"
    }}
  ],
  "subquest_summary": "brief description of the side-quest the player just opened up (1-2 sentences)",
  "narrative": "what the player sees printed to them right now (2-3 sentences). Should describe the system noticing what they want to do, mention the missing prerequisites, and gesture at where to find them.",
  "ready_to_execute": false if the new rule has missing preconditions, true if all are met,
  "missing_preconditions": ["which preconditions of the new rule are not yet satisfied"]
}}

CRITICAL RULES:
- Do NOT generate any object that would short-circuit the murder mystery
  (no "confession letter from the criminal", no "list of all the clues").
- If the player's action would let them skip steps, make them work for it
  by adding preconditions that require existing prerequisites to be done first.
- New rooms should connect to AT LEAST ONE existing room.
- If the player tries to use an object that exists, prefer "ready_to_execute": true
  rather than inventing more obstacles.
- Retroactive updates: any time you add a NEW state variable to a NEW or
  existing object (like 'leaning_against' on a ladder), check whether
  pick_up / drop / move / examine should be updated to reference it. If yes,
  add an entry to updated_rules with a reason."""

    return call_llm_json(SYSTEM_PROMPT, user_prompt, temperature=0.5)


# ---------------------------------------------------------------------------
# Application of the plan to world state — called by the game engine
# ---------------------------------------------------------------------------

def apply_plan(plan: dict, world_state: WorldState) -> list:
    """
    Apply a cascade plan to the world. Returns a list of human-readable
    log lines describing what changed (so the engine can print them).
    """
    log = []

    # Add new rooms first so objects can be placed in them
    for room in plan["new_rooms"]:
        if room.id in world_state.rooms:
            continue
        world_state.rooms[room.id] = room
        # Make connections bidirectional
        for direction, target_room_id in list(room.connections.items()):
            if target_room_id in world_state.rooms:
                opposite = _opposite_direction(direction)
                if opposite and opposite not in world_state.rooms[target_room_id].connections:
                    world_state.rooms[target_room_id].connections[opposite] = room.id
        log.append(f"NEW ROOM: {room.name} ({room.id}) connected via {list(room.connections.keys())}")

    # Add new objects
    for obj in plan["new_objects"]:
        if obj.id in world_state.objects:
            continue
        # Validate location exists
        if obj.location in world_state.rooms:
            world_state.rooms[obj.location].object_ids.append(obj.id)
            world_state.objects[obj.id] = obj
            log.append(f"NEW OBJECT: {obj.name} ({obj.id}) placed in {obj.location}")

    # Apply retroactive updates
    for upd in plan.get("updated_rules", []):
        rule_name = upd.get("rule_name")
        if rule_name in world_state.rules:
            rule = world_state.rules[rule_name]
            for pre in upd.get("new_preconditions", []):
                if pre not in rule.preconditions:
                    rule.preconditions.append(pre)
            for eff in upd.get("new_effects", []):
                if eff not in rule.effects:
                    rule.effects.append(eff)
            log.append(f"UPDATED RULE: '{rule_name}' — {upd.get('reason', 'no reason given')}")

    # Add new rules
    for rule in plan["new_rules"]:
        world_state.rules[rule.name] = rule
        log.append(f"NEW RULE: '{rule.name}' — {rule.description}")

    return log


def _opposite_direction(d: str) -> str | None:
    pairs = {
        "north": "south", "south": "north",
        "east": "west", "west": "east",
        "up": "down", "down": "up",
        "northeast": "southwest", "southwest": "northeast",
        "northwest": "southeast", "southeast": "northwest",
    }
    return pairs.get(d.lower())


# ---------------------------------------------------------------------------
# Prompt context helpers
# ---------------------------------------------------------------------------

def _existing_rules_summary(world_state: WorldState) -> str:
    lines = []
    for rule in world_state.rules.values():
        pre = "; ".join(rule.preconditions) if rule.preconditions else "(none)"
        lines.append(f"  - {rule.name}: {rule.description}  PRECONDITIONS: {pre}")
    return "\n".join(lines)


def _world_objects_summary(world_state: WorldState) -> str:
    sample = list(world_state.objects.values())[:20]
    return "\n".join(
        f"  - {o.id} ('{o.name}', in {o.location}, weight={o.state.get('weight', '?')})"
        for o in sample
    )


def _rooms_summary(world_state: WorldState) -> str:
    return "\n".join(
        f"  - {rid} ('{r.name}'): connections={list(r.connections.keys())}"
        for rid, r in world_state.rooms.items()
    )


def _inventory_summary(world_state: WorldState) -> str:
    if not world_state.inventory:
        return "(empty)"
    return ", ".join(world_state.objects[oid].name for oid in world_state.inventory if oid in world_state.objects)
