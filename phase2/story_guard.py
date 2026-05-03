"""
Component 5 (ORANGE box in architecture diagram): Story Guard

Runs after the Action Interpreter, BEFORE the action's effects are applied.
Decides whether the player's action is:

  - constituent : it advances a Phase 1 plot point. Engine credits the clue
                  / debunks the herring / etc.
  - consistent  : it doesn't advance the story but doesn't break it either.
                  Engine just executes it normally.
  - exception   : it would make an unresolved plot point IMPOSSIBLE. Engine
                  must intervene. Three intervention strategies:
                    1. block    : refuse the action with a narrative reason
                    2. redirect : let action partially succeed but redirect away
                    3. adapt    : let action succeed; generate a new path to
                                  the same information (e.g., a backup witness)

Also handles the "advancing the story via an unexpected path" case from the
template-specific question — the player might do something that effectively
reveals a clue without going through the canonical discovery method.
"""

import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from llm import call_llm_json
from phase2.world_models import WorldState


SYSTEM_PROMPT = """You are the story guardian for a murder mystery text adventure.
Your job is to make sure the player's actions don't break the story.

You see the action the player is about to take, the current world state, and
the unresolved plot points (clues to discover, red herrings to debunk,
suspects to confront). You decide:

  1. Does this action ADVANCE an unresolved plot point? (constituent)
     This includes both planned discoveries AND alternate-path discoveries
     where the player figures things out a different way.

  2. Is this action neutral — doesn't advance, doesn't threaten? (consistent)

  3. Is this action a THREAT — would it make an unresolved plot point
     impossible to ever resolve? (exception)

For exceptions, recommend an intervention strategy.

You always respond in valid JSON."""


