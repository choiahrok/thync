// Every data request carries X-Thync-Token. Open the page once with #t=<token> and it is remembered.
import { recall, remember, state } from "./state.ts";
import type { ApiGraph } from "./types.ts";

let token = recall("token") || "";
{
  const m = location.hash.match(/(?:^#|&)t=([^&]+)/);
  if (m) {
    token = decodeURIComponent(m[1]);
    remember("token", token);
    history.replaceState(null, "", location.pathname + location.search); // keep the token out of the address bar
  }
}

export const api = (path: string, init: RequestInit = {}): Promise<Response> =>
  fetch(path, { ...init, cache: "no-store", headers: { ...(init.headers ?? {}), "X-Thync-Token": token, "Content-Type": "application/json" } });

export const post = (path: string, body: unknown): Promise<Response> =>
  api(path, { method: "POST", body: JSON.stringify(body) });

/** null when the token is missing or wrong. */
export async function fetchGraph(): Promise<ApiGraph | null> {
  const res = await api(`/graph.json?days=${state.days}`);
  return res.status === 401 ? null : res.json();
}
