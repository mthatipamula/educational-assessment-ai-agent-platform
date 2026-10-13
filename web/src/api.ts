export interface User { key: string; id: string; name: string; role: 'TEACHER' | 'STUDENT'; detail: string }

export const PERSONAS: User[] = [
  { key: 'teacher-key', id: 'T-RIVERA', name: 'Ms. Rivera', role: 'TEACHER', detail: 'Author items with AI, review scores, run evaluations' },
  { key: 'maya-key', id: 'STU-MAYA', name: 'Maya', role: 'STUDENT', detail: 'Grade 6 student: practice items and the AI tutor' },
  { key: 'leo-key', id: 'STU-LEO', name: 'Leo', role: 'STUDENT', detail: 'Grade 7 student: practice items and the AI tutor' },
];

const KEY = 'edu.user';
export function loadUser(): User | null {
  try { return JSON.parse(sessionStorage.getItem(KEY) ?? 'null'); } catch { return null; }
}
export function saveUser(u: User | null): void {
  try { if (u) sessionStorage.setItem(KEY, JSON.stringify(u)); else sessionStorage.removeItem(KEY); } catch { /* storage unavailable */ }
}

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

export async function api<T = any>(path: string, init: { method?: string; body?: unknown } = {}): Promise<T> { // eslint-disable-line
  const headers: Record<string, string> = {};
  const user = loadUser();
  if (user) headers['X-API-Key'] = user.key;
  if (init.body !== undefined) headers['Content-Type'] = 'application/json';
  const res = await fetch(path, { method: init.method ?? 'GET', headers, body: init.body !== undefined ? JSON.stringify(init.body) : undefined });
  const text = await res.text();
  const body = text ? (() => { try { return JSON.parse(text); } catch { return text; } })() : null;
  if (!res.ok) {
    const detail = typeof body?.detail === 'string' ? body.detail : Array.isArray(body?.detail) ? body.detail.map((d: { msg: string }) => d.msg).join('; ') : res.statusText;
    throw new ApiError(res.status, detail);
  }
  return body as T;
}

export const when = (iso?: string | null) =>
  iso ? new Date(iso).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }) : '-';
export const num = (v: unknown, digits = 1) => (v == null ? '-' : Number(v).toFixed(digits).replace(/\.0$/, ''));
