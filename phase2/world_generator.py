"""
Component 1 (GREEN box in architecture diagram): World Generator

Reads a Phase 1 crime schema + plot points and produces an initial WorldState:
- A graph of rooms (with intermediate rooms inserted where commonsense demands)
- Game objects placed in rooms, with clue objects mapped to Phase 1 clue ids
- NPCs (suspects + a few extras) placed in rooms with their alibis intact
- A base set of action rules: move, look, examine, pick_up, drop, talk, use,
  give, inventory, accuse

The base rules are NOT the only rules the player can use. The Rule Generator
(component 4) adds new rules at runtime when the player tries something novel.
"""

import os
import sys
import json

# allow importing Phase 1 modules from the parent dir
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from llm import call_llm_json
from phase2.world_models import (
    Room, GameObject, NPC, ActionRule, WorldState
)


WORLD_GEN_SYSTEM = """You are a game world architect for a text adventure murder mystery.
You take a generated mystery story and turn it into a playable text-game world:
rooms with descriptions, objects placed in rooms, NPCs in rooms, sensible
adjacency between locations. You always respond in valid JSON."""


def generate_world(crime_schema: dict, plot_points: list, starting_room_hint: str = None) -> WorldState:
    """
    Main entry point. Returns a fully populated WorldState.

    Strategy:
      1. Ask the LLM to extract distinct locations from plot points and connect
         them into a sensible graph (with intermediate hallway/lobby rooms).
      2. Ask the LLM to place objects: clues become specific game objects with
         clue_id set so the engine can credit them when discovered. Red herrings
         become objects too. We add a few non-clue ambient objects per room.
      3. Suspects from the schema become NPCs placed in plausible rooms.
      4. We hand-write the base action rules (these never change at runtime).
    """
    state = WorldState()
    state.crime_schema = crime_schema
    state.plot_points = plot_points

    rooms_data = _generate_rooms(crime_schema, plot_points)
    objects_data = _generate_objects(crime_schema, plot_points, rooms_data)
    npcs_data = _generate_npcs(crime_schema, rooms_data)

    # Materialize rooms
    for r in rooms_data["rooms"]:
        room = Room(
            id=r["id"],
            name=r["name"],
            description=r["description"],
            connections=r.get("connections", {}),
            state=r.get("state", {}),
        )
        state.rooms[room.id] = room

    # Place objects
    for o in objects_data["objects"]:
        obj = GameObject(
            id=o["id"],
            name=o["name"],
            description=o["description"],
            location=o["location"],
            state=o.get("state", {"weight": "light", "is_destructible": True}),
            aliases=o.get("aliases", []),
            is_clue=o.get("is_clue", False),
            clue_id=o.get("clue_id"),
            is_critical_evidence=o.get("is_critical_evidence", False),
            is_red_herring=o.get("is_red_herring", False),
            red_herring_id=o.get("red_herring_id"),
        )
        state.objects[obj.id] = obj
        if obj.location in state.rooms:
            state.rooms[obj.location].object_ids.append(obj.id)

    # Place NPCs
    for n in npcs_data["npcs"]:
        npc = NPC(
            id=n["id"],
            name=n["name"],
            description=n["description"],
            location=n["location"],
            state=n.get("state", {"alive": True, "willing_to_talk": True}),
            is_suspect=n.get("is_suspect", False),
            suspect_data=n.get("suspect_data", {}),
            dialogue_topics=n.get("dialogue_topics", []),
            is_critical=n.get("is_critical", False),
        )
        state.npcs[npc.id] = npc
        if npc.location in state.rooms:
            state.rooms[npc.location].npc_ids.append(npc.id)

    # Pick a starting room — first room in the rooms list, or a hinted one
    state.player_location = starting_room_hint or rooms_data["rooms"][0]["id"]
    state.rooms[state.player_location].visited = True

    # Base action rules (hand-written; these are the bedrock)
    state.rules = _base_rules()

    return state


# ---------------------------------------------------------------------------
# Internal LLM-driven generators
# ---------------------------------------------------------------------------

