"""
Component 2 (YELLOW box in architecture diagram): Text Game Engine

The orchestrator. Each turn:

  1. Print the current room (or whatever just happened)
  2. Read player input from stdin (or a scripted input list, for demos)
  3. Action Interpreter classifies the input
     - if 'impossible': print refusal, end turn
     - if 'novel': call Rule Generator, apply cascade plan
     - if 'known': proceed
  4. Story Guard evaluates the action
     - if 'exception' + intervention='block': print intervention, end turn
     - if 'exception' + 'adapt' or 'redirect': apply intervention, then execute
     - if 'constituent' or 'consistent': execute normally
  5. Apply the action's effects (move object, update state, reveal clue)
  6. Update story progress (clues found, herrings debunked, plot points completed)
  7. Idle nudge if too many turns without progress
  8. Loop until game over (player accused, player gave up, or all clues found)

Every turn appends structured events to world_state.transcript so the engine
can dump a `[USER] / [ACTION INTERPRETER] / [RULE GENERATOR] / [STORY GUARD]`
walkthrough at the end (rubric: 15%).
"""

import os
import sys
import json
import textwrap

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from phase2.world_models import WorldState, GameObject, NPC
from phase2 import action_interpreter, rule_generator, story_guard


IDLE_NUDGE_THRESHOLD = 6           # turns without story progress before NPC nudge


# ---------------------------------------------------------------------------
# Game loop entry point
# ---------------------------------------------------------------------------

