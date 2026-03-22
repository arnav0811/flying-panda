from models import CrimeSchema, PlotPoint
from llm import call_llm

SYSTEM_PROMPT = """You are an expert fiction editor specializing in mystery novels. Your job
is to take a series of plot point scenes and weave them into a cohesive, polished mystery
story. You ensure consistent character voice, smooth transitions between scenes, and
a satisfying narrative arc.

Maintain third person past tense throughout. Keep Detective Mara Chen's voice consistent -
she is sharp, methodical, but human."""


def compile_story(schema: CrimeSchema, plot_points: list[PlotPoint]):
    # Build the raw material
    scenes = ""
    for pp in plot_points:
        scenes += f"\n--- PLOT POINT {pp.number}: {pp.title} ---\n"
        scenes += f"[Type: {pp.event_type} / {pp.subtype}]\n"
        scenes += f"{pp.narrative}\n"

    crime_summary = (
        f"Setting: {schema.setting}\n"
        f"Victim: {schema.victim} ({schema.victim_background})\n"
        f"Criminal: {schema.criminal_name}\n"
        f"Method: {schema.method}\n"
        f"Motive: {schema.motive}\n"
    )

    user_prompt = f"""Here is the ground truth of the crime:
{crime_summary}

Here are the {len(plot_points)} plot point scenes in order:
{scenes}

Compile these into a single cohesive mystery story. Your tasks:

1. Write smooth transitions between scenes so the story flows naturally.
2. Ensure character names and details are consistent throughout.
3. Add atmospheric details that reinforce the setting ({schema.setting}).
4. Keep each plot point as a distinct section with its number and title as a header, like:
   "## Plot Point 1: [Title]"
5. Do NOT remove or skip any plot points. Every single one must appear.
6. You may add brief bridging paragraphs between plot points, but don't invent new major events.
7. Add a brief opening paragraph before Plot Point 1 to set the scene.
8. The total story should feel like a complete mystery novella.

Write the full compiled story now."""

    story = call_llm(SYSTEM_PROMPT, user_prompt, temperature=0.7)
    return story


def generate_crime_story(schema: CrimeSchema):
    """Generate the backstory of how the crime was committed."""
    crime_summary = (
        f"Setting: {schema.setting}\n"
        f"Victim: {schema.victim} ({schema.victim_background})\n"
        f"Criminal: {schema.criminal_name}\n"
        f"Method: {schema.method}\n"
        f"Motive: {schema.motive}\n\n"
        f"Suspects and their relationships:\n"
    )
    for s in schema.suspects:
        label = " [THE CRIMINAL]" if s.is_criminal else ""
        crime_summary += (
            f"- {s.name}{label} ({s.role}): "
            f"Motive: {s.motive}. Alibi: {s.alibi}.\n"
        )

    crime_summary += f"\nEvidence chain:\n"
    for c in schema.evidence_chain:
        crime_summary += f"- Clue {c.id}: {c.description}\n"

    user_prompt = f"""Based on this crime schema, write the "crime story" - the hidden backstory
of what actually happened, told from an omniscient perspective. This is the story of
how {schema.criminal_name} committed the murder and what led up to it.

{crime_summary}

Write 400-600 words covering:
1. The criminal's relationship with the victim and building resentment/motive
2. The planning of the crime
3. The night of the murder - what actually happened step by step
4. The immediate aftermath and cover-up attempts

Write it as compelling narrative, not a police report. Third person past tense."""

    return call_llm(SYSTEM_PROMPT, user_prompt, temperature=0.8)
