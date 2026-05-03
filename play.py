"""
Phase 2 entry point.

Loads a pre-generated Phase 1 mystery (crime schema + plot points) from disk,
builds the interactive game world via the World Generator, then drops the
player into the Text Game Engine.

Usage:
    # play with a saved exemplar (recommended for grading / demos)
    python play.py --exemplar

    # play with a specific saved Phase 1 run
    python play.py --schema output/crime_schema_TIMESTAMP.json \\
                   --plot-points output/plot_points_TIMESTAMP.json

    # generate a fresh story first, then play
    python play.py --setting "a university research lab" --fresh

    # run a scripted demo (reads inputs from a text file, writes transcript)
    python play.py --exemplar --scripted demo_inputs/exemplar_run.txt
"""

import os
import sys
import json
import time
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from phase2.world_generator import generate_world
from phase2.game_engine import play
from phase2.world_models import (
    WorldState, Room, GameObject, NPC, ActionRule,
)

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
EXAMPLES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "examples")
PHASE2_OUTPUT_DIR = os.path.join(OUTPUT_DIR, "phase2")


def main():
    p = argparse.ArgumentParser(description="Flying Panda — Phase 2 interactive mystery")
    p.add_argument("--exemplar", action="store_true",
                   help="Use the bundled exemplar Phase 1 mystery from examples/")
    p.add_argument("--schema", type=str, help="Path to crime_schema_*.json")
    p.add_argument("--plot-points", type=str, help="Path to plot_points_*.json")
    p.add_argument("--fresh", action="store_true",
                   help="Generate a fresh Phase 1 mystery first")
    p.add_argument("--setting", type=str, default="a university research lab",
                   help="Setting for fresh generation")
    p.add_argument("--world", type=str,
                   help="Path to a saved world snapshot (skips world generation; "
                        "used for deterministic replay of bundled demos).")
    p.add_argument("--scripted", type=str,
                   help="Path to a text file of player inputs (one per line). "
                        "Engine reads from the file instead of stdin.")
    p.add_argument("--max-turns", type=int, default=40,
                   help="Hard cap on turns (default 40)")
    args = p.parse_args()

    # ---- 1. obtain world: either load saved snapshot, or run World Generator
    if args.world:
        print(f"\n[Phase 2] Loading saved world: {args.world}")
        world = _load_world_snapshot(args.world)
        print(f"  Rooms: {len(world.rooms)}  Objects: {len(world.objects)}  "
              f"NPCs: {len(world.npcs)}  Rules: {len(world.rules)}")
    else:
        schema_path, plot_path = _resolve_inputs(args)
        print(f"\n[Phase 2] Loading mystery from:")
        print(f"  Crime schema: {schema_path}")
        print(f"  Plot points:  {plot_path}")
        crime_schema, plot_points = _load_phase1(schema_path, plot_path)

        print(f"\n[Phase 2] Generating game world from Phase 1 output...")
        print(f"  This makes 3 LLM calls (rooms, objects, NPCs).")
        world = generate_world(crime_schema, plot_points)
        print(f"  Rooms: {len(world.rooms)}  Objects: {len(world.objects)}  "
              f"NPCs: {len(world.npcs)}  Base rules: {len(world.rules)}")

    os.makedirs(PHASE2_OUTPUT_DIR, exist_ok=True)
    timestamp = time.strftime("%Y%m%d_%H%M%S")

    # save initial world snapshot
    initial_world_path = os.path.join(PHASE2_OUTPUT_DIR, f"world_initial_{timestamp}.json")
    with open(initial_world_path, "w") as f:
        f.write(world.to_json())
    print(f"  Initial world snapshot: {initial_world_path}")

    # ---- 3. run game loop
    scripted_inputs = None
    if args.scripted:
        with open(args.scripted) as f:
            scripted_inputs = [line.rstrip("\n") for line in f
                               if line.strip() and not line.startswith("#")]
        print(f"\n[Phase 2] Scripted run: {len(scripted_inputs)} inputs from {args.scripted}")

    # always tee output to a transcript file
    transcript_text_path = os.path.join(PHASE2_OUTPUT_DIR, f"transcript_{timestamp}.txt")
    transcript_file = open(transcript_text_path, "w")

    try:
        play(world, scripted_inputs=scripted_inputs,
             max_turns=args.max_turns, output_stream=transcript_file)
    finally:
        transcript_file.close()

    # ---- 4. dump structured transcript JSON for review
    transcript_json_path = os.path.join(PHASE2_OUTPUT_DIR, f"transcript_{timestamp}.json")
    with open(transcript_json_path, "w") as f:
        json.dump(world.transcript, f, indent=2, default=str)

    # ---- 5. dump labeled walkthrough (the rubric-friendly version)
    walkthrough_path = os.path.join(PHASE2_OUTPUT_DIR, f"walkthrough_{timestamp}.txt")
    with open(walkthrough_path, "w") as f:
        f.write(_format_walkthrough(world))

    # ---- 6. final world snapshot
    final_world_path = os.path.join(PHASE2_OUTPUT_DIR, f"world_final_{timestamp}.json")
    with open(final_world_path, "w") as f:
        f.write(world.to_json())

    print(f"\n[Phase 2] Outputs saved:")
    print(f"  Plain transcript:   {transcript_text_path}")
    print(f"  Structured events:  {transcript_json_path}")
    print(f"  Labeled walkthrough: {walkthrough_path}")
    print(f"  Final world state:  {final_world_path}")