def play(world_state: WorldState, scripted_inputs: list = None,
         max_turns: int = 60, output_stream=None) -> WorldState:
    """
    Main game loop.

    scripted_inputs: optional list of strings; if provided, the engine reads
                     from this list instead of stdin (used for automated demos).
    output_stream:   defaults to stdout. Pass an open file handle to also
                     write the user-facing output to a file.
    max_turns:       hard cap on turns, just in case.
    """
    out = _Output(output_stream)
    out.print(_banner(world_state))
    out.print(_describe_room(world_state))
    world_state.log("scene", _describe_room(world_state))

    input_iter = iter(scripted_inputs) if scripted_inputs is not None else None

    while not world_state.game_over and world_state.turn_count < max_turns:
        world_state.turn_count += 1

        # ---- get input
        try:
            if input_iter is not None:
                player_input = next(input_iter)
                out.print(f"\n> {player_input}")
            else:
                out.print("")  # blank line for readability
                player_input = input("> ").strip()
        except (StopIteration, EOFError):
            out.print("\n[Engine] No more input. Ending session.")
            break

        if not player_input:
            world_state.turn_count -= 1
            continue

        if player_input.lower() in {"quit", "exit", "q"}:
            out.print("\n[Engine] Player ended the session.")
            break

        world_state.log("user", player_input)

        # ---- step 3: Action Interpreter
        out.dim(f"[ACTION INTERPRETER] classifying: '{player_input}'...")
        try:
            interp = action_interpreter.interpret(player_input, world_state)
        except Exception as e:
            out.print(f"[Engine] Action Interpreter failed: {e}. Try rephrasing.")
            continue

        interp["player_input_raw"] = player_input
        # Snapshot the classification for the transcript before any mutation
        # below (e.g. novel -> known after Rule Generator runs).
        world_state.log("action_interpreter", dict(interp))
        out.dim(f"[ACTION INTERPRETER] classification={interp['classification']}, "
                f"action={interp['action_name']}, target={interp.get('raw_target')}")

        if interp["classification"] == "impossible":
            reason = interp.get("impossible_reason") or "That doesn't seem possible here."
            out.print(f"\n{reason}")
            world_state.log("system", reason)
            continue

        # ---- step 3b: novel action → Rule Generator
        if interp["classification"] == "novel":
            out.dim("[RULE GENERATOR] action is novel — generating rule + cascade...")
            plan = rule_generator.generate_rule(
                action_name=interp["action_name"],
                raw_target=interp.get("raw_target"),
                player_input=player_input,
                world_state=world_state,
            )
            apply_log = rule_generator.apply_plan(plan, world_state)
            for line in apply_log:
                out.dim(f"[RULE GENERATOR] {line}")
            world_state.log("rule_generator", {
                "plan_summary": plan.get("subquest_summary"),
                "narrative": plan.get("narrative"),
                "new_rules": [r.name for r in plan["new_rules"]],
                "new_objects": [o.id for o in plan["new_objects"]],
                "new_rooms": [r.id for r in plan["new_rooms"]],
                "updated_rules": plan.get("updated_rules", []),
                "ready_to_execute": plan.get("ready_to_execute"),
            })
            out.print(f"\n{plan['narrative']}")
            if plan.get("subquest_summary"):
                out.dim(f"[Subquest opened] {plan['subquest_summary']}")
            # If the new rule's preconditions aren't met, end the turn.
            # The player has to satisfy them via existing actions first.
            if not plan.get("ready_to_execute"):
                continue
            # Otherwise, fall through and let it be classified+executed
            interp["classification"] = "known"
            # Re-resolve target now that new objects may exist
            if interp.get("raw_target"):
                obj = world_state.find_object_by_name(interp["raw_target"])
                if obj:
                    interp["resolved_target_id"] = obj.id
                    interp["resolved_target_type"] = "object"

        # ---- step 4: Story Guard
        out.dim("[STORY GUARD] evaluating action...")
        try:
            guard = story_guard.evaluate(interp, world_state)
        except Exception as e:
            out.print(f"[Engine] Story Guard failed: {e}. Allowing action.")
            guard = {"classification": "consistent"}

        world_state.log("story_guard", guard)
        out.dim(f"[STORY GUARD] classification={guard.get('classification')}"
                + (f", advances_clue={guard.get('advances_clue_id')}" if guard.get("advances_clue_id") else "")
                + (f", intervention={guard.get('intervention')}" if guard.get("intervention") else ""))

        if guard.get("classification") == "exception":
            intervention = guard.get("intervention") or "block"
            narrative = guard.get("intervention_narrative") or "Something prevents you from doing that."

            if intervention == "block":
                out.print(f"\n{narrative}")
                world_state.log("system", narrative)
                continue
            elif intervention == "redirect":
                out.print(f"\n{narrative}")
                world_state.log("system", narrative)
                continue
            elif intervention == "adapt":
                out.print(f"\n{narrative}")
                world_state.log("system", narrative)
                # adapt: action proceeds AND we make a new path to information
                # Fall through to normal execution

        if guard.get("skip_attempt"):
            out.print("\nYou don't have nearly enough evidence to make that claim. Keep investigating.")
            world_state.log("system", "Skip attempt blocked — insufficient evidence.")
            continue

        # ---- step 5: execute the action
        result = _execute_action(interp, world_state, out)
        if result.get("text"):
            out.print(f"\n{result['text']}")
            world_state.log("system", result["text"])

        # ---- step 6: apply Story Guard story-progress hints
        progressed = False
        if guard.get("advances_clue_id") is not None:
            cid = int(guard["advances_clue_id"])
            if cid not in world_state.discovered_clues:
                world_state.discovered_clues.add(cid)
                clue = next((c for c in world_state.crime_schema["evidence_chain"]
                             if c["id"] == cid), None)
                if clue:
                    msg = f"\n[CLUE DISCOVERED] Clue {cid}: {clue['description']}"
                    out.print(msg)
                    world_state.log("clue_discovered", {"clue_id": cid, "clue": clue})
                    progressed = True

        if guard.get("advances_red_herring_id"):
            rh_id = guard["advances_red_herring_id"]
            if rh_id not in world_state.encountered_red_herrings:
                world_state.encountered_red_herrings.add(rh_id)
                rh = next((r for r in world_state.crime_schema.get("red_herrings", [])
                           if r["id"] == rh_id), None)
                if rh:
                    msg = f"\n[RED HERRING ENCOUNTERED] {rh['description']}"
                    out.print(msg)
                    world_state.log("red_herring_encountered", rh)
                    progressed = True

        if guard.get("debunks_red_herring_id"):
            rh_id = guard["debunks_red_herring_id"]
            if rh_id not in world_state.debunked_red_herrings:
                world_state.debunked_red_herrings.add(rh_id)
                msg = f"\n[RED HERRING DEBUNKED] You've ruled out a misleading lead."
                out.print(msg)
                world_state.log("red_herring_debunked", {"id": rh_id})
                progressed = True

        if progressed:
            world_state.last_progress_turn = world_state.turn_count

        # ---- step 7: idle nudge
        idle = world_state.turn_count - world_state.last_progress_turn
        if idle > 0 and idle % IDLE_NUDGE_THRESHOLD == 0 and not world_state.game_over:
            nudge = _idle_nudge(world_state)
            if nudge:
                out.print(f"\n{nudge}")
                world_state.log("system_nudge", nudge)

        # ---- check for game end
        if result.get("game_over"):
            world_state.game_over = True
            world_state.outcome = result.get("outcome", "lost")
            out.print(_ending_banner(world_state))
            world_state.log("game_over", {"outcome": world_state.outcome})

    return world_state


