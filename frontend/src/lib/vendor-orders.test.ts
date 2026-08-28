import { describe, expect, it } from "vitest";

import {
  VENDOR_ORDER_FILTERS,
  nextVendorOrderStatus,
  vendorOrderCollectionEndpoint,
  vendorOrderStatusEndpoint,
} from "./vendor-orders";

describe("vendor order workflow", () => {
  it("matches the backend transition graph", () => {
    expect(nextVendorOrderStatus("pending")).toBe("accepted");
    expect(nextVendorOrderStatus("accepted")).toBe("packing");
    expect(nextVendorOrderStatus("packing")).toBe("dispatched");
    expect(nextVendorOrderStatus("dispatched")).toBe("delivered");
    expect(nextVendorOrderStatus("delivered")).toBeUndefined();
    expect(nextVendorOrderStatus("rejected")).toBeUndefined();
    expect(VENDOR_ORDER_FILTERS).not.toContain("confirmed");
    expect(VENDOR_ORDER_FILTERS).not.toContain("ready");
  });

  it("uses the self-service mutation route exposed by FastAPI", () => {
    expect(vendorOrderStatusEndpoint("item/one")).toBe(
      "/vendor/order-items/item%2Fone/status",
    );
    expect(vendorOrderCollectionEndpoint("accepted")).toBe(
      "/marketplace/vendor/orders?status=accepted",
    );
  });
});
