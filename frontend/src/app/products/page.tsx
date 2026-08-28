import { redirect } from "next/navigation";

export default function LegacyProductsPage() {
  redirect("/admin/products");
}
