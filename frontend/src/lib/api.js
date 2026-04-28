// Thin wrapper around the Flask /api/* endpoints. All payloads are JSON.

// Hard ceiling on a single request. Backend has its own ~60s OpenAI timeout
// plus gunicorn's 120s worker timeout — 90s gives both a chance to surface
// a real error before we abort and show a generic timeout message.
const REQUEST_TIMEOUT_MS = 90_000;

async function postJson(url, body) {
  let res;
  try {
    res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
    });
  } catch (err) {
    if (err && (err.name === "TimeoutError" || err.name === "AbortError")) {
      throw new Error("Request timed out. The server may be busy — try again.");
    }
    throw err;
  }
  let data = null;
  try {
    data = await res.json();
  } catch {
    // Non-JSON response (rare); fall through to error handling
  }
  if (!res.ok) {
    const msg = (data && data.error) || `Request failed: ${res.status}`;
    throw new Error(msg);
  }
  // Flask returns 200 + { error: "..." } for LLM/validation failures.
  // Treat those as errors at the client layer so the catch path surfaces them.
  if (data && data.error) {
    throw new Error(data.error);
  }
  return data;
}

export function chat({ message, imageBase64, confirm, editedSummary } = {}) {
  const body = {};
  if (message !== undefined) body.message = message;
  if (imageBase64) body.image_base64 = imageBase64;
  if (confirm) body.confirm = true;
  if (editedSummary !== undefined) body.edited_summary = editedSummary;
  return postJson("/api/chat", body);
}

export function syncTrace(trace) {
  return postJson("/api/sync", { trace });
}

export function resetSession() {
  return postJson("/api/reset");
}

// Build a download blob URL for the current trace JSON. Caller is responsible
// for revokeObjectURL after the click.
export function traceDownloadUrl(trace) {
  const blob = new Blob([JSON.stringify(trace, null, 2)], {
    type: "application/json",
  });
  return URL.createObjectURL(blob);
}
