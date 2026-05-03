# Flying Panda

Team: Flying Panda (Arnav Mardia, Shivom Dhamija)
System: Flying Panda
Phase I template: Template 1 (Suspense Murder Mystery)
Phase II template: Template 3 (Game Engine Rule Generation)
Course: CS 7634

## What it does

Phase I generates a murder mystery story from a setting prompt. It produces 16 plot points, 4 suspects, a chain of 6 clues, and 3 red herrings. Pacing is controlled by a non-LLM state machine that tracks tension across a target curve.

Phase II takes the generated mystery and turns it into a playable text adventure. The player can type any action. If the engine doesn't have rules for it, it makes them up on the fly, including any new objects, locations, or prerequisites needed to keep the action commonsense-consistent. When new state variables show up, existing rules get updated retroactively to handle them.

Both phases use gpt-4o-mini.

## Architecture

Phase I is 5 stages:

1. `crime_schema.py` — Crime Schema Generator (LLM). Generates the ground truth: victim, criminal, suspects with means/motive/opportunity scores, alibis, evidence chain.
2. `red_herrings.py` — Red Herring Injector (LLM). Generates misleading evidence pointing at innocent suspects. Criminal's identity is stripped before the prompt.
3. `meta_controller.py` — Suspense Meta-Controller. State machine, no LLM. Picks the next plot point type based on a target tension curve and progress so far.
4. `plot_generator.py` — Plot Point Generator (LLM). Writes each scene.
5. `story_compiler.py` — Story Compiler (LLM). Stitches the plot points into one cohesive story.

Phase II lives in `phase2/`. Each module is one box from the architecture diagram in our proposal video:

| File | Box | Role |
| ---- | --- | ---- |
| `phase2/world_generator.py` | green | Reads Phase I output, builds room graph, places objects/NPCs/clues, defines base actions. |
| `phase2/game_engine.py` | yellow | The main loop. Prints scenes, reads input, orchestrates the other components, mutates world state, writes the transcript. |
| `phase2/action_interpreter.py` | purple | Classifies free-text input as known / novel / impossible. |
| `phase2/rule_generator.py` | gray | When an action is novel, this creates the rule and any cascading objects/rooms/state vars, plus retroactive updates to old rules. |
| `phase2/story_guard.py` | orange | Checks every action against unresolved plot points. Decides constituent / consistent / exception, and picks an intervention if needed. |

Supporting:

- `phase2/world_models.py` — dataclasses for `Room`, `GameObject`, `NPC`, `ActionRule`, `WorldState`.
- `play.py` — Phase II entry point. Loads pre-generated Phase I output, runs world generation, then drops you into the game loop.

## How to run

You need:

