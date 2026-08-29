/**
 * Preserve the public HTTPS origin when the Next.js BFF calls a loopback API.
 * The API validates its Host header and relies on the forwarded scheme before
 * applying HTTPS redirects.
 */
export function applyBackendOriginHeaders(headers: Headers, apiBaseUrl?: string): void {
  if (!apiBaseUrl) return;

  try {
    const publicUrl = new URL(apiBaseUrl);
    headers.set("host", publicUrl.host);
    headers.set("x-forwarded-proto", publicUrl.protocol.replace(/:$/, ""));
  } catch {
    // Development deployments without a public API URL keep the normal
    // loopback request behavior.
  }
}