def _generate_rooms(crime_schema: dict, plot_points: list) -> dict:
    """Ask the LLM to extract locations from the story and connect them sensibly."""
    setting = crime_schema["setting"]
    plot_titles = "\n".join(f"- {p['title']}: {p['narrative'][:200]}..." for p in plot_points[:10])

    prompt = f"""The setting is: {setting}

Here are some scenes from the story:
{plot_titles}

Generate a graph of rooms for a text-adventure version of this story.

Requirements:
- 5 to 8 rooms total.
- Each room should be a distinct location relevant to the investigation.
- Add 1-2 intermediate locations (hallway, lobby, parking lot) so adjacent rooms
  in the graph make spatial sense.
- Connections must be bidirectional and use cardinal directions or stairs/elevator.
- Include a starting room where the detective begins (e.g. an entrance/lobby).

Respond with JSON in this exact shape:
{{
  "rooms": [
    {{
      "id": "snake_case_id",
      "name": "Display Name",
      "description": "2-3 sentence atmospheric description visible to the player on entry",
      "connections": {{ "north": "other_room_id", "east": "other_room_id" }},
      "state": {{ "is_lit": true, "is_locked": false }}
    }}
  ]
}}

Make sure every connection refers to a room that actually exists in the list,
and that connections are mutually consistent (if room A says "north: B" then
room B should say "south: A")."""

    return call_llm_json(WORLD_GEN_SYSTEM, prompt, temperature=0.7)


def _generate_objects(crime_schema: dict, plot_points: list, rooms_data: dict) -> dict:
    """Place objects in rooms. Clues map to specific clue_ids so the engine
    can credit them when the player discovers them."""
    rooms_summary = "\n".join(f"- {r['id']}: {r['name']}" for r in rooms_data["rooms"])
    clues = crime_schema["evidence_chain"]
    clues_summary = "\n".join(
        f"  Clue {c['id']}: {c['description']} "
        f"(discovered via: {c['discovery_method']}, points to: {c['points_to']})"
        for c in clues
    )
    rh_summary = "\n".join(
        f"  Red Herring {rh['id']}: {rh['planted_evidence']} "
        f"(misleads toward: {rh['target_suspect']})"
        for rh in crime_schema.get("red_herrings", [])
    )

    prompt = f"""You are placing physical objects into a murder mystery game world.

Available rooms:
{rooms_summary}

Story context:
- Victim: {crime_schema['victim']}
- Method: {crime_schema['method']}
- Setting: {crime_schema['setting']}

Clues from the story (each MUST be represented by exactly one game object):
{clues_summary}

Red herrings (each MUST be represented by exactly one game object):
{rh_summary}

For each clue and each red herring, create a game object. Place it in a room
where it would plausibly be found. Then add 4-6 ambient objects (mundane things
like a desk, a coffee maker, a bookshelf) to make the world feel real.

Respond with JSON:
{{
  "objects": [
    {{
      "id": "snake_case_id",
      "name": "display name",
      "description": "what the player sees when they examine it. For clue objects, this should be evocative but NOT directly state the clue's content — examining it is what reveals the clue.",
      "location": "room_id from the list above",
      "state": {{
        "weight": "light|medium|heavy",
        "is_destructible": true,
        "is_locked": false
      }},
      "aliases": ["short_name", "alt_name"],
      "is_clue": true|false,
      "clue_id": <int from clues list, or null>,
      "is_critical_evidence": true if this object reveals a clue,
      "is_red_herring": true|false,
      "red_herring_id": "<rh id from list, or null>"
    }}
  ]
}}

Rules:
- Every clue from the list must have exactly one corresponding object with that clue_id.
- Every red herring must have exactly one corresponding object with that red_herring_id.
- Clue objects MUST have is_critical_evidence=true (Story Guard protects them).
- Aliases should be short common nouns the player might type (e.g. "mug", "notebook")."""

    return call_llm_json(WORLD_GEN_SYSTEM, prompt, temperature=0.7)


