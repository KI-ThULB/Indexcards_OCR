import axios from 'axios';

// Optional API bearer token (pentest remediation W-01). When VITE_API_TOKEN is set
// at build time, every axios request carries `Authorization: Bearer <token>` and the
// WebSocket URL gets a `?token=` query param. Unset ⇒ no header (local dev, or when
// auth is enforced solely by the reverse proxy). The same built frontend works with
// or without a token, so different institutions can deploy it unchanged.
export const API_TOKEN: string | undefined = import.meta.env.VITE_API_TOKEN;

if (API_TOKEN) {
  axios.defaults.headers.common['Authorization'] = `Bearer ${API_TOKEN}`;
}

/** Append the auth token as a query param to a WebSocket URL when configured. */
export function withWsToken(wsUrl: string): string {
  if (!API_TOKEN) return wsUrl;
  const sep = wsUrl.includes('?') ? '&' : '?';
  return `${wsUrl}${sep}token=${encodeURIComponent(API_TOKEN)}`;
}