# ---------------------------------------------------------------------------
# Action execution — the part that mutates non-clue state
# ---------------------------------------------------------------------------

def _execute_action(interp: dict, world_state: WorldState, out) -> dict:
    """Apply the effects of a (now-validated) action. Returns {text, game_over, outcome}."""
    action = interp["action_name"]
    target_id = interp.get("resolved_target_id")
    target_type = interp.get("resolved_target_type")

    # Built-in actions handled directly
    if action == "look":
        return {"text": _describe_room(world_state)}

    if action == "inventory":
        if not world_state.inventory:
            return {"text": "You're not carrying anything."}
        names = ", ".join(world_state.objects[oid].name for oid in world_state.inventory if oid in world_state.objects)
        return {"text": f"You're carrying: {names}."}

    if action == "help":
        verbs = ", ".join(sorted(r.name for r in world_state.rules.values() if r.is_base))
        extra = ", ".join(sorted(r.name for r in world_state.rules.values() if not r.is_base))
        text = f"Built-in actions: {verbs}\nRecently learned: {extra or '(none yet)'}\nYou can also try anything else — the engine will figure it out."
        return {"text": text}

    if action == "move":
        direction = (target_id or "").lower()
        room = world_state.get_current_room()
        if direction not in (room.connections if room else {}):
            return {"text": f"You can't go {direction} from here. Exits: {list(room.connections.keys()) if room else 'none'}."}
        # check locked passage
        passage_state = (room.state or {}).get(f"locked_{direction}", False)
        if passage_state:
            return {"text": f"The way {direction} is locked."}
        new_room_id = room.connections[direction]
        world_state.player_location = new_room_id
        new_room = world_state.rooms[new_room_id]
        new_room.visited = True
        return {"text": _describe_room(world_state)}

    if action == "examine":
        if target_type == "object" and target_id in world_state.objects:
            obj = world_state.objects[target_id]
            text = obj.description
            # mark examined for idle-nudge tracking
            obj.state["examined"] = True
            return {"text": text}
        if target_type == "npc" and target_id in world_state.npcs:
            npc = world_state.npcs[target_id]
            return {"text": npc.description}
        return {"text": "You don't see that here."}

    if action == "pick_up":
        if target_type != "object" or target_id not in world_state.objects:
            return {"text": "You can't pick that up."}
        obj = world_state.objects[target_id]
        if obj.location != world_state.player_location:
            return {"text": "That's not here."}
        weight = obj.state.get("weight", "light")
        if weight == "heavy":
            return {"text": f"The {obj.name} is far too heavy to carry."}
        # remove from room, add to inventory
        world_state.rooms[world_state.player_location].object_ids.remove(target_id)
        obj.location = "inventory"
        world_state.inventory.append(target_id)
        return {"text": f"You take the {obj.name}."}

    if action == "drop":
        if target_id not in world_state.inventory:
            return {"text": "You don't have that."}
        obj = world_state.objects[target_id]
        # apply retroactive checks: if a state var like leaning_against is set, clear it
        if obj.state.get("leaning_against"):
            obj.state["leaning_against"] = None
        world_state.inventory.remove(target_id)
        obj.location = world_state.player_location
        world_state.rooms[world_state.player_location].object_ids.append(target_id)
        return {"text": f"You drop the {obj.name}."}

    if action == "talk":
        if target_type != "npc" or target_id not in world_state.npcs:
            return {"text": "There's no one here by that name."}
        npc = world_state.npcs[target_id]
        if not npc.state.get("alive", True):
            return {"text": f"{npc.name} is in no state to talk."}
        if not npc.state.get("willing_to_talk", True):
            return {"text": f"{npc.name} refuses to speak with you."}
        npc.state["interrogated_count"] = npc.state.get("interrogated_count", 0) + 1
        # Generate a short bit of dialogue using the NPC's suspect_data
        sdata = npc.suspect_data or {}
        alibi = sdata.get("alibi", "I don't remember exactly where I was.")
        motive = sdata.get("motive", "")
        return {"text": f"\"{alibi}\" {npc.name} pauses. \"Look, I had no reason to want them dead.\""}

    if action == "use":
        if target_id and target_id in world_state.objects:
            obj = world_state.objects[target_id]
            return {"text": f"You consider how the {obj.name} might be used here."}
        return {"text": "You're not sure how to use that."}

    if action == "give":
        return {"text": "You hold out the item, but no one seems interested right now."}

    if action == "accuse":
        # Win/loss check
        if target_type != "npc" or target_id not in world_state.npcs:
            return {"text": "You'd need to accuse a specific person."}
        npc = world_state.npcs[target_id]
        if not npc.is_suspect:
            return {"text": f"{npc.name} isn't a suspect in this case."}
        # Threshold check
        if len(world_state.discovered_clues) < world_state.accusation_threshold:
            return {"text": f"You don't have enough evidence to accuse {npc.name}. ({len(world_state.discovered_clues)}/{world_state.accusation_threshold} clues required)"}
        # Compare against criminal
        criminal_name = world_state.crime_schema.get("criminal_name", "")
        if npc.name.lower() == criminal_name.lower():
            return {
                "text": f"You lay out the evidence. {npc.name} stares at the floor, then at the desk, then nowhere at all. \"... I didn't think it would come to this,\" they whisper. The case is closed.",
                "game_over": True,
                "outcome": "won",
            }
        else:
            return {
                "text": f"You accuse {npc.name}. They look at you, stunned, then furious. The evidence doesn't hold up under scrutiny — you've named the wrong person, and the real killer slips away.",
                "game_over": True,
                "outcome": "lost",
            }

    # Generated rules — when a novel action's preconditions are already met,
    # the Rule Generator's narrative was already printed earlier in the turn.
    # We don't add another line here to avoid double-narrating.
    rule = world_state.rules.get(action)
    if rule and not rule.is_base:
        return {"text": ""}

    return {"text": f"(The action '{action}' didn't do anything visible.)"}


