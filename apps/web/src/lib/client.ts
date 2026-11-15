// Thin wrapper around the generated OpenAPI client (src/lib/api/schema.d.ts is generated; do not hand-edit it).
import createClient from "openapi-fetch";
import type { components, paths } from "./api/schema";

export type Schemas = components["schemas"];
export type JobCard = Schemas["JobCard"];
export type JobDetail = Schemas["JobDetail"];
export type ApprovalOut = Schemas["ApprovalOut"];
export type RunOut = Schemas["RunOut"];

export const TOKEN_KEY = "gigbid_token";

export function token(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(TOKEN_KEY);
}

export const api = createClient<paths>({ baseUrl: "" });

api.use({
  onRequest({ request }) {
    const t = token();
    if (t) request.headers.set("Authorization", `Bearer ${t}`);
    return request;
  },
  async onResponse({ response }) {
    if (response.status === 401 && typeof window !== "undefined" && !location.pathname.startsWith("/login")) {
      location.href = "/login";
    }
    if (response.status === 503 && typeof window !== "undefined") {
      window.dispatchEvent(new CustomEvent("gigbid:degraded"));
    }
    return response;
  },
});

export function errorText(e: unknown): string {
  if (!e) return "";
  if (typeof e === "string") return e;
  const d = (e as { detail?: unknown }).detail;
  if (typeof d === "string") return d;
  if (Array.isArray(d)) return d.map((x) => (x as { msg?: string }).msg).join("; ");
  return JSON.stringify(e);
}

export const money = (n?: number | null) => (n == null ? "–" : `$${Math.round(n).toLocaleString()}`);
export const pct = (n?: number | null) => (n == null ? "–" : `${Math.round(n * 100)}%`);
