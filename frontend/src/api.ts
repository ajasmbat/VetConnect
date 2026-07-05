import { API_BASE_URL } from "./config";
import type { AssistantResponse } from "./types";

async function readError(r: Response): Promise<string> {
  try {
    const body = await r.json();
    return body.detail || body.message || `Request failed (${r.status})`;
  } catch {
    return `Request failed (${r.status})`;
  }
}

export async function askAssistant(
  question: string,
  coords?: { lat: number; long: number }
): Promise<AssistantResponse> {
  const r = await fetch(`${API_BASE_URL}/api/assistant`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question, ...coords }),
  });
  if (!r.ok) throw new Error(await readError(r));
  return r.json();
}