# ---------------------------------------------------------------------------
# Description and idle nudge helpers
# ---------------------------------------------------------------------------

def _describe_room(world_state: WorldState) -> str:
    room = world_state.get_current_room()
    if not room:
        return "(You're nowhere.)"

    lines = []
    lines.append(f"== {room.name} ==")
    lines.append(textwrap.fill(room.description, width=78))

    objs = world_state.objects_in_room()
    if objs:
        names = ", ".join(o.name for o in objs)
        lines.append(f"You see: {names}.")

    npcs = world_state.npcs_in_room()
    if npcs:
        names = ", ".join(f"{n.name}" for n in npcs)
        lines.append(f"Present: {names}.")

    if room.connections:
        exits = ", ".join(room.connections.keys())
        lines.append(f"Exits: {exits}.")

    return "\n".join(lines)


def _idle_nudge(world_state: WorldState) -> str:
    """Return a short hint when the player has gone N turns without progress."""
    undiscovered = [c for c in world_state.crime_schema.get("evidence_chain", [])
                    if c["id"] not in world_state.discovered_clues]
    if not undiscovered:
        return ""
    next_clue = undiscovered[0]
    method = next_clue.get("discovery_method") or next_clue.get("description", "")
    return (f"\n[A passing detective murmurs] \"You might want to look into "
            f"{method.lower().rstrip('.')}.\"")


def _banner(world_state: WorldState) -> str:
    schema = world_state.crime_schema
    return (
        "=" * 70 + "\n"
        f"  FLYING PANDA — Phase II Interactive Mystery\n"
        f"  Setting: {schema.get('setting', 'unknown')}\n"
        f"  Victim:  {schema.get('victim', 'unknown')}\n"
        f"  Goal:    Find {world_state.accusation_threshold}+ clues, then accuse the killer.\n"
        f"  Type 'help' for actions, 'quit' to leave.\n"
        + "=" * 70
    )


def _ending_banner(world_state: WorldState) -> str:
    if world_state.outcome == "won":
        return (
            "\n" + "=" * 70 + "\n"
            "  CASE CLOSED — You named the killer correctly.\n"
            f"  Clues discovered: {len(world_state.discovered_clues)}\n"
            f"  Red herrings debunked: {len(world_state.debunked_red_herrings)}\n"
            f"  Total turns: {world_state.turn_count}\n"
            + "=" * 70
        )
    elif world_state.outcome == "lost":
        return (
            "\n" + "=" * 70 + "\n"
            "  CASE COLD — You accused the wrong person.\n"
            "  The real killer walks free.\n"
            + "=" * 70
        )
    return ""


# ---------------------------------------------------------------------------
# Output streaming helper
# ---------------------------------------------------------------------------

class _Output:
    """Tee output to stdout and (optionally) a file."""
    def __init__(self, file_handle=None):
        self.file = file_handle

    def print(self, text: str):
        print(text)
        if self.file:
            self.file.write(text + "\n")
            self.file.flush()

    def dim(self, text: str):
        # Slightly dimmer marker for engine-internal events. Some terminals
        # render this as gray; in plain text it's just bracketed.
        print(f"\033[90m{text}\033[0m")
        if self.file:
            self.file.write(text + "\n")
            self.file.flush()
