# Deployed n8n workflow (sanitised)

`agentic-mobility-assistant-workflow-public.json` is the production workflow of the prototype
evaluated in the paper (Section 6.1), with credentials and deployment-specific identifiers
removed. Import it into n8n and configure your own OpenAI/Gemini, Google Calendar, TomTom and
OpenWeatherMap credentials and the n8n data tables `UserSettings`, `VehicleStatus`,
`ChargingLocations` and route memory.

Main stages (see Table 1 of the paper for the mapping to ISV):

| Stage | Key nodes |
|---|---|
| Request routing | `Webhook`, `Schedule Trigger`, `IntentClassifier Agent`, `Switch` |
| Records | `GetToday` (Google Calendar), `NormalizeCalendarEvents`, `FamilyConfig`, `GetUserSettings`, `GetVehicleStatus` |
| Household mission (LLM) | `FamilyRoutePlanningAgent` |
| Grounding | `GeoCodeAddressTomTom`, `GetRoute_TomTom`, `Call 'GetConstructionImpacts'`, `GetChargingLocations`, `OpenWeatherMap1` |
| Rules | `FindAutonomousVehicleTasks` (charging gap), `DecideWhetherToReroute1`, `CompareOriginalAndDetour`, `ValidateRescheduleFeasibility` |
| Output | `BuildVehicleOperationsOutput`, `FilterUserVisibleRouteContext`, `FinalRouteAgent`, `SaveLastRouteMemory` |
| Calendar edits | `CalendarEventExtractor Agent`, `RemoveEventExtractor Agent`, Google Calendar create/delete |

To upgrade the workflow to the ISV architecture, follow `docs/n8n_integration.md`.