# ---------------------------------------------------------------------------
# Input resolution
# ---------------------------------------------------------------------------

def _resolve_inputs(args):
    if args.fresh:
        return _run_fresh_phase1(args.setting)

    if args.exemplar:
        schema = os.path.join(EXAMPLES_DIR, "exemplar_crime_schema.json")
        plot = os.path.join(EXAMPLES_DIR, "exemplar_plot_points.json")
        if not (os.path.exists(schema) and os.path.exists(plot)):
            print("[Phase 2] Exemplar files not found in examples/. Falling back to latest in output/.")
            return _latest_in_output()
        return schema, plot

    if args.schema and args.plot_points:
        return args.schema, args.plot_points

    # default: use the most recent Phase 1 output
    return _latest_in_output()


def _latest_in_output():
    if not os.path.isdir(OUTPUT_DIR):
        print("[Phase 2] No output directory. Generating a fresh story first...")
        return _run_fresh_phase1("a university research lab")
    schemas = sorted([f for f in os.listdir(OUTPUT_DIR) if f.startswith("crime_schema_") and f.endswith(".json")])
    plots = sorted([f for f in os.listdir(OUTPUT_DIR) if f.startswith("plot_points_") and f.endswith(".json")])
    if not schemas or not plots:
        print("[Phase 2] No Phase 1 output found. Generating a fresh story first...")
        return _run_fresh_phase1("a university research lab")
    # match by timestamp
    return os.path.join(OUTPUT_DIR, schemas[-1]), os.path.join(OUTPUT_DIR, plots[-1])


def _run_fresh_phase1(setting):
    """Run the Phase 1 pipeline to produce fresh inputs."""
    from main import run as run_phase1
    print(f"\n[Phase 2] Running Phase 1 pipeline for setting: {setting!r}")
    run_phase1(setting)
    return _latest_in_output()


def _load_phase1(schema_path: str, plot_path: str):
    with open(schema_path) as f:
        crime_schema = json.load(f)
    with open(plot_path) as f:
        plot_points = json.load(f)
    return crime_schema, plot_points


def _load_world_snapshot(path: str) -> WorldState:
    """Reconstitute a WorldState from a saved JSON snapshot. Used for
    deterministic replay of bundled demos. The world generator's LLM call
    is skipped; everything else (the four LLM components in the game loop)
    still runs live."""
    with open(path) as f:
        data = json.load(f)

    # Try sibling files for the matching crime_schema and plot_points so the
    # Story Guard has the Phase 1 ground truth available.
    crime_schema = {}
    plot_points = []
    snap_dir = os.path.dirname(os.path.abspath(path))
    for sibling_name in ("exemplar_crime_schema.json",):
        candidate = os.path.join(snap_dir, sibling_name)
        if os.path.exists(candidate):
            with open(candidate) as f:
                crime_schema = json.load(f)
            break
    for sibling_name in ("exemplar_plot_points.json",):
        candidate = os.path.join(snap_dir, sibling_name)
        if os.path.exists(candidate):
            with open(candidate) as f:
                plot_points = json.load(f)
            break

    world = WorldState()
    world.crime_schema = crime_schema
    world.plot_points = plot_points
    world.player_location = data.get("player_location", "")
    world.inventory = list(data.get("inventory", []))
    world.discovered_clues = set(data.get("discovered_clues", []))
    world.encountered_red_herrings = set(data.get("encountered_red_herrings", []))
    world.debunked_red_herrings = set(data.get("debunked_red_herrings", []))
    world.plot_points_completed = list(data.get("plot_points_completed", []))
    world.turn_count = data.get("turn_count", 0)
    world.outcome = data.get("outcome", "in_progress")

    for rid, rd in data.get("rooms", {}).items():
        world.rooms[rid] = Room(**rd)
    for oid, od in data.get("objects", {}).items():
        world.objects[oid] = GameObject(**od)
    for nid, nd in data.get("npcs", {}).items():
        world.npcs[nid] = NPC(**nd)
    for rname, rd in data.get("rules", {}).items():
        world.rules[rname] = ActionRule(**rd)

    return world


