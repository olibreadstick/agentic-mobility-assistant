const SETTINGS_WEBHOOK_URL =
  "https://jbyutse.app.n8n.cloud/webhook/user-settings";

export const USER_SETTINGS_ID = "prototype_user_1";

export async function getSettings(userId = USER_SETTINGS_ID) {
  const response = await fetch(SETTINGS_WEBHOOK_URL, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      action: "get_settings",
      user_id: userId,
    }),
  });

  const text = await response.text();

  console.log("User Settings API status:", response.status);
  console.log("User Settings API raw response:", text);

  if (!response.ok) {
    throw new Error(`Failed to load user settings: ${response.status} ${text}`);
  }

  try {
    return JSON.parse(text);
  } catch (error) {
    throw new Error(`User Settings API did not return valid JSON: ${text}`);
  }
}

export async function saveSettings(settings, userId = USER_SETTINGS_ID) {
  const response = await fetch(SETTINGS_WEBHOOK_URL, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      action: "save_settings",
      user_id: userId,
      settings,
    }),
  });

  const text = await response.text();

  console.log("Save user settings status:", response.status);
  console.log("Save user settings raw response:", text);

  if (!response.ok) {
    throw new Error(`Failed to save user settings: ${response.status} ${text}`);
  }

  return JSON.parse(text);
}