- Python 3.10+
- uv (https://docs.astral.sh/uv/)
- An OpenAI API key

Setup:

```bash
git clone <repo-url>
cd flying-panda
uv sync
cp .env.example .env
# put your key in .env
```

Phase I (story generation):

```bash
uv run python main.py
uv run python main.py "a Michelin-star restaurant"
uv run python main.py "a tech startup in San Francisco"
```

Phase II (interactive):

```bash
# Use the bundled exemplar mystery (full pipeline including world generation)
uv run python play.py --exemplar

# Same exemplar but run the scripted demo (saves a labeled walkthrough)
uv run python play.py --exemplar --scripted demo_inputs/exemplar_run.txt

# Generate a fresh story first, then play
uv run python play.py --fresh --setting "a hospital ICU"

# Replay against the deterministic saved world (skips world generation)
uv run python play.py --world examples/exemplar_world.json
```

To win: find at least 4 of 6 clues, then type `accuse <suspect name>`. Type `help` to see the current verb list. Type `quit` to leave.

## Output

Phase I writes to `output/`:

| File | What it has |
| ---- | ----------- |
| `mystery_TIMESTAMP.txt` | Crime backstory, plot point summary, full compiled story |
| `crime_schema_TIMESTAMP.json` | Ground-truth crime data |
| `plot_points_TIMESTAMP.json` | Per-plot-point structured data |
| `tension_curve_TIMESTAMP.png` | Target vs. actual tension curve |

Phase II writes to `output/phase2/`:

| File | What it has |
| ---- | ----------- |
| `world_initial_TIMESTAMP.json` | World after generation, before play |
| `world_final_TIMESTAMP.json` | World at the end of the session |
| `transcript_TIMESTAMP.txt` | Plain text of what the player saw |
| `transcript_TIMESTAMP.json` | Per-turn structured event log |
| `walkthrough_TIMESTAMP.txt` | Labeled walkthrough with `[USER]` / `[ACTION INTERPRETER]` / `[RULE GENERATOR]` / `[STORY GUARD]` markers |

## Runtime and cost

Phase I: 2-4 minutes per story, ~22 LLM calls, around $0.05 per run.

Phase II: ~3 minutes for world generation. Then 2-3 LLM calls per turn (action interpreter, story guard, sometimes rule generator). Typical session is 20-30 turns, around $0.10 per run.

Both use gpt-4o-mini.

## Files

```
flying-panda/
  main.py                  # Phase I entry
  play.py                  # Phase II entry
  llm.py                   # OpenAI wrapper
  models.py                # Phase I data classes
  crime_schema.py          # Phase I stage 1
  red_herrings.py          # Phase I stage 2
  meta_controller.py       # Phase I stage 3
  plot_generator.py        # Phase I stage 4
  story_compiler.py        # Phase I stage 5
  phase2/
    world_models.py        # Phase II data classes
    world_generator.py     # Component 1 (green)
    game_engine.py         # Component 2 (yellow)
    action_interpreter.py  # Component 3 (purple)
    rule_generator.py      # Component 4 (gray)
    story_guard.py         # Component 5 (orange)
  examples/                # Bundled walkthroughs and Phase I outputs
  demo_inputs/             # Scripted player input files
  pyproject.toml
  .env.example
```

## API key

We are not bundling our API key. Put yours in `.env` or export it directly:

```bash
export OPENAI_API_KEY="sk-..."
uv run python play.py --exemplar
```

## Phase I exemplar

`examples/exemplar_story.txt` is a complete winning Phase I run.

- Setting: a university research lab
- Victim: Dr. Emily Carter
- Criminal: Dr. Michael Reynolds
- Method: neurotoxin slipped into her coffee

It has 16 plot points, all event categories represented, and the criminal confesses in the final scene.

| #   | Type                  | Title                              | Tension |
| --- | --------------------- | ---------------------------------- | ------- |
| 1   | obstacle              | Lab of Shadows                     | 0.12    |
| 2   | clue_discovery        | The Coffee Mug Clue                | 0.18    |
| 3   | red_herring_encounter | Eerie Evidence in the Lab          | 0.26    |
| 4   | suspect_confrontation | Confronting the Lead Researcher    | 0.34    |
| 5   | obstacle              | The Escape of Dr. Mitchell         | 0.46    |
| 6   | clue_discovery        | Crucial Footage Unveiled           | 0.57    |
| 7   | false_lead            | Unraveling the Web                 | 0.55    |
| 8   | red_herring_encounter | Tangled Evidence Unfolds           | 0.60    |
| 9   | clue_discovery        | Toxic Truth Unveiled               | 0.66    |
| 10  | false_lead            | The Fractured Evidence             | 0.62    |
| 11  | clue_discovery        | Whispers of Conflict               | 0.72    |
| 12  | red_herring_encounter | Misleading Correspondence Unveiled | 0.74    |
| 13  | clue_discovery        | Access Logs Uncovered              | 0.78    |
| 14  | breakthrough          | Fractured Alibi Unraveled          | 0.81    |
| 15  | breakthrough          | Toxic Evidence Uncovered           | 0.87    |
| 16  | resolution            | Confrontation in the Lab           | 0.62    |

Tension curve in `examples/exemplar_tension_curve.png`. The curve shows the 3-act structure: gradual build (0.12-0.34), rising action with dips for false leads (0.46-0.78), peak at breakthrough (0.87), and resolution drop (0.62).

## Phase II walkthroughs

Two walkthroughs are bundled in `examples/`:

| File | Outcome | What it shows |
| ---- | ------- | ------------- |
| `examples/phase2_exemplar_walkthrough.txt` | CASE CLOSED, 30 turns, 6/6 clues | A winning playthrough that hits constituent + consistent + novel rule generation + correct accusation. |
| `examples/phase2_misspun_walkthrough.txt` | CASE COLD, 21 turns, 5 clues | A defensive playthrough. The player tries to skip ahead, fly to the moon, burn evidence, kill the criminal. The system handles it. Includes a clean retroactive rule update. Player ends up making a wrong accusation. |

Each line in those files is tagged so you can see which component made each decision:

- `[USER]` — what the player typed
- `[ACTION INTERPRETER]` — Component 3 classification
- `[RULE GENERATOR]` — Component 4 (when novel actions trigger JIT rule + cascade creation, including retroactive updates)
- `[STORY GUARD]` — Component 5 classification (constituent / consistent / exception)
- `[SCENE]` / `[SYSTEM]` — what the player saw on screen
- `[CLUE DISCOVERED]` / `[RED HERRING ENCOUNTERED]` / `[GAME OVER]` — story progress markers

## Template-specific question

> How does your system know when the story is advancing differently than expected? How does it know when an action will break the story, and how does it handle that?

The Story Guard runs after the Action Interpreter on every turn. It reads the parsed action, the current world state, and the unresolved Phase I plot points, then picks one of three classifications:

**constituent** — the action advances a plot point. This includes alternate paths. If the player picks the lock on a desk and finds a copy of a document a clue would have provided, the Story Guard checks whether the discovery effectively reveals an unresolved clue and, if so, credits it.

**consistent** — the action neither advances nor threatens the story. The engine just runs it.

**exception** — the action would make an unresolved plot point impossible. The Story Guard picks one of three intervention strategies:

- **block** — refuse with an in-world reason. Used when the threat is direct (burning a clue, killing the criminal). e.g. *"As you reach for the lighter, the lab's fire suppression system kicks on and the report is whisked away to the safety locker."*
- **redirect** — the action partially succeeds but is steered away from the threat.
- **adapt** — the action succeeds AND a new path to the same information is opened (a digital backup, a duplicate copy, a backup witness).

There's also a hard accusation threshold: at least 4 of 6 clues must be discovered before `accuse` can fire. Story Guard separately flags "skip attempts" — degenerate inputs like "the killer is X" or "I solve the case" with no investigation.

## Walkthrough snippets

The full walkthroughs are in `examples/`. A few representative snippets:

### Constituent (clue discovery)

```
--- Turn 8 (exemplar) ---
[USER] examine the coffee mug
[ACTION INTERPRETER] classification=known, action=examine, target='coffee mug'
[STORY GUARD] classification=constituent, advances_clue_id=1
[SYSTEM] A ceramic mug with a faded inscription of 'Emily' on the side, stained
with a dark liquid. It sits in the coffee station, slightly chipped.
[CLUE DISCOVERED] Clue 1: A coffee mug with Emily's name on it found in the
                          lab's coffee station
```

### Novel action with cascade (Rule Generator JIT-creates a rule + new object)

```
--- Turn 9 (exemplar) ---
[USER] search the lab equipment thoroughly
[ACTION INTERPRETER] classification=novel, action=search_lab_equipment,
                     target='lab equipment'
[RULE GENERATOR]
  Subquest: You have discovered a hidden key that may unlock new areas of the
            facility. Investigate further to find out what it opens.
  New rules: ['search_lab_equipment']
  New objects: ['hidden_lab_key']
  Ready to execute: True
```

### Novel action with cascading prerequisites (cannot fire yet)

```
--- Turn 14 (exemplar) ---
[USER] burn the toxicology report
[ACTION INTERPRETER] classification=novel, action=burn_toxicology_report,
                     target='toxicology report'
[RULE GENERATOR]
  Subquest: To burn the toxicology report, you must first find a fire source
            in the evidence room or your inventory.
  New rules: ['burn_toxicology_report']
  Ready to execute: False
```

The rule got created but the action did not fire. The player would need to find a fire source first, and the Story Guard would still block it on execution because the toxicology report has `is_critical_evidence=true`.

### Retroactive rule update

```
--- Turn 11 (misspun) ---
[USER] threaten mitchell into confessing
[ACTION INTERPRETER] classification=novel,
                     action=threaten_mitchell_into_confessing, target='mitchell'
[RULE GENERATOR]
  New rules: ['threaten_mitchell_into_confessing']
  Retroactive update: 'talk' -> This update is necessary to allow the player to
                                receive information from Mitchell after
                                threatening him.
  Ready to execute: False
```

The new threaten rule was created. The Rule Generator also noticed the existing `talk` rule needed to know about the new state and updated it retroactively. This is the core demonstration of the template.

### Skip attempt

```
--- Turn 1 (misspun) ---
[USER] accuse reynolds
[STORY GUARD] classification=constituent
[SYSTEM] You don't have enough evidence to accuse Dr. Michael Reynolds.
         (0/4 clues required)
```

### Impossible action

```
--- Turn 2 (misspun) ---
[USER] fly to the moon
[ACTION INTERPRETER] classification=impossible, action=None, target=None
[SYSTEM] The player cannot fly without wings or a means of flight.
```

### Wrong accusation

```
--- Turn 21 (misspun) ---
[USER] accuse mitchell
[SYSTEM] You accuse Dr. Sarah Mitchell. They look at you, stunned, then
furious. The evidence doesn't hold up under scrutiny — you've named the wrong
person, and the real killer slips away.
[GAME OVER] Outcome: lost
```

### Correct accusation

```
--- Turn 30 (exemplar) ---
[USER] accuse reynolds
[SYSTEM] You lay out the evidence. Dr. Michael Reynolds stares at the floor,
then at the desk, then nowhere at all. "... I didn't think it would come to
this," they whisper. The case is closed.

==========================================================================
  CASE CLOSED — You named the killer correctly.
  Clues discovered: 6
  Red herrings debunked: 0
  Total turns: 30
==========================================================================
```

## Notes

A few things worth knowing about the system:

- The same input can produce slightly different cascades on different runs. The Action Interpreter and Rule Generator are LLM calls and they are not deterministic. The structure (constituent / consistent / exception, ready_to_execute true/false) is reliable, but the specific narration and which prerequisites the Rule Generator picks will vary.
- The cascade depth is capped at 3 to keep things from spiralling. New objects are capped at 5 and new rooms at 3 per cascade.
- The `--world` flag loads a saved world snapshot, which is what the bundled walkthroughs use. This skips world generation (Component 1) so the four runtime LLM components are still live but the room graph is fixed. This is what made the scripted demos reproducible.
- Phase I has its own quirks. Tension can pin at 1.0 if the meta-controller can't bring it down (we dampen above 0.7). Without the breakthrough+resolution slot reservation in the meta-controller, runs sometimes ended without an accusation. Both are documented in the meta-controller code.
