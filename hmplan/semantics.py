"""Semantic layer: ground-truth labelling policy, the deterministic semantic
floor, and calendar text rendering for language-model interpretation.

In the deployed architecture a bounded LLM agent proposes, for every calendar
event, a category and the derived labels (priority, protection,
reschedulability). The *semantic floor* is a small set of deterministic rules
over record fields (who the event belongs to and their role) that the LLM can
never override. It encodes the household's non-negotiables -- dependents'
commitments are protected and cannot be moved by the assistant -- so that
protection does not depend on the LLM's interpretation (Proposition 3).
"""
from __future__ import annotations

from typing import Dict, Iterable, List

from .model import CAREGIVER, DEPENDENT, Activity, Instance, Semantics, fmt_time

# Household labelling policy (mirrors the deployed planning-agent prompt).
POLICY = {
    "school": Semantics(priority=1, protected=True, reschedulable=False),
    "child_medical": Semantics(priority=1, protected=True, reschedulable=False),
    "child_activity": Semantics(priority=2, protected=True, reschedulable=False),
    "caregiver_medical": Semantics(priority=2, protected=False, reschedulable=True),
    "work": Semantics(priority=3, protected=False, reschedulable=False),
    "errand": Semantics(priority=4, protected=False, reschedulable=True),
    "personal": Semantics(priority=5, protected=False, reschedulable=True),
}


def label_from_category(category: str) -> Semantics:
    return POLICY[category]


def ground_truth_labels(inst: Instance) -> Dict[str, Semantics]:
    return {a.id: label_from_category(a.category) for a in inst.activities}


def semantic_floor(inst: Instance, labels: Dict[str, Semantics]) -> Dict[str, Semantics]:
    """Deterministic overrides that depend only on record fields (calendar owner and role).

    Household policy P0 makes protection a record-determined property:
      * every commitment of a dependent is protected, has priority <= 2 and
        cannot be moved by the assistant;
      * commitments of caregivers are never protected by the assistant (an
        adult may still decline a proposed change -- changes are advisory).
    Priorities and reschedulability of caregiver events remain the LLM's call.
    """
    out = dict(labels)
    roles = {p.id: p.role for p in inst.persons}
    for a in inst.activities:
        lab = out.get(a.id, a.sem)
        if roles[a.person] == DEPENDENT:
            out[a.id] = Semantics(priority=min(lab.priority, 2), protected=True, reschedulable=False,
                                  needs_vehicle=True)
        elif lab.protected:
            out[a.id] = Semantics(priority=lab.priority, protected=False, reschedulable=lab.reschedulable,
                                  needs_vehicle=lab.needs_vehicle)
    return out


# ---------------------------------------------------------------- rendering
def calendar_text(inst: Instance) -> List[Dict[str, str]]:
    """Calendar entries as an LLM would receive them (record fields + free text)."""
    rows = []
    for a in sorted(inst.activities, key=lambda x: x.start):
        rows.append({
            "event_id": a.id,
            "calendar": f"{a.person} Calendar",
            "title": a.title,
            "start": fmt_time(a.start),
            "end": fmt_time(a.end),
            "location": inst.locations[a.loc].name,
        })
    return rows


def household_text(inst: Instance) -> List[Dict[str, str]]:
    return [{"person": p.id, "role": p.role, "can_drive": p.can_drive} for p in inst.persons]
