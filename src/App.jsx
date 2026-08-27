import { useEffect, useMemo, useState } from "react";
import "./App.css";
import { getSettings, USER_SETTINGS_ID } from "./api/settingsClient";
import SettingsPanel from "./components/SettingsPanel";

const WEBHOOK_URL =
  "https://jbyutse.app.n8n.cloud/webhook/66e38986-bf56-4753-b3fc-0cb37235f6fb";

const WELCOME_MESSAGE =
  "Hi! Ask me about your route plan, schedule, priorities, construction impacts, or travel plans for today.";

const DEMO_CHARGING_LOCATION =
  "900 Boulevard René-Lévesque Ouest, Montréal, QC, Canada";

function timeToMinutes(value) {
  if (!value) return null;

  const normalized = value
    .toLowerCase()
    .replace(/\./g, "")
    .trim();

  const match = normalized.match(
    /(\d{1,2}):(\d{2})\s*(am|pm)/
  );

  if (!match) return null;

  let hour = Number(match[1]);
  const minute = Number(match[2]);
  const period = match[3];

  if (period === "pm" && hour !== 12) hour += 12;
  if (period === "am" && hour === 12) hour = 0;

  return hour * 60 + minute;
}

function getDisplayDuration(leg) {
  const departure = timeToMinutes(leg.departure_time);
  const arrival = timeToMinutes(leg.arrival_time);

  if (departure !== null && arrival !== null) {
    let difference = arrival - departure;

    if (difference < 0) {
      difference += 24 * 60;
    }

    return difference;
  }

  return leg.duration_minutes;
}

function getShortWeather(weather) {
  if (!weather) return "";

  const condition = weather.split(",")[0];

  const temperature =
    weather.match(/(-?\d+(?:\.\d+)?)°C/)?.[1];

  const humidity =
    weather.match(/(\d+)% humidity/)?.[1];

  return [
    condition,
    temperature ? `${temperature}°C` : null,
    humidity ? `${humidity}% humidity` : null,
  ]
    .filter(Boolean)
    .join(" · ");
}

