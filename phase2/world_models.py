"""
Data structures for the interactive game world.

Every piece of the world (rooms, objects, NPCs, action rules) is a dataclass
defined here. The game engine and the four LLM components (World Generator,
Action Interpreter, Rule Generator, Story Guard) all read and write these
structures.

The WorldState class at the bottom is the single source of truth for the
game while it's running. Saving WorldState to JSON gives a complete snapshot
that can be reloaded.
"""

from dataclasses import dataclass, field
from typing import Optional
import json


# ---------------------------------------------------------------------------
# Rooms
# ---------------------------------------------------------------------------

@dataclass
class Room:
    """A single location in the world. Rooms are nodes in the navigation graph."""
    id: str
    name: str
    description: str
    connections: dict = field(default_factory=dict)  # direction -> room_id
    object_ids: list = field(default_factory=list)
    npc_ids: list = field(default_factory=list)
    state: dict = field(default_factory=dict)        # arbitrary flags (lit, locked, etc.)
    visited: bool = False

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "connections": self.connections,
            "object_ids": self.object_ids,
            "npc_ids": self.npc_ids,
            "state": self.state,
            "visited": self.visited,
        }


# ---------------------------------------------------------------------------
# Objects
# ---------------------------------------------------------------------------

@dataclass
class GameObject:
    """A thing in the world that can be examined, picked up, used, etc."""
    id: str
    name: str
    description: str
    location: str                        # room_id, "inventory", or "npc:<id>"
    state: dict = field(default_factory=dict)  # weight, is_locked, contents, etc.
    aliases: list = field(default_factory=list)  # alternate names (e.g. "mug" -> "coffee mug")
    is_clue: bool = False
    clue_id: Optional[int] = None        # which Phase 1 clue this object reveals
    is_critical_evidence: bool = False   # protected from destruction by Story Guard
    is_red_herring: bool = False
    red_herring_id: Optional[str] = None

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "location": self.location,
            "state": self.state,
            "aliases": self.aliases,
            "is_clue": self.is_clue,
            "clue_id": self.clue_id,
            "is_critical_evidence": self.is_critical_evidence,
            "is_red_herring": self.is_red_herring,
            "red_herring_id": self.red_herring_id,
        }


# ---------------------------------------------------------------------------
# NPCs
# ---------------------------------------------------------------------------

@dataclass
class NPC:
    """A non-player character. Suspects from Phase 1 become NPCs."""
    id: str
    name: str
    description: str
    location: str
    state: dict = field(default_factory=dict)        # alive, intimidated, willing_to_talk, etc.
    is_suspect: bool = False
    suspect_data: dict = field(default_factory=dict)  # alibi, motive, scores, etc.
    dialogue_topics: list = field(default_factory=list)
    is_critical: bool = False                        # criminal/key witness — protected

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "location": self.location,
            "state": self.state,
            "is_suspect": self.is_suspect,
            "suspect_data": self.suspect_data,
            "dialogue_topics": self.dialogue_topics,
            "is_critical": self.is_critical,
        }


# ---------------------------------------------------------------------------
# Action rules
# ---------------------------------------------------------------------------

@dataclass
class ActionRule:
    """
    The schema of an action the player can take.

    Preconditions are list of human-readable strings — they're checked by
    asking the LLM "given the current world state, do these conditions hold?"
    rather than via a brittle DSL. Effects are similarly human-readable and
    applied by the Action Interpreter. This trades some efficiency for
    flexibility — exactly what Template 3 needs.
    """
    name: str                                    # canonical action key, e.g. "climb_through_window"
    description: str                             # one-sentence summary
    preconditions: list = field(default_factory=list)
    effects: list = field(default_factory=list)
    requires_target: bool = False                # does this take an object/npc target?
    valid_targets: list = field(default_factory=list)  # ids the action can be applied to
    is_base: bool = False                        # part of the original action set
    generated_at_turn: Optional[int] = None      # if dynamically created, which turn

    def to_dict(self):
        return {
            "name": self.name,
            "description": self.description,
            "preconditions": self.preconditions,
            "effects": self.effects,
            "requires_target": self.requires_target,
            "valid_targets": self.valid_targets,
            "is_base": self.is_base,
            "generated_at_turn": self.generated_at_turn,
        }


