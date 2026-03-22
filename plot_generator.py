import json
from models import CrimeSchema, PlotPointSpec, PlotPoint
from llm import call_llm_json

SYSTEM_PROMPT = """You are a suspenseful crime fiction writer. You write vivid, tense scenes
for a murder mystery investigation. Each scene should feel grounded and specific - avoid
generic phrases like "something felt off" or "the detective had a hunch." Instead, show
concrete actions, dialogue, and physical details.

Write in third person past tense. The detective's name is Detective Mara Chen.
You always respond in valid JSON."""


def generate_plot_point(schema: CrimeSchema, spec: PlotPointSpec,
                        previous_points: list[PlotPoint]):
    # Build context from previous plot points
    story_so_far = ""
    if previous_points:
        recent = previous_points[-3:]  # last 3 for context window
        for pp in recent:
            story_so_far += f"\n[Plot Point {pp.number} - {pp.title}]\n{pp.narrative}\n"

    # Build detective's current knowledge
    known_clues = []
    for pp in previous_points:
        for cid in pp.clues_revealed:
            for clue in schema.evidence_chain:
                if clue.id == cid:
                    known_clues.append(clue.description)

    knowledge_summary = "The detective currently knows:\n"
    if known_clues:
        for k in known_clues:
            knowledge_summary += f"- {k}\n"
    else:
        knowledge_summary += "- Nothing yet. The investigation is just beginning.\n"

    # Don't leak the criminal identity to the plot generator (unless it's the resolution)
    setting_info = f"Setting: {schema.setting}\nVictim: {schema.victim} - {schema.victim_background}"
    if spec.event_type != "resolution":
        suspect_info = ""
        for s in schema.suspects:
            suspect_info += f"- {s.name} ({s.role}): {s.alibi}\n"
    else:
        suspect_info = ""
        for s in schema.suspects:
            label = " [THE CRIMINAL]" if s.is_criminal else ""
            suspect_info += f"- {s.name} ({s.role}){label}\n"

    spec_json = json.dumps(spec.to_dict(), indent=2)

    user_prompt = f"""{setting_info}

Suspects:
{suspect_info}

{knowledge_summary}

Recent story context:
{story_so_far if story_so_far else "(Beginning of investigation)"}

Generate the next plot point based on this specification:
{spec_json}

Respond as JSON:
{{
  "title": "short evocative title for this scene (3-6 words)",
  "narrative": "the full scene text, 150-300 words. Be specific and vivid. Include dialogue where appropriate. Show, don't tell.",
  "clues_revealed": [list of clue IDs revealed in this scene, empty list if none],
  "red_herrings_encountered": [list of red herring IDs encountered, empty list if none],
  "red_herrings_debunked": [list of red herring IDs debunked, empty list if none]
}}

The narrative should feel like a chapter from a detective novel - atmospheric and tense.
Do NOT include the plot point number or metadata in the narrative text itself."""

    data = call_llm_json(SYSTEM_PROMPT, user_prompt, temperature=0.85)

    plot_point = PlotPoint(
        number=spec.point_number,
        event_type=spec.event_type,
        subtype=spec.subtype,
        title=data["title"],
        narrative=data["narrative"],
        tension_level=0.0,  # filled in by controller
        clues_revealed=data.get("clues_revealed", []),
        red_herrings_encountered=data.get("red_herrings_encountered", []),
        red_herrings_debunked=data.get("red_herrings_debunked", []),
    )

    return plot_point
