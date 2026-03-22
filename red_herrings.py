import json
from models import CrimeSchema, RedHerring
from llm import call_llm_json

SYSTEM_PROMPT = """You are a mystery writer specializing in misdirection. You create convincing
red herrings - misleading clues that point toward innocent suspects. You do NOT know who the
real criminal is. Your job is to make the investigation harder by adding plausible but
ultimately false evidence trails. You always respond in valid JSON."""


def inject_red_herrings(schema: CrimeSchema, num_herrings=3):
    # Strip criminal identity so the LLM can't bias toward them
    sanitized = schema.without_criminal_identity()

    suspect_names = [s["name"] for s in sanitized["suspects"]]
    suspect_info = json.dumps(sanitized["suspects"], indent=2)

    user_prompt = f"""Here is a murder mystery scenario:

Setting: {sanitized['setting']}
Victim: {sanitized['victim']} - {sanitized['victim_background']}
Method: {sanitized['method']}

Suspects:
{suspect_info}

Generate exactly {num_herrings} red herrings as JSON. Each red herring should be a piece of
misleading evidence that makes an innocent suspect look guilty.

{{
  "red_herrings": [
    {{
      "id": "rh1",
      "description": "what this misleading evidence is",
      "planted_evidence": "the specific physical or testimonial evidence",
      "target_suspect": "name of the suspect this points to (pick from: {', '.join(suspect_names)})",
      "fragility": 1-3 (1 = easy to debunk in one step, 3 = takes multiple investigation steps),
      "debunk_method": "how the detective eventually realizes this is a red herring"
    }}
  ]
}}

RULES:
- Each red herring must point to a DIFFERENT suspect if possible.
- Red herrings should feel convincing at first - not obviously fake.
- The debunk method should require actual investigation work, not just intuition.
- At least one red herring should have fragility 3 (hard to debunk).
- Make each red herring connected to the actual crime scene or victim, not random."""

    data = call_llm_json(SYSTEM_PROMPT, user_prompt, temperature=0.9)

    herrings = []
    for rh in data["red_herrings"]:
        herrings.append(RedHerring(
            id=rh["id"],
            description=rh["description"],
            planted_evidence=rh["planted_evidence"],
            target_suspect=rh["target_suspect"],
            fragility=rh["fragility"],
            debunk_method=rh["debunk_method"],
        ))

    schema.red_herrings = herrings
    return schema
