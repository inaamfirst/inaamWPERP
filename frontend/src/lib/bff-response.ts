import { NextResponse } from "next/server";

const PASSTHROUGH_RESPONSE_HEADERS = [
  "accept-ranges",
  "content-disposition",
  "content-language",
  "content-range",
  "content-type",
  "etag",
  "last-modified",
  "x-request-id",
] as const;

function safeResponseHeaders(response: Response): Headers {
  const headers = new Headers();
  for (const name of PASSTHROUGH_RESPONSE_HEADERS) {
    const value = response.headers.get(name);
    if (value) headers.set(name, value);
  }
  headers.set("Cache-Control", "no-store");
  return headers;
}

/** Forward non-JSON backend bodies without corrupting CSV, ZIP, or media data. */
export function passthroughBackendResponse(response: Response): NextResponse {
  return new NextResponse(response.status === 204 ? null : response.body, {
    status: response.status,
    headers: safeResponseHeaders(response),
  });
}