# ---------------------------------------------------------------------------
# Walkthrough formatting (rubric: 15%)
# ---------------------------------------------------------------------------

def _format_walkthrough(world: WorldState) -> str:
    """
    Produce a clean text version of the run with USER actions and engine
    component actions clearly marked. This is the artifact the rubric asks
    for: 'User actions and drama manager actions should be clearly marked.'
    """
    out = []
    schema = world.crime_schema
    out.append("=" * 78)
    out.append("  FLYING PANDA — Phase II Walkthrough")
    out.append(f"  Setting: {schema.get('setting', '?')}")
    out.append(f"  Victim:  {schema.get('victim', '?')}")
    out.append(f"  Killer:  {schema.get('criminal_name', '?')}  (revealed at end of investigation)")
    out.append(f"  Outcome: {world.outcome.upper()}  ({world.turn_count} turns, "
               f"{len(world.discovered_clues)} clues discovered)")
    out.append("=" * 78)
    out.append("")

    out.append("Legend:")
    out.append("  [USER]                — Free text typed by the player")
    out.append("  [ACTION INTERPRETER]  — Component 3: classifies input as known/novel/impossible")
    out.append("  [RULE GENERATOR]      — Component 4: invents new rules + cascading prerequisites")
    out.append("  [STORY GUARD]         — Component 5: protects the mystery from being broken")
    out.append("  [SCENE]               — World description shown to player")
    out.append("  [SYSTEM]              — Engine response to a successful action")
    out.append("")

    for ev in world.transcript:
        turn = ev.get("turn", 0)
        et = ev["type"]
        c = ev["content"]

        if et == "scene":
            out.append(f"--- Turn {turn} ---")
            out.append(f"[SCENE] {c}")
        elif et == "user":
            out.append(f"\n--- Turn {turn} ---")
            out.append(f"[USER] {c}")
        elif et == "action_interpreter":
            cls = c.get("classification")
            act = c.get("action_name")
            tgt = c.get("raw_target")
            out.append(f"[ACTION INTERPRETER] classification={cls}, action={act}, target={tgt!r}, reason={c.get('reasoning')}")
        elif et == "rule_generator":
            out.append("[RULE GENERATOR]")
            if c.get("plan_summary"):
                out.append(f"  Subquest: {c['plan_summary']}")
            if c.get("new_rules"):
                out.append(f"  New rules: {c['new_rules']}")
            if c.get("new_objects"):
                out.append(f"  New objects: {c['new_objects']}")
            if c.get("new_rooms"):
                out.append(f"  New rooms: {c['new_rooms']}")
            if c.get("updated_rules"):
                for u in c["updated_rules"]:
                    out.append(f"  Retroactive update: '{u.get('rule_name')}' -> {u.get('reason')}")
            out.append(f"  Ready to execute: {c.get('ready_to_execute')}")
        elif et == "story_guard":
            cls = c.get("classification")
            line = f"[STORY GUARD] classification={cls}"
            if c.get("advances_clue_id") is not None:
                line += f", advances_clue_id={c['advances_clue_id']}"
            if c.get("advances_red_herring_id"):
                line += f", encounters_rh={c['advances_red_herring_id']}"
            if c.get("debunks_red_herring_id"):
                line += f", debunks_rh={c['debunks_red_herring_id']}"
            if c.get("intervention"):
                line += f", intervention={c['intervention']}"
            out.append(line)
            if c.get("reasoning"):
                out.append(f"  reasoning: {c['reasoning']}")
            if c.get("intervention_narrative"):
                out.append(f"  intervention_narrative: {c['intervention_narrative']}")
        elif et == "system":
            out.append(f"[SYSTEM] {c}")
        elif et == "system_nudge":
            out.append(f"[SYSTEM NUDGE] {c}")
        elif et == "clue_discovered":
            cl = c.get("clue", {})
            out.append(f"[CLUE DISCOVERED] Clue {c.get('clue_id')}: {cl.get('description')}")
        elif et == "red_herring_encountered":
            out.append(f"[RED HERRING ENCOUNTERED] {c.get('description', c)}")
        elif et == "red_herring_debunked":
            out.append(f"[RED HERRING DEBUNKED] {c}")
        elif et == "game_over":
            out.append("")
            out.append(f"[GAME OVER] Outcome: {c.get('outcome')}")

    return "\n".join(out)


if __name__ == "__main__":
    main()
