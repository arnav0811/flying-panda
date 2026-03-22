from models import CrimeSchema, Suspect, Clue
from llm import call_llm_json

SYSTEM_PROMPT = """You are a crime fiction architect. You design intricate murder mysteries
with carefully constructed clue chains, complex suspect webs, and layered motives.
You always respond in valid JSON."""

def generate_crime_schema(setting, num_suspects=4):
    user_prompt = f"""Create a murder mystery set in: {setting}

Generate a complete crime schema as JSON with these exact fields:

{{
  "setting": "{setting}",
  "victim": "full name",
  "victim_background": "2-3 sentences about the victim, their role, why people might want them dead",
  "criminal_name": "full name of the guilty suspect",
  "method": "how the murder was committed (specific, not vague)",
  "motive": "the criminal's real motive (specific and personal)",
  "suspects": [
    {{
      "name": "full name",
      "role": "their position/role in the setting",
      "means": "what tools/access/capability they have that could be used for murder",
      "means_score": 1-5,
      "motive": "their specific reason to want the victim dead",
      "motive_score": 1-5,
      "opportunity": "why they could have been at the scene",
      "opportunity_score": 1-5,
      "alibi": "their stated alibi",
      "alibi_is_false": true/false,
      "alibi_real_reason": "if alibi is false, what they were actually doing (empty string if alibi is true)",
      "is_criminal": true/false
    }}
  ],
  "evidence_chain": [
    {{
      "id": 1,
      "description": "what the clue is",
      "points_to": "what this clue points toward",
      "requires_clue": null for first clue or id of prerequisite clue,
      "discovery_method": "how the detective finds this clue"
    }}
  ]
}}

IMPORTANT CONSTRAINTS:
- Exactly {num_suspects} suspects, one of whom is the criminal.
- At least 2 innocent suspects must have HIGH scores (4-5) in ALL three of means, motive, and opportunity. This prevents trivial elimination.
- At least 1 innocent suspect must have a FALSE alibi (they lied about where they were for personal/embarrassing reasons, but they didn't commit the crime).
- The criminal must have a PLAUSIBLE alibi that seems solid on the surface but can be debunked through investigation.
- The evidence chain must have exactly 6 clues, ordered so each clue leads to the next. Clue 1 has requires_clue: null. Clue 2 has requires_clue: 1. And so on.
- Each clue should be concrete and specific (a physical object, a witness statement, a record, etc.), not abstract.
- The criminal's motive should be deeply personal, not generic.
- Make suspects interconnected - they should have relationships with each other, not just with the victim."""

    data = call_llm_json(SYSTEM_PROMPT, user_prompt, temperature=0.9)

    suspects = []
    for s in data["suspects"]:
        suspects.append(Suspect(
            name=s["name"],
            role=s["role"],
            means=s["means"],
            means_score=s["means_score"],
            motive=s["motive"],
            motive_score=s["motive_score"],
            opportunity=s["opportunity"],
            opportunity_score=s["opportunity_score"],
            alibi=s["alibi"],
            alibi_is_false=s["alibi_is_false"],
            alibi_real_reason=s.get("alibi_real_reason", ""),
            is_criminal=s["is_criminal"],
        ))

    evidence = []
    for c in data["evidence_chain"]:
        evidence.append(Clue(
            id=c["id"],
            description=c["description"],
            points_to=c["points_to"],
            requires_clue=c["requires_clue"],
            discovery_method=c["discovery_method"],
        ))

    schema = CrimeSchema(
        setting=data["setting"],
        victim=data["victim"],
        victim_background=data["victim_background"],
        criminal_name=data["criminal_name"],
        method=data["method"],
        motive=data["motive"],
        suspects=suspects,
        evidence_chain=evidence,
    )

    return schema
