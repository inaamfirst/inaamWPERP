import { redirect } from "next/navigation";

export default function LegacyNewProductPage() {
  redirect("/admin/products/new");
}
