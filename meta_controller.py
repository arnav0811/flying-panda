"""
Stage 3: Suspense Meta-Controller

It is a state machine thatcontrols the pacing of the investigation by deciding what type of plot point
should happen next.
Inputs: CrimeSchema 
Outputs: PlotPointSpec objects that tell the Plot Point Generator (Stage 4)
         what kind of scene to write.

Key responsibilities:
- Maintains a target tension curve 
- Tracks which clues have been revealed, which red herrings encountered/debunked
- Picks event types (clue_discovery, obstacle, red_herring_encounter, etc.)
  based on tension change, progress, and variety constraints
- Guarantees a breakthrough + resolution at the end of the story
- Updates internal state after each plot point is generated (feedback loop,
  shown as yellow arrow in architecture diagram)
"""

import random
import math
from models import CrimeSchema, PlotPointSpec, PlotPoint


class SuspenseController:
    """
    Non-LLM state machine that controls the pacing of the investigation.
    Tracks detective knowledge, tension level, and decides what type of
    plot point should happen next based on a target tension curve.
    """

    # Event types and how they affect tension
    TENSION_EFFECTS = {
        "clue_discovery": 0.08,
        "red_herring_encounter": 0.06,
        "false_lead": -0.04,
        "obstacle": 0.10,
        "suspect_confrontation": 0.07,
        "criminal_interference": 0.15,
        "breakthrough": 0.12,
        "resolution": 0.05,
    }

    # Subtypes for each event type
    SUBTYPES = {
        "clue_discovery": [
            "physical_evidence", "witness_testimony", "forensic_result",
            "document_found", "surveillance_footage", "digital_trace",
        ],
        "red_herring_encounter": [
            "suspicious_item", "false_witness", "misleading_record",
            "planted_evidence", "coincidental_connection",
        ],
        "false_lead": [
            "alibi_debunked_innocent", "misinterpreted_evidence",
            "dead_end_lead", "witness_recants",
        ],
        "obstacle": [
            "witness_intimidated", "evidence_tampered", "access_denied",
            "suspect_flees", "legal_barrier",
        ],
        "suspect_confrontation": [
            "interrogation", "alibi_challenge", "evidence_presented",
            "bluff_play", "emotional_appeal",
        ],
        "criminal_interference": [
            "evidence_destroyed", "witness_threatened", "false_evidence_planted",
            "detective_warned", "accomplice_distraction",
        ],
        "breakthrough": [
            "alibi_cracked", "key_connection_found", "confession_partial",
            "forensic_match", "timeline_contradiction",
        ],
        "resolution": [
            "final_confrontation", "full_reveal", "arrest",
        ],
    }

    def __init__(self, schema: CrimeSchema, num_plot_points=16):
        self.schema = schema
        self.num_plot_points = num_plot_points
        self.min_plot_points = 15  # minimum required by rubric

        # State tracking
        self.revealed_clues = set()
        self.encountered_herrings = set()
        self.debunked_herrings = set()
        self.active_leads = []
        self.active_suspect = None  # currently under investigation
        self.tension_history = [0.0]
        self.current_tension = 0.0
        self.plot_points_generated = 0

        # Track recently used types to avoid repetition
        self.recent_types = []
        self.recent_subtypes = []

        # Build the target tension curve
        self.target_curve = self._build_tension_curve()

    def _build_tension_curve(self):
        """
        Build a target tension curve that follows a mystery arc:
        - Slow build in act 1 (first ~25%)
        - Rising tension with dips in act 2 (middle ~50%)
        - Peak and resolution in act 3 (last ~25%)
        """
        n = self.num_plot_points
        curve = []
        for i in range(n):
            progress = i / (n - 1)

            if progress < 0.25:
                # Act 1: slow build, discovery phase
                target = 0.15 + 0.2 * (progress / 0.25)
            elif progress < 0.75:
                # Act 2: rising with oscillation
                act2_progress = (progress - 0.25) / 0.50
                base = 0.35 + 0.35 * act2_progress
                # Add some wave to prevent monotonic rise
                wave = 0.05 * math.sin(act2_progress * math.pi * 3)
                target = base + wave
            else:
                # Act 3: peak then resolution
                act3_progress = (progress - 0.75) / 0.25
                if act3_progress < 0.6:
                    # Build to peak
                    target = 0.70 + 0.25 * (act3_progress / 0.6)
                else:
                    # Resolution drop
                    target = 0.95 - 0.30 * ((act3_progress - 0.6) / 0.4)

            curve.append(round(target, 3))

        return curve

    def get_progress(self):
        total_clues = len(self.schema.evidence_chain)
        if total_clues == 0:
            return 0.0
        return len(self.revealed_clues) / total_clues

    def _pick_event_type(self):
        """Decide what type of event should happen next based on tension delta and progress."""
        progress = self.get_progress()
        point_progress = self.plot_points_generated / self.num_plot_points
        target = self.target_curve[min(self.plot_points_generated, len(self.target_curve) - 1)]
        delta = target - self.current_tension
        tolerance = 0.1

        # Last plot point is ALWAYS resolution
        if self.plot_points_generated == self.num_plot_points - 1:
            return "resolution"

        # Second to last -> breakthrough to set up the resolution
        if self.plot_points_generated == self.num_plot_points - 2:
            return "breakthrough"

        # Near end, most clues found -> breakthrough
        if point_progress >= 0.75 and progress >= 0.7:
            return "breakthrough"

        # Criminal interference when detective is getting close
        if progress > 0.7 and "criminal_interference" not in self.recent_types[-2:]:
            if random.random() < 0.6:
                return "criminal_interference"

        # Build weight map based on tension needs
        weights = {}

        if delta > tolerance:
            # Need MORE tension
            weights["obstacle"] = 3.0
            weights["criminal_interference"] = 2.0
            weights["red_herring_encounter"] = 2.0
            weights["clue_discovery"] = 1.5
            weights["suspect_confrontation"] = 2.0
        elif delta < -tolerance:
            # Tension too HIGH, dial back
            weights["false_lead"] = 3.0
            weights["clue_discovery"] = 2.0
            weights["suspect_confrontation"] = 1.5
        else:
            # On track - balanced mix
            weights["clue_discovery"] = 2.5
            weights["suspect_confrontation"] = 2.0
            weights["red_herring_encounter"] = 1.5
            weights["obstacle"] = 1.0
            weights["false_lead"] = 1.0

        # Reduce weight of recently used types
        for t in self.recent_types[-3:]:
            if t in weights:
                weights[t] *= 0.3

        # Must reveal clues so we actually solve the crime
        unrevealed = len(self.schema.evidence_chain) - len(self.revealed_clues)
        remaining_points = self.num_plot_points - self.plot_points_generated
        if unrevealed > 0 and remaining_points > 0:
            # Force clue discovery if we're running out of time
            if unrevealed >= remaining_points - 2:
                return "clue_discovery"
            if unrevealed >= remaining_points * 0.5:
                weights["clue_discovery"] = max(weights.get("clue_discovery", 0), 4.0)

        # If we haven't encountered any red herrings yet and we're past the start
        if (len(self.encountered_herrings) == 0 and
                len(self.schema.red_herrings) > 0 and point_progress > 0.1):
            weights["red_herring_encounter"] = max(weights.get("red_herring_encounter", 0), 3.0)

        # Can't encounter herrings if none are left
        unencountered = set(rh.id for rh in self.schema.red_herrings) - self.encountered_herrings
        if not unencountered:
            weights.pop("red_herring_encounter", None)

        # Can't debunk herrings if none have been encountered but not debunked
        debunkable = self.encountered_herrings - self.debunked_herrings
        if not debunkable:
            weights.pop("false_lead", None)

        # Filter out anything with 0 or negative weight
        weights = {k: v for k, v in weights.items() if v > 0}

        if not weights:
            return "clue_discovery"

        types = list(weights.keys())
        probs = list(weights.values())
        total = sum(probs)
        probs = [p / total for p in probs]

        return random.choices(types, weights=probs, k=1)[0]

    def _pick_subtype(self, event_type):
        available = self.SUBTYPES.get(event_type, ["generic"])
        # Avoid recently used subtypes
        filtered = [s for s in available if s not in self.recent_subtypes[-4:]]
        if not filtered:
            filtered = available
        return random.choice(filtered)

    def _build_details(self, event_type, subtype):
        """Build specific instructions for the plot point generator."""
        details = {}
        schema = self.schema

        if event_type == "clue_discovery":
            # Find the next clue in the chain that can be revealed
            next_clue = None
            for clue in schema.evidence_chain:
                if clue.id not in self.revealed_clues:
                    if clue.requires_clue is None or clue.requires_clue in self.revealed_clues:
                        next_clue = clue
                        break
            if next_clue:
                details["clue"] = next_clue.to_dict()
                details["auto_reveal_clue"] = next_clue.id  # controller tracks this
                details["instruction"] = (
                    f"The detective discovers: {next_clue.description}. "
                    f"Method: {next_clue.discovery_method}. "
                    f"This points toward: {next_clue.points_to}."
                )
            else:
                # All clues revealed or blocked, just do a confrontation instead
                details["instruction"] = "The detective reviews existing evidence and notices a new connection."

        elif event_type == "red_herring_encounter":
            unencountered = [rh for rh in schema.red_herrings if rh.id not in self.encountered_herrings]
            if unencountered:
                herring = random.choice(unencountered)
                details["red_herring"] = herring.to_dict()
                details["instruction"] = (
                    f"The detective encounters misleading evidence: {herring.planted_evidence}. "
                    f"This seems to point toward {herring.target_suspect}."
                )

        elif event_type == "false_lead":
            debunkable = [rh for rh in schema.red_herrings
                         if rh.id in self.encountered_herrings and rh.id not in self.debunked_herrings]
            if debunkable:
                herring = random.choice(debunkable)
                details["red_herring"] = herring.to_dict()
                details["instruction"] = (
                    f"The detective realizes the evidence pointing to {herring.target_suspect} "
                    f"is a dead end. {herring.debunk_method}"
                )

        elif event_type == "obstacle":
            details["instruction"] = (
                f"The detective faces a {subtype.replace('_', ' ')}. "
                f"This blocks progress temporarily and raises stakes."
            )

        elif event_type == "suspect_confrontation":
            suspect = random.choice(schema.suspects)
            self.active_suspect = suspect.name
            details["suspect"] = suspect.to_dict()
            details["instruction"] = (
                f"The detective confronts {suspect.name} ({subtype.replace('_', ' ')}). "
                f"Their alibi: '{suspect.alibi}'. "
            )
            if suspect.alibi_is_false:
                details["instruction"] += "The alibi has cracks that could be exposed."
            else:
                details["instruction"] += "The alibi appears solid under pressure."

        elif event_type == "criminal_interference":
            criminal = schema.get_criminal()
            details["instruction"] = (
                f"The criminal ({criminal.name}, though the detective may not know yet) "
                f"takes action to protect themselves: {subtype.replace('_', ' ')}. "
                f"This should feel threatening and raise the stakes significantly."
            )

        elif event_type == "breakthrough":
            criminal = schema.get_criminal()
            details["instruction"] = (
                f"A major breakthrough: {subtype.replace('_', ' ')}. "
                f"The evidence is starting to converge on {criminal.name}. "
                f"The detective is close to the truth."
            )

        elif event_type == "resolution":
            criminal = schema.get_criminal()
            details["instruction"] = (
                f"The resolution: {subtype.replace('_', ' ')}. "
                f"The criminal is {criminal.name}. "
                f"Method: {schema.method}. Motive: {schema.motive}. "
                f"Bring the investigation to a satisfying close."
            )

        return details

    def next_plot_point_spec(self):
        """Generate the specification for the next plot point."""
        if self.plot_points_generated >= self.num_plot_points:
            return None

        event_type = self._pick_event_type()
        subtype = self._pick_subtype(event_type)
        target = self.target_curve[min(self.plot_points_generated, len(self.target_curve) - 1)]
        details = self._build_details(event_type, subtype)

        spec = PlotPointSpec(
            point_number=self.plot_points_generated + 1,
            event_type=event_type,
            subtype=subtype,
            target_tension=target,
            details=details,
        )

        return spec

    def update_state(self, plot_point: PlotPoint, spec: PlotPointSpec = None):
        """Update controller state after a plot point is generated."""
        # Track revealed clues from LLM response
        for clue_id in plot_point.clues_revealed:
            self.revealed_clues.add(clue_id)

        # Also auto-reveal clue if the controller assigned one
        if spec and "auto_reveal_clue" in spec.details:
            cid = spec.details["auto_reveal_clue"]
            self.revealed_clues.add(cid)
            if cid not in plot_point.clues_revealed:
                plot_point.clues_revealed.append(cid)

        # Track red herring state
        for rh_id in plot_point.red_herrings_encountered:
            self.encountered_herrings.add(rh_id)
        for rh_id in plot_point.red_herrings_debunked:
            self.debunked_herrings.add(rh_id)

        # Update tension
        if plot_point.event_type == "resolution":
            # Resolution brings tension down for a satisfying close
            self.current_tension = max(0.0, self.current_tension - 0.25)
        else:
            base_effect = self.TENSION_EFFECTS.get(plot_point.event_type, 0.05)
            noise = random.uniform(-0.03, 0.03)
            # Dampen gains as tension gets high so we don't pin at 1.0
            if self.current_tension > 0.7:
                base_effect *= (1.0 - self.current_tension) * 2
            self.current_tension = max(0.0, min(0.98, self.current_tension + base_effect + noise))
        plot_point.tension_level = self.current_tension
        self.tension_history.append(self.current_tension)

        # Track recent types for variety
        self.recent_types.append(plot_point.event_type)
        self.recent_subtypes.append(plot_point.subtype)

        self.plot_points_generated += 1

    def is_done(self):
        """Only done after resolution has been generated."""
        has_resolution = "resolution" in self.recent_types
        max_points = self.plot_points_generated >= self.num_plot_points

        if has_resolution:
            return True
        if max_points:
            return True
        return False
