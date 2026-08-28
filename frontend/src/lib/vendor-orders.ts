export const VENDOR_ORDER_FILTERS = [
  "all",
  "pending",
  "accepted",
  "packing",
  "dispatched",
  "delivered",
  "rejected",
] as const;

const NEXT_VENDOR_ORDER_STATUS: Readonly<Record<string, string | undefined>> = {
  pending: "accepted",
  accepted: "packing",
  packing: "dispatched",
  dispatched: "delivered",
};

export function nextVendorOrderStatus(status: string): string | undefined {
  return NEXT_VENDOR_ORDER_STATUS[status];
}

export function vendorOrderCollectionEndpoint(filter: string): string {
  return `/marketplace/vendor/orders${filter === "all" ? "" : `?status=${filter}`}`;
}

export function vendorOrderStatusEndpoint(orderItemId: string): string {
  return `/vendor/order-items/${encodeURIComponent(orderItemId)}/status`;
}
