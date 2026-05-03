"""
Component 3 (PURPLE box in architecture diagram): Action Interpreter

Translates free-text player input into a structured action the game engine
can execute. The output is a single dict with one of three classifications:

  - known        : maps to an existing rule. Engine checks preconditions
                   and applies effects.
  - novel        : doesn't match any rule. The Rule Generator (component 4)
                   gets invoked to JIT-create the rule.
  - impossible   : violates basic commonsense (e.g., "fly to the moon"
                   in a lab setting). Engine rejects with a reason.

Special cases:
  - story_advancing flag: set when the action would conclude the mystery
    (e.g. "accuse <suspect>"). Engine routes to the Story Guard before execution.
  - resolved_target: the canonical id of the object/NPC the player was
    talking about. Lets the player type loose strings like "the mug" or
    "Reynolds" and have it resolve correctly.
"""

import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from llm import call_llm_json
from phase2.world_models import WorldState


SYSTEM_PROMPT = """You are the parser for a text adventure game's action layer.
You read the player's free-text input and the current world state, then decide
what action they're trying to perform. You always respond in valid JSON.

You should be generous in interpreting natural language — "go up the stairs",
"head north", and "n" can all mean the same move action. But you should be
strict about commonsense: a player can't fly without wings, can't see in
total darkness without a light source, etc."""


def interpret(player_input: str, world_state: WorldState) -> dict:
    """
    Returns a dict shaped like:
      {
        "classification": "known" | "novel" | "impossible",
        "action_name": str,                # canonical name; for novel actions, a snake_case proposal
        "raw_target": str | None,          # string the player typed
        "resolved_target_id": str | None,  # id of object/NPC if found
        "resolved_target_type": "object"|"npc"|"direction"|"suspect"|null,
        "story_advancing": bool,           # accuse / final confrontation / etc.
        "reasoning": str,                  # one short sentence
        "impossible_reason": str | None    # only set when classification == impossible
      }
    """
    # First pass: try to resolve common patterns locally without an LLM call.
    # Saves money and latency on the most common inputs.
    quick = _quick_match(player_input, world_state)
    if quick is not None:
        return quick

    # Otherwise, ask the LLM.
    rules_summary = _rules_summary(world_state)
    visible_objects = _visible_objects_summary(world_state)
    visible_npcs = _visible_npcs_summary(world_state)
    exits = _exits_summary(world_state)

    user_prompt = f"""Current world state:
- Player is in: {world_state.player_location} ({world_state.get_current_room().name})
- Exits: {exits}
- Visible objects: {visible_objects}
- NPCs in this room: {visible_npcs}
- Inventory: {[world_state.objects[oid].name for oid in world_state.inventory] or 'empty'}
- Discovered clues: {sorted(list(world_state.discovered_clues))} of {len(world_state.crime_schema.get('evidence_chain', []))}

Available actions (rules currently in the game engine):
{rules_summary}

Player input: "{player_input}"

Classify this input and respond as JSON:
{{
  "classification": "known" | "novel" | "impossible",
  "action_name": "the canonical action name (one of the available actions, OR a new snake_case name if novel)",
  "raw_target": "the object/npc/direction the player is targeting, as a string (or null)",
  "story_advancing": true if the action is an accusation or final reveal,
  "reasoning": "one sentence explaining your classification",
  "impossible_reason": "only if classification is impossible: a brief in-world explanation"
}}

Guidelines:
- "known" if the input maps to one of the available actions (even loosely).
  Map "look around", "where am I", "describe" -> "look".
  Map "n", "north", "go north", "head north" -> "move" with target "north".
  Map "examine X", "look at X", "inspect X", "study X" -> "examine".
  Map "take X", "grab X", "pick up X" -> "pick_up".
  Map "talk to X", "ask X about Y", "interrogate X" -> "talk".
  Map "I accuse X", "X is the murderer", "arrest X" -> "accuse" (story_advancing=true).

- "novel" if the input describes a real action that doesn't fit any existing
  rule (e.g., "climb through the window", "pick the lock", "set fire to X",
  "search the desk drawers"). Pick a snake_case action_name.

- "impossible" only if the action violates physical/commonsense law given
  the setting (e.g., "fly to mars", "summon a dragon", "teleport"). Be
  generous — most things players try are at least conceivable."""

    response = call_llm_json(SYSTEM_PROMPT, user_prompt, temperature=0.3)

    # Resolve target id from the raw target string
    response["resolved_target_id"] = None
    response["resolved_target_type"] = None
    if response.get("raw_target"):
        target_str = response["raw_target"]
        # try directions first
        if target_str.lower() in {"north", "south", "east", "west", "up", "down",
                                   "northeast", "northwest", "southeast", "southwest",
                                   "ne", "nw", "se", "sw", "n", "s", "e", "w", "u", "d"}:
            response["resolved_target_id"] = _normalize_direction(target_str)
            response["resolved_target_type"] = "direction"
        else:
            obj = world_state.find_object_by_name(target_str)
            if obj:
                response["resolved_target_id"] = obj.id
                response["resolved_target_type"] = "object"
            else:
                npc = world_state.find_npc_by_name(target_str)
                if npc:
                    response["resolved_target_id"] = npc.id
                    response["resolved_target_type"] = "npc"

    return response