function RouteSummary({ routeData }) {
  const trips = routeData.route_legs || [];
  const conflicts = routeData.conflicts || [];
  const vehicle = routeData.vehicle || {};

  const chargingLocation =
    vehicle.charging_location || DEMO_CHARGING_LOCATION;

  return (
    <div className="route-dashboard">

      {/* TOP SUMMARY */}
      <div className="route-overview-card">
        <div>
          <div className="route-date">
            {routeData.route_date_label}
          </div>

          <div className="route-weather">
            {getShortWeather(routeData.weather_summary)}
          </div>
        </div>

        <div className="route-stats">
          <div className="route-stat">
            <strong>{trips.length}</strong>
            <span>Trips</span>
          </div>

          {vehicle.battery_percent !== null && (
            <div className="route-stat">
              <strong>{vehicle.battery_percent}%</strong>
              <span>Battery</span>
            </div>
          )}
        </div>
      </div>

      {/* CONFLICT */}
      {conflicts.map((conflict, index) => (
        <div className="conflict-card" key={index}>
          <div className="card-label">
            Schedule conflict
          </div>

          <div className="conflict-title">
            {conflict.event_title}
          </div>

          <div className="conflict-recommendation">
            Recommended: {conflict.recommended_start} –{" "}
            {conflict.recommended_end}
          </div>

          <div className="conflict-reason">
            {conflict.reason}
          </div>

          <div className="status-row">
            {conflict.feasibility_verified && (
              <span className="status-chip success">
                Route feasible
              </span>
            )}

            {conflict.requires_provider_confirmation && (
              <span className="status-chip warning">
                Provider confirmation required
              </span>
            )}
          </div>
        </div>
      ))}

      {/* ROUTE */}
      <div className="section-heading">
        Today's route
      </div>

      <div className="route-timeline">
        {trips.map((leg) => {
          const duration = getDisplayDuration(leg);

          return (
            <div
              className="timeline-trip"
              key={leg.trip_number}
            >
              <div className="timeline-column">
                <div className="timeline-time">
                  {leg.departure_time}
                </div>

                <div className="timeline-dot" />

                <div className="timeline-line" />
              </div>

              <div className="trip-card">
                <div className="trip-header">
                  <span>Trip {leg.trip_number}</span>

                  {duration !== null && (
                    <span>{duration} min</span>
                  )}
                </div>

                <div className="trip-location">
                  <div className="location-start">
                    {leg.start_address}
                  </div>

                  <div className="route-arrow">↓</div>

                  <div className="location-end">
                    {leg.end_address}
                  </div>
                </div>

                {leg.purpose && (
                  <div className="trip-purpose">
                    {leg.purpose}
                  </div>
                )}

                {leg.responsibility && (
                  <div className="responsibility-note">
                    {leg.responsibility}
                  </div>
                )}

                {leg.shared_ride && (
                  <div className="shared-ride-note">
                    {leg.shared_ride}
                  </div>
                )}

                <div className="arrival-row">
                  Arrive {leg.arrival_time}
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {/* VEHICLE */}
      <div className="vehicle-card">
        <div className="card-label">
          Vehicle plan
        </div>

        <div className="vehicle-grid">
          <div>
            <span className="vehicle-label">
              Battery
            </span>

            <strong>
              {vehicle.battery_percent ?? "—"}%
            </strong>
          </div>

          {vehicle.charging_start &&
            vehicle.charging_end && (
              <div>
                <span className="vehicle-label">
                  Autonomous charging
                </span>

                <strong>
                  {vehicle.charging_start} –{" "}
                  {vehicle.charging_end}
                </strong>
              </div>
            )}
        </div>

        {vehicle.charging_start && (
          <div className="charging-location">
            {chargingLocation}
          </div>
        )}
      </div>

      {/* SUMMARY */}
      {routeData.summary && (
        <div className="day-summary">
          {routeData.summary}
        </div>
      )}
    </div>
  );
}


function App() {
  const sessionId = useMemo(() => {
    const existing = localStorage.getItem("agenticVehicleSessionId");
    if (existing) return existing;

    const newSessionId = crypto.randomUUID();
    localStorage.setItem("agenticVehicleSessionId", newSessionId);
    return newSessionId;
  }, []);

  const [messages, setMessages] = useState([
    {
      role: "assistant",
      text: WELCOME_MESSAGE,
    },
  ]);



  const [settings, setSettings] = useState(null);
  const [settingsLoading, setSettingsLoading] = useState(false);
  const [settingsError, setSettingsError] = useState("");
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [activePersonId, setActivePersonId] = useState(
    localStorage.getItem("activePersonId") || ""
  );


  const handleActivePersonSelect = (selectedPerson) => {
    setActivePersonId(selectedPerson);
    localStorage.setItem("activePersonId", selectedPerson);
  };


  useEffect(() => {
  async function loadSettings() {
    try {
      setSettingsLoading(true);
      setSettingsError("");

      const data = await getSettings(USER_SETTINGS_ID);

      setSettings(data.settings);
      console.log("Loaded user settings:", data.settings);
    } catch (error) {
      console.error(error);
      setSettingsError("Could not load user settings.");
    } finally {
      setSettingsLoading(false);
    }
  }

  loadSettings();
}, []);


  useEffect(() => {
    const timer = setTimeout(() => {
      speakText(WELCOME_MESSAGE);
    }, 500);

    const unlockVoice = () => {
      speakText(WELCOME_MESSAGE);
      window.removeEventListener("click", unlockVoice);
    };

    window.addEventListener("click", unlockVoice);

    return () => {
      clearTimeout(timer);
      window.removeEventListener("click", unlockVoice);
    };
  }, []);

  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [listening, setListening] = useState(false);

  function extractAssistantReply(data) {
  if (typeof data === "string") return data;

  if (Array.isArray(data)) {
    data = data[0];
  }

  return (
    data.user_interface_output ||
    data.reply ||
    data.user_message ||
    data.output ||
    data.text ||
    data.response ||
    data.message ||
    data?.json?.user_interface_output ||
    data?.json?.reply ||
    data?.json?.user_message ||
    data?.output?.[0]?.content?.[0]?.text ||
    "Sorry, I did not receive a valid response."
  );
}

function extractStructuredRoute(data) {
  const candidates = [
    data?.user_interface_output,
    data?.output,
    data?.json?.user_interface_output,
    data?.json?.output,
  ];

  for (const candidate of candidates) {
    if (!candidate) continue;

    if (
      typeof candidate === "object" &&
      Array.isArray(candidate.route_legs)
    ) {
      return candidate;
    }

    if (typeof candidate === "string") {
      try {
        const parsed = JSON.parse(candidate);

        if (
          parsed?.user_interface_output &&
          Array.isArray(parsed.user_interface_output.route_legs)
        ) {
          return parsed.user_interface_output;
        }

        if (Array.isArray(parsed?.route_legs)) {
          return parsed;
        }
      } catch {
        // Not structured route JSON, so continue normally.
      }
    }
  }

  return null;
}

function speakText(text) {
  if (!("speechSynthesis" in window)) {
    console.warn("Text-to-speech is not supported in this browser.");
    return;
  }

  window.speechSynthesis.cancel();

  const utterance = new SpeechSynthesisUtterance(text);
  utterance.lang = "en-CA";
  utterance.rate = 1;
  utterance.pitch = 1;

  window.speechSynthesis.speak(utterance);
}

function stopSpeaking() {
  if ("speechSynthesis" in window) {
    window.speechSynthesis.cancel();
  }
}

  async function sendMessageText(textToSend) {
    const trimmedInput = textToSend.trim();

    if (!trimmedInput || loading) return;

    if (!activePersonId) {
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          text: "Please select whether you are Parent1 or Parent2 before asking for your route.",
        },
      ]);
      return;
    }

    setMessages((prev) => [...prev, { role: "user", text: trimmedInput }]);
    setInput("");
    setLoading(true);

    try {
      const response = await fetch(WEBHOOK_URL, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
        message: trimmedInput,
        chatInput: trimmedInput,
        sessionId,
        user_id: USER_SETTINGS_ID,
        activePersonId,
        inputType: "voice_or_text",
        settings,
      }),
      });

      if (!response.ok) {
        throw new Error(`Agent request failed with status ${response.status}`);
      }

      const rawData = await response.json();
      const data = Array.isArray(rawData) ? rawData[0] : rawData;

      const assistantReply = extractAssistantReply(data);
      const routeData = extractStructuredRoute(data);

      const missingEvents =
      data.missing_location_events ||
      data.json?.missing_location_events ||
      [];

    setMessages((prev) => [
      ...prev,
      {
        role: "assistant",
        text: routeData ? "" : assistantReply,
        routeData,
        missing_location_events: missingEvents,
      },
    ]);

    const baseSpeechText =
      routeData?.summary || assistantReply;

    const speechText =
      missingEvents.length > 0
        ? baseSpeechText +
          " " +
          missingEvents
            .map(
              (event) =>
                `${event.title}, for ${event.person}, at ${event.start_time_display}.`
            )
            .join(" ")
        : baseSpeechText;

    speakText(speechText);
    } catch (error) {
      console.error("Agent connection error:", error);

      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          text: "Error connecting to the agent.",
        },
      ]);
    } finally {
      setLoading(false);
    }
  }

  function sendMessage() {
    sendMessageText(input);
  }

  function startVoiceInput() {
    const SpeechRecognition =
      window.SpeechRecognition || window.webkitSpeechRecognition;

    if (!SpeechRecognition) {
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          text: "Voice recognition is not supported in this browser. Try using Chrome.",
        },
      ]);
      return;
    }

    const recognition = new SpeechRecognition();

    recognition.lang = "en-CA";
    recognition.interimResults = false;
    recognition.continuous = false;

    recognition.onstart = () => {
      setListening(true);
    };

    recognition.onresult = (event) => {
      const transcript = event.results[0][0].transcript;
      setInput(transcript);
      sendMessageText(transcript);
    };

    recognition.onerror = (event) => {
      console.error("Speech recognition error:", event.error);

      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          text: "Sorry, I could not understand the voice input.",
        },
      ]);
    };

    recognition.onend = () => {
      setListening(false);
    };

    recognition.start();
  }

  function replayLastAssistantMessage() {
  const lastAssistantMessage = [...messages]
    .reverse()
    .find((message) => message.role === "assistant");

  if (!lastAssistantMessage) return;

  let textToSpeak = lastAssistantMessage.text;

  if (lastAssistantMessage.missing_location_events?.length > 0) {
    textToSpeak +=
      " " +
      lastAssistantMessage.missing_location_events
        .map(
          (event) =>
            `${event.title}, for ${event.person}, at ${event.start_time_display}.`
        )
        .join(" ");
  }

  speakText(textToSpeak);
}

      return (
        <div className="page">
          <div className="chat-container">
            <h1>Agentic Mobility Assistant</h1>

            <div className="user-selector">
              <span className="user-selector-label">User:</span>

              <button
                type="button"
                className={`user-button ${activePersonId === "Parent1" ? "active" : ""}`}
                onClick={() => handleActivePersonSelect("Parent1")}
              >
                Parent1
              </button>

              <button
                type="button"
                className={`user-button ${activePersonId === "Parent2" ? "active" : ""}`}
                onClick={() => handleActivePersonSelect("Parent2")}
              >
                Parent2
              </button>
            </div>

            <button
              type="button"
              className="settings-button"
              onClick={() => setSettingsOpen((prev) => !prev)}
            >
              ⚙️ Settings
            </button>

            {settingsLoading && <p>Loading settings...</p>}
            {settingsError && <p>{settingsError}</p>}

            {settingsOpen && (
              <SettingsPanel
                settings={settings}
                setSettings={setSettings}
                userId={USER_SETTINGS_ID}
                onClose={() => setSettingsOpen(false)}
              />
            )}



            <div className="chat-box">
              {messages.map((msg, index) => (
                <div key={index} className={`message ${msg.role}`}>
                  {msg.routeData ? (
                    <RouteSummary routeData={msg.routeData} />
                  ) : (
                    <div>{msg.text}</div>
                  )}

    {msg.missing_location_events?.length > 0 && (
      <div className="missing-events">
        {msg.missing_location_events.map((event, i) => (
          <div key={i} className="missing-event">
            <div>
              • {event.title} ({event.person} at {event.start_time_display})
            </div>

            {event.htmlLink && (
              <a
                href={event.htmlLink}
                target="_blank"
                rel="noopener noreferrer"
              >
                Edit event
              </a>
            )}
          </div>
        ))}
      </div>
    )}
            </div>
          ))}

          {loading && <div className="message assistant">Thinking...</div>}
          {listening && <div className="message assistant">Listening...</div>}
        </div>

        <div className="input-row">
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask about your plan..."
            onKeyDown={(e) => {
              if (e.key === "Enter") sendMessage();
            }}
            disabled={loading}
          />

          <button onClick={startVoiceInput} disabled={loading || listening}>
            🎤
          </button>

          <button onClick={sendMessage} disabled={loading}>
            Send
          </button>
          <button onClick={replayLastAssistantMessage} type="button">
            🔊 Replay
          </button>
          <button onClick={stopSpeaking} type="button">
            Stop voice
          </button>
        </div>
      </div>
    </div>
  );
}

export default App;