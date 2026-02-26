/** API client — handles auth headers and token refresh. */

const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8080';

interface Tokens {
  access_token: string;
  refresh_token: string;
}

let tokens: Tokens | null = null;

export function setTokens(t: Tokens | null) {
  tokens = t;
  if (t) {
    localStorage.setItem('tokens', JSON.stringify(t));
  } else {
    localStorage.removeItem('tokens');
  }
}

export function getTokens(): Tokens | null {
  if (tokens) return tokens;
  const stored = localStorage.getItem('tokens');
  if (stored) {
    tokens = JSON.parse(stored);
    return tokens;
  }
  return null;
}

export function isLoggedIn(): boolean {
  return !!getTokens();
}

async function refreshTokens(): Promise<boolean> {
  const t = getTokens();
  if (!t) return false;
  try {
    const resp = await fetch(`${API_BASE}/auth/refresh`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: t.refresh_token }),
    });
    if (!resp.ok) return false;
    const data = await resp.json();
    setTokens(data);
    return true;
  } catch {
    return false;
  }
}

export async function api(path: string, options: RequestInit = {}): Promise<Response> {
  const t = getTokens();
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options.headers as Record<string, string> || {}),
  };
  if (t) {
    headers['Authorization'] = `Bearer ${t.access_token}`;
  }

  let resp = await fetch(`${API_BASE}${path}`, { ...options, headers });

  // Auto-refresh on 401
  if (resp.status === 401 && t) {
    const refreshed = await refreshTokens();
    if (refreshed) {
      const newT = getTokens()!;
      headers['Authorization'] = `Bearer ${newT.access_token}`;
      resp = await fetch(`${API_BASE}${path}`, { ...options, headers });
    }
  }

  return resp;
}

export async function apiJson<T = unknown>(path: string, options: RequestInit = {}): Promise<T> {
  const resp = await api(path, options);
  if (!resp.ok) {
    const body = await resp.json().catch(() => ({}));
    throw new Error(body.detail || `API error ${resp.status}`);
  }
  return resp.json();
}
