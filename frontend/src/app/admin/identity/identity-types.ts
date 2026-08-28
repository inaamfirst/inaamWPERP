export type AccountStatus = "active" | "pending" | "paused" | "stopped";
export type UserFormType = "Vendor" | "Generic";

export type Role = {
  id: string;
  name: string;
  is_custom: boolean;
  permissions: string[];
};

export type Permission = { id: string; name: string; description: string };

export type VendorProfile = {
  id: string;
  company_id: string;
  name: string;
  slug: string;
  legal_name: string | null;
  contact_name: string | null;
  email: string | null;
  phone: string | null;
  status: string;
  default_commission_bps: number;
  metadata: Record<string, unknown>;
};

export type User = {
  id: string;
  username: string;
  email: string | null;
  full_name: string | null;
  account_status: AccountStatus;
  must_change_password: boolean;
  role_ids: string[];
  role_names: string[];
  company_id: string | null;
};

export type UserDetail = User & { vendor_profile: VendorProfile | null };

export type UserForm = {
  username: string;
  password: string;
  password_confirmation: string;
  email: string;
  full_name: string;
  role_ids: string[];
  account_status: AccountStatus;
  must_change_password: boolean;
  business_name: string;
  slug: string;
  legal_name: string;
  contact_name: string;
  vendor_email: string;
  phone: string;
  vendor_status: string;
  commission: number;
};

export type RoleForm = { name: string; permissions: string[] };

export const ACCOUNT_STATUSES: AccountStatus[] = [
  "active",
  "pending",
  "paused",
  "stopped",
];
