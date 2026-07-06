/**
 * Backend base URL.
 *
 * Reads from the Vite build-time env var `VITE_API_BASE_URL` (set in
 * `frontend/.env` or your host's build settings). Falls back to the dev
 * server so `npm run dev` works out of the box.
 */
export const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";
