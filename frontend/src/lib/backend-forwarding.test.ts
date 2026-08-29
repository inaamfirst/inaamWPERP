import { describe, expect, it } from "vitest";
import { applyBackendOriginHeaders } from "./backend-forwarding";

describe("applyBackendOriginHeaders", () => {
  it("forwards the configured HTTPS host and scheme to a loopback API", () => {
    const headers = new Headers();

    applyBackendOriginHeaders(headers, "https://159-65-129-218.nip.io");

    expect(headers.get("host")).toBe("159-65-129-218.nip.io");
    expect(headers.get("x-forwarded-proto")).toBe("https");
  });

  it("does not alter headers for an absent or invalid URL", () => {
    const headers = new Headers({ "content-type": "application/json" });

    applyBackendOriginHeaders(headers, "not a URL");

    expect(headers.get("host")).toBeNull();
    expect(headers.get("content-type")).toBe("application/json");
  });
});