# ---------------------------------------------------------------------------
# Quick local matching for the common cases
# ---------------------------------------------------------------------------

_DIRECTION_WORDS = {
    "n": "north", "s": "south", "e": "east", "w": "west",
    "u": "up", "d": "down",
    "ne": "northeast", "nw": "northwest", "se": "southeast", "sw": "southwest",
    "north": "north", "south": "south", "east": "east", "west": "west",
    "up": "up", "down": "down",
    "northeast": "northeast", "northwest": "northwest",
    "southeast": "southeast", "southwest": "southwest",
}


def _normalize_direction(s: str) -> str:
    return _DIRECTION_WORDS.get(s.lower().strip(), s.lower().strip())


def _quick_match(player_input: str, world_state: WorldState) -> dict | None:
    """Match obvious commands without an LLM call. Returns None if no match."""
    text = player_input.lower().strip()
    tokens = text.split()
    if not tokens:
        return None

    # Standalone direction
    if len(tokens) == 1 and tokens[0] in _DIRECTION_WORDS:
        d = _normalize_direction(tokens[0])
        return _build_response("known", "move", tokens[0], d, "direction",
                               story_advancing=False, reasoning="direction word")

    # "go <direction>" / "head <direction>" / "move <direction>"
    if len(tokens) == 2 and tokens[0] in {"go", "head", "move", "walk", "run"} and tokens[1] in _DIRECTION_WORDS:
        d = _normalize_direction(tokens[1])
        return _build_response("known", "move", tokens[1], d, "direction",
                               story_advancing=False, reasoning="movement command")

    # "look" / "look around"
    if text in {"look", "look around", "l", "describe", "where am i", "where am i?"}:
        return _build_response("known", "look", None, None, None,
                               story_advancing=False, reasoning="look command")

    # "inventory" / "i"
    if text in {"inventory", "i", "inv"}:
        return _build_response("known", "inventory", None, None, None,
                               story_advancing=False, reasoning="inventory command")

    # "help"
    if text in {"help", "?"}:
        return _build_response("known", "help", None, None, None,
                               story_advancing=False, reasoning="help command")

    return None


def _build_response(classification, action_name, raw_target, resolved_id, resolved_type,
                    story_advancing=False, reasoning="", impossible_reason=None):
    return {
        "classification": classification,
        "action_name": action_name,
        "raw_target": raw_target,
        "resolved_target_id": resolved_id,
        "resolved_target_type": resolved_type,
        "story_advancing": story_advancing,
        "reasoning": reasoning,
        "impossible_reason": impossible_reason,
    }


# ---------------------------------------------------------------------------
# Helpers for the prompt
# ---------------------------------------------------------------------------

def _rules_summary(world_state: WorldState) -> str:
    lines = []
    for rule in world_state.rules.values():
        target_part = " <target>" if rule.requires_target else ""
        lines.append(f"  - {rule.name}{target_part}: {rule.description}")
    return "\n".join(lines)


def _visible_objects_summary(world_state: WorldState) -> str:
    objs = world_state.objects_in_room()
    if not objs:
        return "(none)"
    return ", ".join(f"{o.name} (id={o.id})" for o in objs)


def _visible_npcs_summary(world_state: WorldState) -> str:
    npcs = world_state.npcs_in_room()
    if not npcs:
        return "(none)"
    return ", ".join(f"{n.name} (id={n.id})" for n in npcs)


def _exits_summary(world_state: WorldState) -> str:
    room = world_state.get_current_room()
    if not room or not room.connections:
        return "(none)"
    return ", ".join(f"{d} -> {rid}" for d, rid in room.connections.items())
