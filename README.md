# Agentic Mobility Assistant

A context-aware agentic AI system for coordinating daily household mobility using a shared autonomous electric vehicle.

[Open the Agentic Mobility Assistant](https://agentic-vehicle-assistant.vercel.app/)

The Agentic Mobility Assistant combines calendar information, household responsibilities, vehicle status, traffic conditions, construction information, and routing services to generate feasible daily travel plans. The system is designed to support households with multiple caregivers and dependents while accounting for scheduling conflicts and transportation priorities.

## Overview

Daily travel planning can become complex when several household members share one vehicle. Work meetings, school pickups, medical appointments, traffic, construction, and vehicle charging requirements may all need to be considered simultaneously.

The Agentic Mobility Assistant uses an agentic workflow to interpret user requests, analyze calendar events, identify conflicts, assign transportation responsibilities, and generate a personalized route plan.

The project consists of:

* A React-based user interface
* An n8n agentic workflow
* Calendar integration
* AI-based intent classification and planning
* Traffic-aware route generation
* Construction-aware routing
* Shared-vehicle coordination
* Electric vehicle charging decisions
* Multi-user household support

## Key Features

### Calendar-Aware Planning

The system retrieves household calendar events and determines which events require transportation.

Events are classified according to their transportation role and priority, including:

* Dependent pickups
* Dependent activities
* Medical appointments
* Work and research meetings
* Administrative events
* Flexible personal activities

### Household Coordination

The system supports multiple caregivers and dependents sharing a single vehicle.

It can:

* Assign caregivers to dependent pickups
* Identify scheduling conflicts
* Preserve high-priority transportation responsibilities
* Track passengers in the vehicle
* Prevent infeasible overlapping vehicle use
* Recommend alternative times when conflicts occur

### Traffic-Aware Routing

TomTom routing services are used to calculate:

* Travel distance
* Estimated travel time
* Traffic delay
* Suggested departure time
* Estimated arrival time
* Route geometry and street information

### Construction Awareness

Generated routes can be compared with current construction information to determine whether road work affects the planned route.

When relevant construction is detected, the workflow can evaluate whether an alternative route should be used.

### Shared Electric Vehicle Support

The assistant considers the status of the household's shared electric vehicle when creating the daily mobility plan.

The workflow can evaluate:

* Current battery level
* Preferred minimum battery level
* Critical battery threshold
* Available idle periods
* Possible autonomous charging opportunities

Charging can be inserted into the vehicle schedule when appropriate without interfering with higher-priority household trips.

### Route Follow-Up

The system maintains route context so users can ask follow-up questions such as:

* "What time should I leave?"
* "What is my plan for today?"
* "When will the vehicle charge?"
* "Is there traffic on my route?"
* "Is there construction?"
* "What is the current battery level?"

The assistant can answer questions about an existing route without unnecessarily rebuilding the entire plan.

### Calendar Modification

Users can also request calendar changes conversationally.

Examples include:

* "Add a dentist appointment tomorrow at 4 PM."
* "Remove my afternoon meeting."
* "Cancel the school pickup event."

After a calendar change, the system can recalculate the mobility plan.

## System Architecture

The application follows a hybrid agentic architecture in which AI reasoning is combined with deterministic workflow components and external data services.

```text
User
  |
  v
React Interface
  |
  v
n8n Webhook
  |
  v
User Settings + Session Context
  |
  v
Intent Classification
  |
  +---------------------------+
  |             |             |
  v             v             v
Route       Route          Calendar
Planning    Follow-Up      Modification
  |
  v
Calendar Event Collection
  |
  v
Family Route Planning Agent
  |
  v
Conflict Detection &
Caregiver Assignment
  |
  v
Location Resolution
  |
  v
Vehicle / Charging Planning
  |
  v
TomTom Routing
  |
  v
Traffic & Construction Analysis
  |
  v
Personalized Route Summary
  |
  v
React Interface
```

The workflow separates language-model reasoning from tasks better handled deterministically, such as API requests, time calculations, route processing, filtering, and structured data transformation.

## Technologies

### Frontend

* React
* Vite
* JavaScript
* HTML/CSS

### Workflow and AI

* n8n
* OpenAI language models
* Agentic AI
* Prompt engineering
* JSON-based agent communication

### External Services

* Google Calendar
* TomTom Routing and Geocoding
* OpenWeatherMap

### Development

* Git
* GitHub
* REST APIs
* JSON

## Repository Structure

```text
agentic-mobility-assistant/
│
├── src/
│   ├── api/
│   ├── assets/
│   ├── components/
│   └── App.jsx
│
├── public/
│
├── agentic-mobility-assistant-workflow-public.json
│
├── package.json
├── vite.config.js
└── README.md
```

## n8n Workflow

A sanitized version of the Agentic Mobility Assistant n8n workflow is included in:

```text
agentic-mobility-assistant-workflow-public.json
```

The public workflow preserves the architecture and processing logic while removing private credentials and environment-specific information.

The workflow contains placeholders for services such as:

* TomTom API credentials
* Google Calendar credentials
* OpenAI credentials
* n8n data table identifiers

These must be configured within the user's own n8n environment before running the workflow.

## Running the Frontend

Install the project dependencies:

```bash
npm install
```

Start the development server:

```bash
npm run dev
```

The React application communicates with the n8n workflow through a webhook endpoint. A valid n8n deployment and the required API integrations must be configured for the complete system to function.

## Privacy and Security

The public repository does not intentionally include API keys or authentication credentials.

The included n8n workflow has been sanitized for public use. Users importing the workflow must connect their own credentials and configure their own calendars, API services, and n8n resources.

Real household calendar information should not be committed to a public repository.

## Project Context

This project was developed as part of a software engineering internship and research project investigating how agentic AI can support context-aware daily mobility planning.

The work explores how language-model-based agents can be combined with deterministic software components and real-world transportation data to coordinate complex household travel requirements.

The project also supported research on the development and evaluation of a hybrid agentic mobility assistant for context-aware daily travel planning.

## Future Development

Potential extensions include:

* Improved real-time traffic adaptation
* Additional transportation modes
* More advanced EV energy modeling
* Automated charging-station selection
* Expanded multi-vehicle household support
* Additional personalization
* Improved route-plan visualization
* Larger-scale evaluation across different household scenarios

## Author

**Olivia Cardillo**

Software Engineering
