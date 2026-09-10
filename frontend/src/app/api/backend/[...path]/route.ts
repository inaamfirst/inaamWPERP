import { cookies } from "next/headers";
import { NextRequest, NextResponse } from "next/server";
import { applyBackendOriginHeaders } from "@/lib/backend-forwarding";
import { passthroughBackendResponse } from "@/lib/bff-response";

const ACCESS_COOKIE = "erp_access";
const REFRESH_COOKIE = "erp_refresh";
const CSRF_COOKIE = "erp_bff_csrf";
const SAFE_METHODS = new Set(["GET", "HEAD", "OPTIONS"]);
const PUBLIC_MUTATIONS = new Set([
  "auth/login",
  "auth/register/user",
  "auth/register/vendor",
  "auth/password-reset/request",
  "auth/password-reset/confirm",
  "auth/activate",
]);

type RouteContext = { params: Promise<{ path: string[] }> };

function backendBaseUrl(): string {
  return (process.env.ERP_API_INTERNAL_URL || "http://127.0.0.1:8000").replace(/\/$/, "");
}

function cookieOptions(httpOnly: boolean) {
  return {
    httpOnly,
    secure: process.env.NODE_ENV === "production",
    sameSite: "strict" as const,
    path: "/",
  };
}

function clearAuthCookies(response: NextResponse) {
  response.cookies.set(ACCESS_COOKIE, "", { ...cookieOptions(true), maxAge: 0 });
  response.cookies.set(REFRESH_COOKIE, "", { ...cookieOptions(true), maxAge: 0 });
  response.cookies.set(CSRF_COOKIE, "", { ...cookieOptions(false), maxAge: 0 });
}

function jsonResponse(response: Response, payload: unknown): NextResponse {
  const result = NextResponse.json(payload, { status: response.status });
  const requestId = response.headers.get("x-request-id");
  if (requestId) result.headers.set("x-request-id", requestId);
  result.headers.set("Cache-Control", "no-store");
  return result;
}

function redactAuthTokens(payload: unknown): unknown {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) return payload;
  const safePayload = { ...(payload as Record<string, unknown>) };
  delete safePayload.access_token;
  delete safePayload.refresh_token;
  return safePayload;
}

async function handle(request: NextRequest, context: RouteContext): Promise<NextResponse> {
  const { path } = await context.params;
  const endpoint = path.join("/");
  const cookieStore = await cookies();
  const accessToken = cookieStore.get(ACCESS_COOKIE)?.value;
  const refreshToken = cookieStore.get(REFRESH_COOKIE)?.value;

  if (!SAFE_METHODS.has(request.method) && !PUBLIC_MUTATIONS.has(endpoint)) {
    const expected = cookieStore.get(CSRF_COOKIE)?.value;
    const supplied = request.headers.get("x-csrf-token");
    if (!expected || expected !== supplied) {
      return NextResponse.json({ detail: "CSRF validation failed." }, { status: 403 });
    }
  }

  const headers = new Headers();
  for (const name of ["content-type", "accept", "x-request-id"]) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  applyBackendOriginHeaders(headers, process.env.ERP_API_BASE_URL);
  if (accessToken && endpoint !== "auth/login" && endpoint !== "auth/refresh") {
    headers.set("authorization", `Bearer ${accessToken}`);
  }

  let body: ArrayBuffer | undefined;
  if (!SAFE_METHODS.has(request.method)) body = await request.arrayBuffer();
  if (endpoint === "auth/refresh") {
    if (!refreshToken) return NextResponse.json({ detail: "Refresh token required." }, { status: 401 });
    headers.set("content-type", "application/json");
    body = new TextEncoder().encode(JSON.stringify({ refresh_token: refreshToken })).buffer;
  }

  let backendResponse: Response;
  try {
    backendResponse = await fetch(
      `${backendBaseUrl()}/api/v1/${endpoint}${request.nextUrl.search}`,
      {
        method: request.method,
        headers,
        body,
        cache: "no-store",
      },
    );
  } catch {
    return NextResponse.json({ detail: "Backend service unavailable." }, { status: 502 });
  }
  const authResponse = endpoint === "auth/login" || endpoint === "auth/refresh";
  let payload: Record<string, unknown> | null = null;
  let result: NextResponse;
  if (authResponse) {
    const parsed = await backendResponse.json().catch(() => null);
    payload = parsed && typeof parsed === "object" && !Array.isArray(parsed)
      ? parsed as Record<string, unknown>
      : null;
    result = jsonResponse(backendResponse, redactAuthTokens(payload));
  } else if (backendResponse.headers.get("content-type")?.includes("json")) {
    const parsed = await backendResponse.json().catch(() => null);
    result = jsonResponse(backendResponse, parsed);
  } else {
    result = passthroughBackendResponse(backendResponse);
  }

  if (authResponse && backendResponse.ok && typeof payload?.access_token === "string") {
    result.cookies.set(ACCESS_COOKIE, payload.access_token, { ...cookieOptions(true), maxAge: 30 * 60 });
    if (typeof payload.refresh_token === "string") {
      result.cookies.set(REFRESH_COOKIE, payload.refresh_token, { ...cookieOptions(true), maxAge: 24 * 60 * 60 });
    }
    result.cookies.set(CSRF_COOKIE, crypto.randomUUID(), { ...cookieOptions(false), maxAge: 24 * 60 * 60 });
  }
  if (endpoint === "auth/logout" && (backendResponse.ok || backendResponse.status === 401)) {
    clearAuthCookies(result);
  }
  return result;
}

export async function GET(request: NextRequest, context: RouteContext) { return handle(request, context); }
export async function POST(request: NextRequest, context: RouteContext) { return handle(request, context); }
export async function PUT(request: NextRequest, context: RouteContext) { return handle(request, context); }
export async function PATCH(request: NextRequest, context: RouteContext) { return handle(request, context); }
export async function DELETE(request: NextRequest, context: RouteContext) { return handle(request, context); }