def evaluate(action_dict: dict, world_state: WorldState) -> dict:
    """
    Return a dict like:
      {
        "classification": "constituent" | "consistent" | "exception",
        "advances_clue_id": int | None,
        "advances_red_herring_id": str | None,
        "debunks_red_herring_id": str | None,
        "exception_threat": str | None,
        "intervention": "block" | "redirect" | "adapt" | None,
        "intervention_narrative": str | None,
        "reasoning": str,
        "skip_attempt": bool   # is the player trying to short-circuit the mystery?
      }
    """
    # Quick-check: the meta-action 'accuse' always goes through the full Story Guard
    # because it's the win/loss trigger
    crime_schema = world_state.crime_schema
    unresolved_clues = [c for c in crime_schema.get("evidence_chain", [])
                        if c["id"] not in world_state.discovered_clues]
    unresolved_herrings = [rh for rh in crime_schema.get("red_herrings", [])
                           if rh["id"] not in world_state.debunked_red_herrings]

    target_obj = None
    target_npc = None
    if action_dict.get("resolved_target_type") == "object":
        target_obj = world_state.objects.get(action_dict.get("resolved_target_id"))
    elif action_dict.get("resolved_target_type") == "npc":
        target_npc = world_state.npcs.get(action_dict.get("resolved_target_id"))

    target_summary = ""
    if target_obj:
        target_summary = (f"Target object: {target_obj.name} (id={target_obj.id}, "
                          f"is_clue={target_obj.is_clue}, clue_id={target_obj.clue_id}, "
                          f"is_critical_evidence={target_obj.is_critical_evidence}, "
                          f"is_red_herring={target_obj.is_red_herring}, "
                          f"red_herring_id={target_obj.red_herring_id})")
    elif target_npc:
        target_summary = (f"Target NPC: {target_npc.name} (id={target_npc.id}, "
                          f"is_critical={target_npc.is_critical}, "
                          f"is_suspect={target_npc.is_suspect}, "
                          f"alive={target_npc.state.get('alive', True)})")

    unresolved_summary = "\n".join(
        f"  Clue {c['id']}: {c['description']} (discovery method: {c['discovery_method']}, points to: {c['points_to']})"
        for c in unresolved_clues
    ) or "  (all clues resolved!)"

    unresolved_rh = "\n".join(
        f"  Red Herring {rh['id']}: {rh['planted_evidence']} -> debunk via {rh['debunk_method']}"
        for rh in unresolved_herrings
    ) or "  (all red herrings resolved)"

    user_prompt = f"""The player is about to perform this action:

  Action: {action_dict.get('action_name')}
  Player input (raw): "{action_dict.get('player_input_raw', '')}"
  Target: {action_dict.get('raw_target') or '(none)'}
  {target_summary}

Current state:
  Discovered clues so far: {sorted(list(world_state.discovered_clues))} of {len(crime_schema.get('evidence_chain', []))}
  Player location: {world_state.player_location}

Unresolved plot points:

UNRESOLVED CLUES (each must remain discoverable):
{unresolved_summary}

UNRESOLVED RED HERRINGS:
{unresolved_rh}

Classify the action:

{{
  "classification": "constituent" | "consistent" | "exception",
  "advances_clue_id": <int id from unresolved_clues if this action would
       reveal that clue (whether through canonical means OR an alternate path)
       — null otherwise>,
  "advances_red_herring_id": <id from unresolved_red_herrings if this action
       would have the player encounter it — null otherwise>,
  "debunks_red_herring_id": <id if this action would debunk a previously-
       encountered red herring — null otherwise>,
  "exception_threat": "if exception: which unresolved plot point this action
       would make impossible — null otherwise",
  "intervention": "if exception: 'block' | 'redirect' | 'adapt' — null otherwise",
  "intervention_narrative": "if exception: 1-2 sentences the engine will print
       to the player explaining what happens. For 'block': in-world reason it
       fails. For 'redirect': partial success that points elsewhere. For
       'adapt': the action succeeds, but a new route to the same information
       is briefly described.",
  "reasoning": "one sentence explaining your classification",
  "skip_attempt": true if the player is trying to short-circuit the mystery
       (e.g., randomly accusing without evidence, brute-forcing the killer's
       name, instantly demanding a confession)
}}

GUIDELINES:

EXAMINING / READING / LOOKING-AT actions are almost ALWAYS classified as
'constituent' or 'consistent', NEVER as 'exception'. Examining doesn't break
anything physical.
  - If the target object has is_clue=true and clue_id is unresolved → constituent,
    set advances_clue_id = clue_id.
  - If the target object has is_red_herring=true and the red_herring_id is
    not yet in encountered: → constituent, set advances_red_herring_id =
    red_herring_id. The red herring is now "encountered."
  - If the player notices the red herring is misleading (e.g., they examine
    it after finding evidence that contradicts it) → constituent, set
    debunks_red_herring_id.
  - If the target object is ambient (no flags) → consistent.

DESTRUCTIVE actions (burn, break, smash, destroy, tear up, flush, eat) are
where exceptions live:
  - Target has is_critical_evidence=true → 'exception' with intervention='block'
    or 'adapt'. NEVER 'redirect' for these. Block by giving an in-world reason
    the action fails (sprinkler activates, the object is in a sealed evidence
    bag, security camera catches it, etc.). Adapt by letting it succeed AND
    introducing a new pathway to the same clue (a digital backup, an additional
    witness, a duplicate copy).
  - Target has is_red_herring=true → 'consistent' (destroying a red herring
    is fine, it doesn't break the story). Optionally mark it as encountered
    via advances_red_herring_id.
  - Target is ambient (mug, desk, notebook with no flags) → 'consistent'.

VIOLENCE TOWARD NPCs:
  - Target NPC has is_critical=true (the criminal) and the player tries to
    kill/incapacitate them → 'exception' with intervention='block'. They need
    to be alive to confess.
  - Target NPC is is_suspect=true → 'exception' with intervention='block' or
    'redirect'. Suspects can't be killed; they're needed for confrontation.
  - Generic threats / intimidation → 'consistent' (NPCs can refuse to talk,
    but the action itself doesn't break anything).

ACCUSE action:
  - Always classification='constituent'. The engine handles win/lose.

SKIP ATTEMPTS:
  - Only mark skip_attempt=true for inputs like "the killer is X", "X did it",
    "I solve the mystery", "I know who did it" without any actual investigation
    having happened.
  - Pure 'accuse' actions with insufficient clues are NOT skip_attempts; the
    engine has its own evidence-threshold check for those.

ALTERNATE PATHS:
  - If the player does something creative that effectively reveals a clue
    through a non-canonical method (e.g., reads a backup of the data, or
    deduces from a different source), classify as 'constituent' and set
    advances_clue_id to the clue they revealed. Add a note in 'reasoning'."""

    return call_llm_json(SYSTEM_PROMPT, user_prompt, temperature=0.3)
