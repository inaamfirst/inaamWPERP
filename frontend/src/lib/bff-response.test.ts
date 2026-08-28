import { describe, expect, it } from "vitest";

import { passthroughBackendResponse } from "./bff-response";

describe("BFF response passthrough", () => {
  it("preserves CSV bytes and download metadata", async () => {
    const backend = new Response("order,amount\nA-1,1200\n", {
      status: 200,
      headers: {
        "Content-Type": "text/csv; charset=utf-8",
        "Content-Disposition": 'attachment; filename="orders.csv"',
        "X-Request-Id": "request-1",
        "Set-Cookie": "must-not-leak=true",
      },
    });

    const result = passthroughBackendResponse(backend);

    await expect(result.text()).resolves.toBe("order,amount\nA-1,1200\n");
    expect(result.status).toBe(200);
    expect(result.headers.get("content-type")).toBe("text/csv; charset=utf-8");
    expect(result.headers.get("content-disposition")).toBe(
      'attachment; filename="orders.csv"',
    );
    expect(result.headers.get("x-request-id")).toBe("request-1");
    expect(result.headers.get("cache-control")).toBe("no-store");
    expect(result.headers.has("set-cookie")).toBe(false);
  });

  it("preserves arbitrary ZIP bytes", async () => {
    const bytes = new Uint8Array([0x50, 0x4b, 0x03, 0x04, 0xff, 0x00, 0x80]);
    const backend = new Response(bytes, {
      headers: { "Content-Type": "application/zip" },
    });

    const result = passthroughBackendResponse(backend);

    expect(new Uint8Array(await result.arrayBuffer())).toEqual(bytes);
    expect(result.headers.get("content-type")).toBe("application/zip");
  });
});
