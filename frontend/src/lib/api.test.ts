import { beforeEach, describe, expect, it, vi } from "vitest";

import { refreshAccessToken } from "./api";

describe("refreshAccessToken", () => {
  beforeEach(() => {
    document.cookie = "erp_bff_csrf=; Max-Age=0; Path=/";
    vi.restoreAllMocks();
  });

  it("sends the browser-readable CSRF token to the BFF refresh mutation", async () => {
    document.cookie = "erp_bff_csrf=csrf%20value; Path=/";
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(new Response(null, { status: 200 }));

    await expect(refreshAccessToken()).resolves.toBe(true);

    expect(fetchMock).toHaveBeenCalledOnce();
    const [url, options] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/backend/auth/refresh");
    expect(options?.method).toBe("POST");
    expect(new Headers(options?.headers).get("x-csrf-token")).toBe("csrf value");
  });
});
