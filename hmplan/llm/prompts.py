"""Prompts for the bounded language-model roles.

The interpretation prompt is deliberately narrow: the model only classifies
events. It never sees coordinates, travel times or the vehicle state, and its
output is validated against a JSON schema before the semantic floor and the
solver use it. The LLM-only planning prompt is used solely as a baseline.
"""
from __future__ import annotations

import json
from typing import Dict, List

CATEGORY_GUIDE = """Categories:
- school: a dependent's school or daycare day (drop-off and pickup)
- child_activity: a dependent's extracurricular activity (sport, music, dance, lesson, practice, class)
- child_medical: a dependent's medical or dental appointment
- work: a caregiver's work, meeting, research or office commitment
- caregiver_medical: a caregiver's medical, dental or health appointment
- errand: administrative appointment (accountant, bank, notary, insurance, passport)
- personal: flexible personal activity (gym, yoga, social, haircut, club)"""

POLICY_GUIDE = """Household policy:
- dependent school / medical: priority 1, protected, not reschedulable
- dependent activity: priority 2, protected, not reschedulable
- caregiver medical: priority 2, not protected, reschedulable (needs provider confirmation)
- work: priority 3, not protected, not reschedulable
- errand: priority 4, not protected, reschedulable
- personal: priority 5, not protected, reschedulable"""


def interpretation_prompt(household: List[Dict], events: List[Dict]) -> str:
    return f"""You are the semantic interpretation agent of a household mobility assistant.
Classify every calendar event. Do NOT compute routes, times, distances or locations, and do NOT
add, remove or modify events. Use only the information given.

{CATEGORY_GUIDE}

{POLICY_GUIDE}

Household members:
{json.dumps(household, indent=1)}

Calendar events:
{json.dumps(events, indent=1)}

Return ONLY a JSON object of the form
{{"events": [{{"event_id": "...", "category": "...", "priority": 1, "protected": true,
              "reschedulable": false, "rationale": "<= 12 words"}}]}}
with exactly one entry per input event_id."""


def llm_only_planning_prompt(household: List[Dict], events: List[Dict], vehicle: Dict, locations: List[Dict]) -> str:
    return f"""You are a household mobility planner for ONE shared electric vehicle.
Plan the whole day: which stops the vehicle makes, when, who gets in and out, any charging, and
any calendar event that should be moved. Dependents must never ride or wait without a caregiver.
Protected events must not be missed or moved. Everyone must end the day at Home.

{POLICY_GUIDE}

Household: {json.dumps(household)}
Vehicle: {json.dumps(vehicle)}
Known locations (use these ids): {json.dumps(locations)}
Calendar events: {json.dumps(events, indent=1)}

Return ONLY JSON:
{{"stops": [{{"location": "<location id>", "arrive": "HH:MM", "depart": "HH:MM",
             "drop": ["<person>"], "pick": ["<person>"], "charge_min": 0}}],
 "reschedule": [{{"event_id": "...", "new_start": "HH:MM"}}]}}
The first stop must be Home at the start of the day."""


INTENTS = ("route_planning", "route_followup", "calendar_event_add", "calendar_event_remove", "casual")


def intent_prompt(message: str, previous_route_available: bool) -> str:
    return f"""Classify the user's message into one intent: {", ".join(INTENTS)}.
Recalculation requests (recalculate, refresh, update, rebuild, rerun, new plan) are route_planning
even if a previous route exists. Questions about an existing plan are route_followup only if a
previous route exists. Return ONLY {{"intent": "..."}}.
Previous route available: {"yes" if previous_route_available else "no"}
Message: {message}"""


def explanation_prompt(route_context: Dict) -> str:
    return f"""Format the verified route below into a concise summary for the active user.
Use only the input; do not recalculate, add, remove or reorder trips; never claim a calendar
change was made unless it is listed as confirmed. Return ONLY {{"user_interface_output": "..."}}.
INPUT: {json.dumps(route_context)}"""
