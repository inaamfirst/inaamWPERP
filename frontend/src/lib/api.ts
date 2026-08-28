const BFF_BASE = '/api/backend';

type ApiErrorPayload = {
  detail?: unknown;
  [key: string]: unknown;
};

export class ApiError extends Error {
  status: number;
  data: ApiErrorPayload;

  constructor(status: number, data: unknown) {
    const payload = data && typeof data === 'object' ? data as ApiErrorPayload : {};
    super(typeof payload.detail === 'string' ? payload.detail : 'An API error occurred');
    this.name = 'ApiError';
    this.status = status;
    this.data = payload;
  }
}

function csrfToken(): string | null {
  if (typeof document === 'undefined') return null;
  const entry = document.cookie.split('; ').find((value) => value.startsWith('erp_bff_csrf='));
  return entry ? decodeURIComponent(entry.split('=').slice(1).join('=')) : null;
}

export async function refreshAccessToken(): Promise<boolean> {
  if (refreshInFlight) return refreshInFlight;

  refreshInFlight = (async () => {
    try {
      const headers = new Headers({ 'Content-Type': 'application/json' });
      const csrf = csrfToken();
      if (csrf) headers.set('X-CSRF-Token', csrf);
      const response = await fetch(`${BFF_BASE}/auth/refresh`, {
        method: 'POST',
        headers,
        credentials: 'same-origin',
        body: JSON.stringify({}),
      });
      return response.ok;
    } catch {
      return false;
    } finally {
      refreshInFlight = null;
    }
  })();

  return refreshInFlight;
}

// Refresh-token rotation invalidates the previous refresh token. Sharing the
// in-flight request prevents concurrent API calls from racing each other.
let refreshInFlight: Promise<boolean> | null = null;

/** Standard same-origin fetch wrapper with HttpOnly-cookie authentication. */
export async function fetchApi(endpoint: string, options: RequestInit = {}) {
  const normalizedEndpoint = endpoint.startsWith('/') ? endpoint : `/${endpoint}`;
  const url = `${BFF_BASE}${normalizedEndpoint}`;
  const request = () => {
    const headers = new Headers(options.headers);
    if (!headers.has('Content-Type') && !(options.body instanceof FormData)) {
      headers.set('Content-Type', 'application/json');
    }
    const method = (options.method || 'GET').toUpperCase();
    const csrf = csrfToken();
    if (csrf && !['GET', 'HEAD', 'OPTIONS'].includes(method)) headers.set('X-CSRF-Token', csrf);
    return fetch(url, { ...options, headers, credentials: 'same-origin' });
  };

  let response = await request();
  const refreshExcluded = new Set([
    '/auth/login', '/auth/refresh', '/auth/password-reset/request',
    '/auth/password-reset/confirm', '/auth/activate',
  ]);
  if (response.status === 401 && !refreshExcluded.has(normalizedEndpoint)) {
    if (await refreshAccessToken()) response = await request();
  }

  if (response.status === 204) return null;
  const data = await response.json().catch(() => null);
  if (!response.ok) throw new ApiError(response.status, data);
  return data;
}