# ---------------------------------------------------------------------------
# World state
# ---------------------------------------------------------------------------

@dataclass
class WorldState:
    """
    Single source of truth for the running game.

    The game engine mutates this on every turn. The four LLM components
    read it (and sometimes mutate it) to make decisions.
    """
    # Static-ish world structure
    rooms: dict = field(default_factory=dict)        # id -> Room
    objects: dict = field(default_factory=dict)      # id -> GameObject
    npcs: dict = field(default_factory=dict)         # id -> NPC
    rules: dict = field(default_factory=dict)        # name -> ActionRule

    # Player
    player_location: str = ""
    inventory: list = field(default_factory=list)    # object ids carried

    # Story progress
    discovered_clues: set = field(default_factory=set)        # clue_ids found
    encountered_red_herrings: set = field(default_factory=set)
    debunked_red_herrings: set = field(default_factory=set)
    plot_points_completed: list = field(default_factory=list)

    # Phase 1 context (read-only references)
    crime_schema: dict = field(default_factory=dict)
    plot_points: list = field(default_factory=list)

    # Game-loop state
    turn_count: int = 0
    last_progress_turn: int = 0
    game_over: bool = False
    outcome: str = "in_progress"                     # in_progress | won | lost
    accusation_threshold: int = 4                    # clues needed before accusing

    # Transcript (for walkthrough output)
    transcript: list = field(default_factory=list)   # list of dict events

    # ---- helpers -----------------------------------------------------------

    def get_current_room(self):
        return self.rooms.get(self.player_location)

    def objects_in_room(self, room_id=None):
        rid = room_id or self.player_location
        return [self.objects[oid] for oid in self.rooms[rid].object_ids if oid in self.objects]

    def npcs_in_room(self, room_id=None):
        rid = room_id or self.player_location
        return [self.npcs[nid] for nid in self.rooms[rid].npc_ids if nid in self.npcs]

    def find_object_by_name(self, name: str):
        """Loose match — used when the player types 'mug' and we have 'coffee_mug'."""
        name_lower = name.lower().strip()
        # exact id first
        if name_lower in self.objects:
            return self.objects[name_lower]
        # then exact name
        for obj in self.objects.values():
            if obj.name.lower() == name_lower:
                return obj
        # then alias
        for obj in self.objects.values():
            if name_lower in [a.lower() for a in obj.aliases]:
                return obj
        # then partial
        for obj in self.objects.values():
            if name_lower in obj.name.lower() or obj.name.lower() in name_lower:
                return obj
        return None

    def find_npc_by_name(self, name: str):
        name_lower = name.lower().strip()
        if name_lower in self.npcs:
            return self.npcs[name_lower]
        for npc in self.npcs.values():
            if npc.name.lower() == name_lower:
                return npc
            # last name match (e.g. "reynolds" -> "Dr. Michael Reynolds")
            parts = npc.name.lower().split()
            if name_lower in parts:
                return npc
        # partial
        for npc in self.npcs.values():
            if name_lower in npc.name.lower():
                return npc
        return None

    def log(self, event_type: str, content):
        """Append a turn event to the transcript."""
        self.transcript.append({
            "turn": self.turn_count,
            "type": event_type,
            "content": content,
        })

    def to_dict(self):
        return {
            "rooms": {k: v.to_dict() for k, v in self.rooms.items()},
            "objects": {k: v.to_dict() for k, v in self.objects.items()},
            "npcs": {k: v.to_dict() for k, v in self.npcs.items()},
            "rules": {k: v.to_dict() for k, v in self.rules.items()},
            "player_location": self.player_location,
            "inventory": self.inventory,
            "discovered_clues": sorted(list(self.discovered_clues)),
            "encountered_red_herrings": sorted(list(self.encountered_red_herrings)),
            "debunked_red_herrings": sorted(list(self.debunked_red_herrings)),
            "plot_points_completed": self.plot_points_completed,
            "turn_count": self.turn_count,
            "game_over": self.game_over,
            "outcome": self.outcome,
            "transcript": self.transcript,
        }

    def to_json(self, indent=2):
        return json.dumps(self.to_dict(), indent=indent, default=str)


