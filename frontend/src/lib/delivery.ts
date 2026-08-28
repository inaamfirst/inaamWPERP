export type DeliveryStatus = "assigned" | "picked_up" | "out_for_delivery" | "delivered" | "failed" | "cancelled";

export type Delivery = {
  id: string;
  order_id: string;
  order_number: string;
  order_status: string;
  order_total_minor: number;
  payment_status: string;
  rider_user_id: string;
  rider_username: string | null;
  rider_name: string | null;
  status: DeliveryStatus;
  recipient_name: string;
  recipient_phone: string | null;
  address_line1: string;
  address_line2: string | null;
  city: string | null;
  state: string | null;
  postal_code: string | null;
  country: string;
  picked_up_at: string | null;
  out_for_delivery_at: string | null;
  delivered_at: string | null;
  failed_at: string | null;
  failure_reason: string | null;
  created_at: string;
  updated_at: string;
};

export const nextDeliveryStatus: Partial<Record<DeliveryStatus, DeliveryStatus>> = {
  assigned: "picked_up",
  picked_up: "out_for_delivery",
  out_for_delivery: "delivered",
};

export function deliveryAddress(delivery: Delivery): string {
  return [delivery.address_line1, delivery.address_line2, delivery.city, delivery.state, delivery.postal_code]
    .filter(Boolean)
    .join(", ");
}
