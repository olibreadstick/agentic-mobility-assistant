# Connecting the n8n prototype to the ISV planner and verifier

The deployed prototype (`workflow/agentic-mobility-assistant-workflow-public.json`) already
separates LLM agents from deterministic nodes. ISV moves the remaining combinatorial work out of
the *Family Route Planning Agent* and puts one verifier in front of every response.

## 1. Run the service

```bash
python service/server.py --host 0.0.0.0 --port 8787      # no third-party dependencies
curl -s localhost:8787/health
```

Endpoints: `POST /plan`, `POST /verify`, `POST /floor` (see `service/server.py`).
`examples/montreal_run2_request.json` is a complete request for the field case.

## 2. Build the instance in n8n

After `CollectGeocodedScheduledEvents` and `AttachVehicleStatus`, add a **Code** node that maps
the workflow state to the instance schema of `hmplan/io.py`:

| Instance field | Source node |
|---|---|
| `locations` | geocoded events, home, `GetChargingLocations` |
| `persons` | `FamilyConfig.family_members` (`role`, `can_drive`) |
| `activities[*].start/end/loc` | Google Calendar records (never from an LLM) |
| `activities[*].semantics` | `FamilyRoutePlanningAgent` output: priority / protected / reschedulable only |
| `activities[*].slots` | provider availability, if known (empty = cannot be moved) |
| `activities[*].escorts` | school pickup authorisations (settings) |
| `vehicle` | `GetVehicleStatus` + user settings (battery, thresholds, autonomy) |
| `leg_overrides` | optional TomTom legs `[origin, destination, km, minutes]` |

Change the planning agent prompt so that it **only classifies events** (use
`hmplan/llm/prompts.py::interpretation_prompt`). It should no longer order trips, assign
caregivers or propose times.

## 3. Plan, verify, respond

1. **HTTP Request** `POST /plan` with `{ "instance": ..., "time_limit": 20 }`.
2. **HTTP Request** `POST /verify` with the instance and the returned mission (this is also the
   node to use for any mission that was edited or produced elsewhere).
3. **IF** `verified == false`: pass `report.violations` to the Final Route Agent and require it
   to disclose them. Never send an unverified plan as if it were feasible.
4. Store the mission in route memory together with a digest of the inputs
   (`hmplan/memory.py::context_digest`); answer follow-ups from memory only if the digest of
   the current inputs is unchanged.

The rule nodes `FindAutonomousVehicleTasks`, `DecideWhetherToReroute1` and
`ValidateRescheduleFeasibility` become redundant once `/plan` and `/verify` are in place; keep
TomTom routing, construction and charger nodes as the grounding services.