def _generate_npcs(crime_schema: dict, rooms_data: dict) -> dict:
    """Suspects become NPCs. Place them in rooms tied to their role."""
    rooms_summary = "\n".join(f"- {r['id']}: {r['name']}" for r in rooms_data["rooms"])
    suspects_json = json.dumps(crime_schema["suspects"], indent=2)
    criminal_name = crime_schema.get("criminal_name", "")

    prompt = f"""You are placing characters into a murder mystery game world.

Available rooms:
{rooms_summary}

Suspects (one of them is the criminal — but the player will find that out
through investigation, not narration):
{suspects_json}

Create one NPC per suspect. Place each one in a plausible room based on their
role. Their description should mention what they look like and what they're
doing right now, but NOT reveal their guilt.

Important: the NPC named "{criminal_name}" is the criminal — set is_critical=true
so the engine prevents them from being killed before the resolution.

Respond with JSON:
{{
  "npcs": [
    {{
      "id": "snake_case_id (use last name if possible)",
      "name": "Full Name",
      "description": "1-2 sentence physical/behavioral description visible when entering their room",
      "location": "room_id",
      "state": {{
        "alive": true,
        "willing_to_talk": true,
        "intimidated": false,
        "interrogated_count": 0
      }},
      "is_suspect": true,
      "suspect_data": {{
        "role": "...", "alibi": "...", "motive": "...",
        "means": "...", "alibi_is_false": false
      }},
      "dialogue_topics": ["the_victim", "the_night_of", "their_alibi", "their_relationship_with_victim"],
      "is_critical": true if this is the criminal else false
    }}
  ]
}}"""

    return call_llm_json(WORLD_GEN_SYSTEM, prompt, temperature=0.7)


# ---------------------------------------------------------------------------
# Base action rules — hand-written, never modified at runtime
# ---------------------------------------------------------------------------

def _base_rules() -> dict:
    """The starting set of action rules. Generated rules are added on top."""
    rules = [
        ActionRule(
            name="look",
            description="Look around the current room. Lists objects, NPCs, and exits.",
            preconditions=["player is in a room"],
            effects=["display current room description"],
            requires_target=False,
            is_base=True,
        ),
        ActionRule(
            name="examine",
            description="Look closely at an object or NPC.",
            preconditions=[
                "target is in the current room OR in inventory",
                "target is visible (not hidden inside a closed container)",
            ],
            effects=[
                "display target description",
                "if target is_clue and player has not yet discovered clue_id: discover the clue",
                "if target is_red_herring: mark as encountered",
            ],
            requires_target=True,
            is_base=True,
        ),
        ActionRule(
            name="pick_up",
            description="Pick up an object and put it in inventory.",
            preconditions=[
                "target is in the current room",
                "target is portable (state.weight in {light, medium})",
                "target is not nailed down or affixed",
            ],
            effects=["move target to inventory"],
            requires_target=True,
            is_base=True,
        ),
        ActionRule(
            name="drop",
            description="Drop an object from inventory into the current room.",
            preconditions=["target is in inventory"],
            effects=["move target to current room"],
            requires_target=True,
            is_base=True,
        ),
        ActionRule(
            name="move",
            description="Move to an adjacent room. Direction is the target.",
            preconditions=[
                "current room has a connection in the named direction",
                "the connecting passage is not locked",
            ],
            effects=["update player_location to the connected room"],
            requires_target=True,
            is_base=True,
        ),
        ActionRule(
            name="talk",
            description="Speak with an NPC about a topic from their dialogue_topics.",
            preconditions=[
                "target NPC is in the current room",
                "NPC.state.alive == true",
                "NPC.state.willing_to_talk == true",
            ],
            effects=[
                "NPC responds with information about the topic",
                "may reveal a clue if the topic and NPC's knowledge align",
                "may debunk a red herring if the conversation does so",
            ],
            requires_target=True,
            is_base=True,
        ),
        ActionRule(
            name="use",
            description="Use an object, optionally on another object or NPC.",
            preconditions=["target is in inventory or in the current room"],
            effects=["effect depends on target — may reveal a clue or unlock something"],
            requires_target=True,
            is_base=True,
        ),
        ActionRule(
            name="give",
            description="Give an object from inventory to an NPC.",
            preconditions=[
                "target object is in inventory",
                "target NPC is in the current room",
            ],
            effects=["move object from inventory to npc:<id>"],
            requires_target=True,
            is_base=True,
        ),
        ActionRule(
            name="inventory",
            description="List the objects you are carrying.",
            preconditions=[],
            effects=["display inventory"],
            requires_target=False,
            is_base=True,
        ),
        ActionRule(
            name="accuse",
            description="Accuse an NPC of being the murderer. Ends the game.",
            preconditions=[
                "discovered_clues count >= accusation_threshold",
                "target NPC is a suspect",
            ],
            effects=[
                "if target is the criminal: outcome = won",
                "if target is innocent: outcome = lost",
                "set game_over = true",
            ],
            requires_target=True,
            is_base=True,
        ),
        ActionRule(
            name="help",
            description="Show available base actions.",
            preconditions=[],
            effects=["print list of base verbs"],
            requires_target=False,
            is_base=True,
        ),
    ]
    return {r.name: r for r in rules}
