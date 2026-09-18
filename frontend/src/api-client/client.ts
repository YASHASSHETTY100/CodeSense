const ENV_API = (import.meta as any).env?.VITE_API_URL || (import.meta as any).env?.VITE_API;
const BASE = (ENV_API !== undefined && ENV_API !== null && ENV_API !== '')
  ? ENV_API
  : (typeof window !== 'undefined' && window.location.hostname === 'localhost'
      ? 'http://localhost:8000'
      : '');

export function getToken(): string {
  return localStorage.getItem('token') || '';
}

export function setSession(token: string, user: { email: string; role?: string; name?: string }) {
  localStorage.setItem('token', token);
  localStorage.setItem('user', JSON.stringify(user));
}

export function getUser(): { email: string; role: string; name: string } | null {
  try {
    const raw = localStorage.getItem('user');
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

export function logout() {
  localStorage.removeItem('token');
  localStorage.removeItem('user');
  window.location.href = '/login';
}

function authHeaders(): Record<string, string> {
  const token = getToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export async function api(path: string, opts: any = {}) {
  const customHeaders = (opts && opts.headers) ? opts.headers : {};
  const mergedHeaders: Record<string, string> = {
    'Content-Type': 'application/json',
    ...authHeaders(),
    ...customHeaders,
  };

  const r = await fetch(`${BASE}${path}`, {
    ...opts,
    headers: mergedHeaders,
  });

  if (!r.ok) {
    let msg = `${r.status}`;
    try {
      const errJson = await r.json();
      msg = errJson.detail || JSON.stringify(errJson);
    } catch {
      msg = await r.text();
    }
    throw new Error(msg);
  }

  const contentType = r.headers.get('content-type') || '';
  return contentType.includes('json') ? r.json() : r.text();
}

export async function downloadFile(path: string, defaultFilename: string = 'document.bin'): Promise<void> {
  const token = getToken();
  const headers: Record<string, string> = token ? { Authorization: `Bearer ${token}` } : {};
  const url = path.startsWith('http') ? path : `${BASE}${path}`;
  const res = await fetch(url, { headers });
  if (!res.ok) {
    let msg = `Download failed with status ${res.status}`;
    try {
      const errJson = await res.json();
      msg = errJson.detail || JSON.stringify(errJson);
    } catch {
      // ignore
    }
    throw new Error(msg);
  }
  const blob = await res.blob();
  let filename = defaultFilename;
  const disposition = res.headers.get('content-disposition');
  if (disposition && disposition.includes('filename=')) {
    const match = disposition.match(/filename="?([^";]+)"?/);
    if (match && match[1]) {
      filename = match[1].trim();
    }
  }
  const blobUrl = window.URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.style.display = 'none';
  a.href = blobUrl;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  setTimeout(() => window.URL.revokeObjectURL(blobUrl), 1000);
}

export { BASE };
