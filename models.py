from dataclasses import dataclass, field
from typing import Optional
import json


@dataclass
class Suspect:
    name: str
    role: str
    means: str
    means_score: int          # 1-5
    motive: str
    motive_score: int         # 1-5
    opportunity: str
    opportunity_score: int    # 1-5
    alibi: str
    alibi_is_false: bool
    alibi_real_reason: str    # what they were actually doing if alibi is false
    is_criminal: bool

    def to_dict(self):
        return {
            "name": self.name,
            "role": self.role,
            "means": self.means,
            "means_score": self.means_score,
            "motive": self.motive,
            "motive_score": self.motive_score,
            "opportunity": self.opportunity,
            "opportunity_score": self.opportunity_score,
            "alibi": self.alibi,
            "alibi_is_false": self.alibi_is_false,
            "alibi_real_reason": self.alibi_real_reason,
            "is_criminal": self.is_criminal,
        }


@dataclass
class Clue:
    id: int
    description: str
    points_to: str            # which suspect or evidence this leads to
    requires_clue: Optional[int]  # id of the clue that must be found first (None for first clue)
    discovery_method: str     # how the detective finds this

    def to_dict(self):
        return {
            "id": self.id,
            "description": self.description,
            "points_to": self.points_to,
            "requires_clue": self.requires_clue,
            "discovery_method": self.discovery_method,
        }


@dataclass
class RedHerring:
    id: str
    description: str
    planted_evidence: str
    target_suspect: str       # innocent suspect this points to
    fragility: int            # 1-3, how many steps to debunk
    debunk_method: str

    def to_dict(self):
        return {
            "id": self.id,
            "description": self.description,
            "planted_evidence": self.planted_evidence,
            "target_suspect": self.target_suspect,
            "fragility": self.fragility,
            "debunk_method": self.debunk_method,
        }


@dataclass
class CrimeSchema:
    setting: str
    victim: str
    victim_background: str
    criminal_name: str
    method: str
    motive: str
    suspects: list[Suspect]
    evidence_chain: list[Clue]
    red_herrings: list[RedHerring] = field(default_factory=list)

    def to_dict(self):
        return {
            "setting": self.setting,
            "victim": self.victim,
            "victim_background": self.victim_background,
            "criminal_name": self.criminal_name,
            "method": self.method,
            "motive": self.motive,
            "suspects": [s.to_dict() for s in self.suspects],
            "evidence_chain": [c.to_dict() for c in self.evidence_chain],
            "red_herrings": [r.to_dict() for r in self.red_herrings],
        }

    def to_json(self, indent=2):
        return json.dumps(self.to_dict(), indent=indent)

    def get_criminal(self):
        for s in self.suspects:
            if s.is_criminal:
                return s
        return None

    def get_innocent_suspects(self):
        return [s for s in self.suspects if not s.is_criminal]

    def without_criminal_identity(self):
        """Return a dict version with criminal identity removed (for red herring generation)."""
        d = self.to_dict()
        d.pop("criminal_name")
        for s in d["suspects"]:
            s.pop("is_criminal")
        return d


@dataclass
class PlotPointSpec:
    """What the meta-controller tells the plot generator to produce."""
    point_number: int
    event_type: str           # clue_discovery, red_herring_encounter, obstacle,
                              # suspect_confrontation, criminal_interference,
                              # breakthrough, resolution, false_lead
    subtype: str              # more specific description
    target_tension: float     # what tension level we're aiming for
    details: dict             # specific instructions for this plot point

    def to_dict(self):
        return {
            "point_number": self.point_number,
            "event_type": self.event_type,
            "subtype": self.subtype,
            "target_tension": self.target_tension,
            "details": self.details,
        }


@dataclass
class PlotPoint:
    """A generated plot point with its narrative text."""
    number: int
    event_type: str
    subtype: str
    title: str
    narrative: str
    tension_level: float
    clues_revealed: list[int] = field(default_factory=list)
    red_herrings_encountered: list[str] = field(default_factory=list)
    red_herrings_debunked: list[str] = field(default_factory=list)

    def to_dict(self):
        return {
            "number": self.number,
            "event_type": self.event_type,
            "subtype": self.subtype,
            "title": self.title,
            "narrative": self.narrative,
            "tension_level": self.tension_level,
            "clues_revealed": self.clues_revealed,
            "red_herrings_encountered": self.red_herrings_encountered,
            "red_herrings_debunked": self.red_herrings_debunked,
        }
