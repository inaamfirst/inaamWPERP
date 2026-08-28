"use client";

import {
  useEffect,
  useMemo,
  useState,
  type ChangeEvent,
  type FormEvent,
  type KeyboardEvent,
} from "react";
import { ApiError, fetchApi } from "@/lib/api";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { useAuth } from "@/contexts/AuthContext";
import styles from "@/components/commerce.module.css";

type ImageRecord = {
  id?: string | null;
  url: string;
  variant_id?: string | null;
  external_id?: string | null;
  name?: string | null;
  alt_text?: string | null;
  sort_order?: number;
  sync_status?: string;
};

type VariantRecord = {
  id?: string | null;
  name?: string | null;
  sku?: string | null;
  barcode?: string | null;
  price_minor?: number;
  sale_price_minor?: number | null;
  cost_minor?: number | null;
  currency?: string;
  attributes?: Record<string, unknown>;
  manage_stock?: boolean | null;
  stock_quantity?: number | null;
  stock_status?: string | null;
  backorders?: string | null;
  weight?: string | null;
  length?: string | null;
  width?: string | null;
  height?: string | null;
  shipping_class?: string | null;
  description?: string | null;
  image_url?: string | null;
  metadata?: Record<string, unknown>;
  is_active?: boolean;
};

type Product = {
  id: string;
  name: string;
  slug?: string | null;
  sku?: string | null;
  barcode?: string | null;
  product_type?: string;
  status: string;
  category_id?: string | null;
  brand_id?: string | null;
  category_ids?: string[];
  description?: string | null;
  short_description?: string | null;
  seo_title?: string | null;
  seo_description?: string | null;
  visibility?: string;
  featured?: boolean;
  global_unique_id?: string | null;
  regular_price_minor: number;
  sale_price_minor?: number | null;
  sale_start_at?: string | null;
  sale_end_at?: string | null;
  tax_status?: string;
  tax_class?: string | null;
  manage_stock?: boolean;
  stock_quantity?: number | null;
  stock_status?: string;
  backorders?: string;
  sold_individually?: boolean;
  weight?: string | null;
  length?: string | null;
  width?: string | null;
  height?: string | null;
  shipping_class?: string | null;
  reviews_allowed?: boolean;
  purchase_note?: string | null;
  menu_order?: number;
  tags?: string[];
  upsell_ids?: string[];
  cross_sell_ids?: string[];
  grouped_product_ids?: string[];
  attributes?: unknown[];
  default_attributes?: unknown[];
  custom_metadata?: Record<string, unknown>;
  metadata?: Record<string, unknown>;
  variants?: VariantRecord[];
  images?: ImageRecord[];
};

type Listing = {
  product_id: string;
  listing_status: string;
  sync_status: string;
};
type Reference = { id: string; name: string; is_active?: boolean };

type ImageForm = {
  id?: string | null;
  url: string;
  name: string;
  alt_text: string;
  sort_order: string;
  variant_id: string;
  external_id: string;
};

type VariantForm = {
  id?: string | null;
  name: string;
  sku: string;
  barcode: string;
  price: string;
  sale_price: string;
  cost: string;
  currency: string;
  attributes: string;
  manage_stock: boolean;
  stock_quantity: string;
  stock_status: string;
  backorders: string;
  weight: string;
  length: string;
  width: string;
  height: string;
  shipping_class: string;
  description: string;
  image_url: string;
  metadata: string;
  is_active: boolean;
};

type ProductForm = {
  name: string;
  slug: string;
  sku: string;
  barcode: string;
  product_type: string;
  status: string;
  category_id: string;
  brand_id: string;
  description: string;
  short_description: string;
  regular_price: string;
  sale_price: string;
  sale_start_at: string;
  sale_end_at: string;
  global_unique_id: string;
  featured: boolean;
  visibility: string;
  tax_status: string;
  tax_class: string;
  manage_stock: boolean;
  stock_quantity: string;
  stock_status: string;
  backorders: string;
  sold_individually: boolean;
  weight: string;
  length: string;
  width: string;
  height: string;
  shipping_class: string;
  seo_title: string;
  seo_description: string;
  reviews_allowed: boolean;
  purchase_note: string;
  menu_order: string;
  tags: string;
  upsell_ids: string;
  cross_sell_ids: string;
  grouped_product_ids: string;
  attributes: string;
  default_attributes: string;
  custom_metadata: string;
  metadata: string;
  images: ImageForm[];
  variants: VariantForm[];
};

type Tab =
  | "basic"
  | "pricing"
  | "inventory"
  | "shipping"
  | "images"
  | "variants"
  | "seo"
  | "advanced";

const tabs: Array<[Tab, string]> = [
  ["basic", "Basic"],
  ["pricing", "Pricing"],
  ["inventory", "Inventory"],
  ["shipping", "Shipping"],
  ["images", "Images"],
  ["variants", "Variants"],
  ["seo", "SEO"],
  ["advanced", "Advanced"],
];

const emptyImage: ImageForm = {
  url: "",
  name: "",
  alt_text: "",
  sort_order: "0",
  variant_id: "",
  external_id: "",
};
const emptyVariant: VariantForm = {
  name: "",
  sku: "",
  barcode: "",
  price: "0",
  sale_price: "",
  cost: "",
  currency: "PKR",
  attributes: "{}",
  manage_stock: false,
  stock_quantity: "",
  stock_status: "instock",
  backorders: "no",
  weight: "",
  length: "",
  width: "",
  height: "",
  shipping_class: "",
  description: "",
  image_url: "",
  metadata: "{}",
  is_active: true,
};

const emptyForm: ProductForm = {
  name: "",
  slug: "",
  sku: "",
  barcode: "",
  product_type: "simple",
  status: "active",
  category_id: "",
  brand_id: "",
  description: "",
  short_description: "",
  regular_price: "0",
  sale_price: "",
  sale_start_at: "",
  sale_end_at: "",
  global_unique_id: "",
  featured: false,
  visibility: "visible",
  tax_status: "taxable",
  tax_class: "",
  manage_stock: false,
  stock_quantity: "",
  stock_status: "instock",
  backorders: "no",
  sold_individually: false,
  weight: "",
  length: "",
  width: "",
  height: "",
  shipping_class: "",
  seo_title: "",
  seo_description: "",
  reviews_allowed: true,
  purchase_note: "",
  menu_order: "0",
  tags: "",
  upsell_ids: "",
  cross_sell_ids: "",
  grouped_product_ids: "",
  attributes: "[]",
  default_attributes: "[]",
  custom_metadata: "{}",
  metadata: "{}",
  images: [],
  variants: [],
};

function money(minor: number | null | undefined) {
  return typeof minor === "number" && Number.isFinite(minor)
    ? `PKR ${(minor / 100).toFixed(2)}`
    : "—";
}

function listValue(values: string[] | undefined) {
  return (values || []).join(", ");
}
function optional(value: string) {
  const trimmed = value.trim();
  return trimmed || null;
}
function splitList(value: string) {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}
function minor(value: string, fallback: number | null = null) {
  if (!value.trim()) return fallback;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? Math.round(parsed * 100) : fallback;
}
function integer(value: string, fallback: number | null = null) {
  if (!value.trim()) return fallback;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? Math.round(parsed) : fallback;
}
function jsonValue(value: string, label: string) {
  try {
    return JSON.parse(value || "{}");
  } catch {
    throw new Error(`${label} contains invalid JSON.`);
  }
}
function dateInput(value: string | null | undefined) {
  return value ? value.slice(0, 16) : "";
}
function textValue(value: unknown) {
  return value == null ? "" : String(value);
}

function formFromProduct(product: Product): ProductForm {
  return {
    ...emptyForm,
    name: product.name,
    slug: textValue(product.slug),
    sku: textValue(product.sku),
    barcode: textValue(product.barcode),
    product_type: product.product_type || "simple",
    status: product.status,
    category_id: textValue(product.category_id),
    brand_id: textValue(product.brand_id),
    description: textValue(product.description),
    short_description: textValue(product.short_description),
    regular_price: ((product.regular_price_minor || 0) / 100).toFixed(2),
    sale_price:
      product.sale_price_minor == null
        ? ""
        : (product.sale_price_minor / 100).toFixed(2),
    sale_start_at: dateInput(product.sale_start_at),
    sale_end_at: dateInput(product.sale_end_at),
    global_unique_id: textValue(product.global_unique_id),
    featured: Boolean(product.featured),
    visibility: product.visibility || "visible",
    tax_status: product.tax_status || "taxable",
    tax_class: textValue(product.tax_class),
    manage_stock: Boolean(product.manage_stock),
    stock_quantity: textValue(product.stock_quantity),
    stock_status: product.stock_status || "instock",
    backorders: product.backorders || "no",
    sold_individually: Boolean(product.sold_individually),
    weight: textValue(product.weight),
    length: textValue(product.length),
    width: textValue(product.width),
    height: textValue(product.height),
    shipping_class: textValue(product.shipping_class),
    seo_title: textValue(product.seo_title),
    seo_description: textValue(product.seo_description),
    reviews_allowed: product.reviews_allowed !== false,
    purchase_note: textValue(product.purchase_note),
    menu_order: textValue(product.menu_order ?? 0),
    tags: listValue(product.tags),
    upsell_ids: listValue(product.upsell_ids),
    cross_sell_ids: listValue(product.cross_sell_ids),
    grouped_product_ids: listValue(product.grouped_product_ids),
    attributes: JSON.stringify(product.attributes || [], null, 2),
    default_attributes: JSON.stringify(
      product.default_attributes || [],
      null,
      2,
    ),
    custom_metadata: JSON.stringify(product.custom_metadata || {}, null, 2),
    metadata: JSON.stringify(product.metadata || {}, null, 2),
    images: (product.images || []).map((image) => ({
      id: image.id,
      url: image.url,
      name: textValue(image.name),
      alt_text: textValue(image.alt_text),
      sort_order: textValue(image.sort_order ?? 0),
      variant_id: textValue(image.variant_id),
      external_id: textValue(image.external_id),
    })),
    variants: (product.variants || []).map((variant) => ({
      id: variant.id,
      name: textValue(variant.name),
      sku: textValue(variant.sku),
      barcode: textValue(variant.barcode),
      price: ((variant.price_minor || 0) / 100).toFixed(2),
      sale_price:
        variant.sale_price_minor == null
          ? ""
          : (variant.sale_price_minor / 100).toFixed(2),
      cost:
        variant.cost_minor == null ? "" : (variant.cost_minor / 100).toFixed(2),
      currency: variant.currency || "PKR",
      attributes: JSON.stringify(variant.attributes || {}, null, 2),
      manage_stock: Boolean(variant.manage_stock),
      stock_quantity: textValue(variant.stock_quantity),
      stock_status: variant.stock_status || "instock",
      backorders: variant.backorders || "no",
      weight: textValue(variant.weight),
      length: textValue(variant.length),
      width: textValue(variant.width),
      height: textValue(variant.height),
      shipping_class: textValue(variant.shipping_class),
      description: textValue(variant.description),
      image_url: textValue(variant.image_url),
      metadata: JSON.stringify(variant.metadata || {}, null, 2),
      is_active: variant.is_active !== false,
    })),
  };
}

function payloadFromForm(form: ProductForm) {
  return {
    name: form.name.trim(),
    slug: optional(form.slug),
    sku: optional(form.sku),
    barcode: optional(form.barcode),
    product_type: form.product_type,
    status: form.status,
    category_id: optional(form.category_id),
    category_ids: splitList(form.category_id),
    brand_id: optional(form.brand_id),
    description: optional(form.description),
    short_description: optional(form.short_description),
    regular_price_minor: minor(form.regular_price, 0),
    sale_price_minor: minor(form.sale_price),
    sale_start_at: optional(form.sale_start_at),
    sale_end_at: optional(form.sale_end_at),
    global_unique_id: optional(form.global_unique_id),
    featured: form.featured,
    visibility: form.visibility,
    tax_status: form.tax_status,
    tax_class: optional(form.tax_class),
    manage_stock: form.manage_stock,
    stock_quantity: integer(form.stock_quantity),
    stock_status: form.stock_status,
    backorders: form.backorders,
    sold_individually: form.sold_individually,
    weight: optional(form.weight),
    length: optional(form.length),
    width: optional(form.width),
    height: optional(form.height),
    shipping_class: optional(form.shipping_class),
    seo_title: optional(form.seo_title),
    seo_description: optional(form.seo_description),
    reviews_allowed: form.reviews_allowed,
    purchase_note: optional(form.purchase_note),
    menu_order: integer(form.menu_order, 0),
    tags: splitList(form.tags),
    upsell_ids: splitList(form.upsell_ids),
    cross_sell_ids: splitList(form.cross_sell_ids),
    grouped_product_ids: splitList(form.grouped_product_ids),
    attributes: jsonValue(form.attributes, "Attributes"),
    default_attributes: jsonValue(
      form.default_attributes,
      "Default attributes",
    ),
    custom_metadata: jsonValue(form.custom_metadata, "Custom metadata"),
    metadata: jsonValue(form.metadata, "Metadata"),
    images: form.images
      .filter((image) => image.url.trim())
      .map((image, index) => ({
        id: image.id || null,
        url: image.url.trim(),
        name: optional(image.name),
        alt_text: optional(image.alt_text),
        sort_order: integer(image.sort_order, index),
        variant_id: optional(image.variant_id),
        external_id: optional(image.external_id),
      })),
    variants: form.variants.map((variant) => ({
      id: variant.id || null,
      name: optional(variant.name),
      sku: optional(variant.sku),
      barcode: optional(variant.barcode),
      price_minor: minor(variant.price, 0),
      sale_price_minor: minor(variant.sale_price),
      cost_minor: minor(variant.cost),
      currency: variant.currency || "PKR",
      attributes: jsonValue(variant.attributes, "Variant attributes"),
      manage_stock: variant.manage_stock,
      stock_quantity: integer(variant.stock_quantity),
      stock_status: variant.stock_status,
      backorders: variant.backorders,
      weight: optional(variant.weight),
      length: optional(variant.length),
      width: optional(variant.width),
      height: optional(variant.height),
      shipping_class: optional(variant.shipping_class),
      description: optional(variant.description),
      image_url: optional(variant.image_url),
      metadata: jsonValue(variant.metadata, "Variant metadata"),
      is_active: variant.is_active,
    })),
  };
}

export default function VendorProducts() {
  const { permissions } = useAuth();
  const canManage = permissions.includes("vendor.products.manage");
  const [products, setProducts] = useState<Product[]>([]);
  const [listings, setListings] = useState<Listing[]>([]);
  const [categories, setCategories] = useState<Reference[]>([]);
  const [brands, setBrands] = useState<Reference[]>([]);
  const [form, setForm] = useState<ProductForm>(emptyForm);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("basic");
  const [showEditor, setShowEditor] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [confirmDelete, setConfirmDelete] = useState(false);

  async function load() {
    setLoading(true);
    try {
      const [productData, listingData, categoryData, brandData] =
        await Promise.all([
          fetchApi("/vendor/catalog/products?include_archived=true"),
          fetchApi("/commerce/vendor/products/channels"),
          fetchApi("/vendor/catalog/categories"),
          fetchApi("/vendor/catalog/brands"),
        ]);
      setProducts(productData as Product[]);
      setListings(listingData as Listing[]);
      setCategories(categoryData as Reference[]);
      setBrands(brandData as Reference[]);
    } catch (caught) {
      setError(
        caught instanceof ApiError
          ? String(caught.data.detail || caught.message)
          : "Failed to load your product catalog.",
      );
    } finally {
      setLoading(false);
    }
  }

  // The initial fetch synchronizes this client view with the API.
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
  }, []);

  const listingByProduct = useMemo(
    () => new Map(listings.map((listing) => [listing.product_id, listing])),
    [listings],
  );
  const productOptions = useMemo(
    () => products.filter((product) => product.id !== selectedId),
    [products, selectedId],
  );

  function setField<K extends keyof ProductForm>(
    field: K,
    value: ProductForm[K],
  ) {
    setForm((current) => ({ ...current, [field]: value }));
  }
  function openNew() {
    if (!canManage) return;
    setSelectedId(null);
    setForm(emptyForm);
    setTab("basic");
    setShowEditor(true);
    setError("");
    setMessage("");
  }
  function openProduct(product: Product) {
    if (!canManage) return;
    setSelectedId(product.id);
    setForm(formFromProduct(product));
    setTab("basic");
    setShowEditor(true);
    setError("");
    setMessage("");
  }

  async function createReference(kind: "category" | "brand") {
    if (!canManage) return;
    const name = window.prompt(`New ${kind} name`);
    if (!name?.trim()) return;
    try {
      const created = (await fetchApi(
        `/vendor/catalog/${kind === "category" ? "categories" : "brands"}`,
        { method: "POST", body: JSON.stringify({ name: name.trim() }) },
      )) as Reference;
      if (kind === "category") {
        setCategories((current) => [...current, created]);
        setField("category_id", created.id);
      } else {
        setBrands((current) => [...current, created]);
        setField("brand_id", created.id);
      }
      setMessage(`${kind === "category" ? "Category" : "Brand"} created.`);
    } catch (caught) {
      setError(
        caught instanceof ApiError
          ? String(caught.data.detail || caught.message)
          : `The ${kind} could not be created.`,
      );
    }
  }

  async function saveProduct(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canManage) return;
    setSaving(true);
    setError("");
    setMessage("");
    try {
      if (form.name.trim().length < 2)
        throw new Error("Product name is required.");
      const saved = (await fetchApi(
        selectedId
          ? `/vendor/catalog/products/${selectedId}`
          : "/vendor/catalog/products",
        {
          method: selectedId ? "PATCH" : "POST",
          body: JSON.stringify(payloadFromForm(form)),
        },
      )) as Product;
      setSelectedId(saved.id);
      setForm(formFromProduct(saved));
      setMessage("Product saved successfully.");
      await load();
    } catch (caught) {
      setError(
        caught instanceof ApiError
          ? String(caught.data.detail || caught.message)
          : caught instanceof Error
            ? caught.message
            : "The product could not be saved.",
      );
    } finally {
      setSaving(false);
    }
  }

  async function changeStatus(status: string) {
    if (!canManage || !selectedId) return;
    setSaving(true);
    setError("");
    try {
      const saved = (await fetchApi(`/vendor/catalog/products/${selectedId}`, {
        method: "PATCH",
        body: JSON.stringify({ status }),
      })) as Product;
      setForm(formFromProduct(saved));
      setMessage(`Product marked ${status}.`);
      await load();
    } catch (caught) {
      setError(
        caught instanceof ApiError
          ? String(caught.data.detail || caught.message)
          : "Product status could not be updated.",
      );
    } finally {
      setSaving(false);
    }
  }

  async function publishSelectedProduct() {
    if (!canManage || !selectedId) return;
    setSaving(true);
    setError("");
    setMessage("");
    try {
      const publishForm = { ...form, status: "active" };
      const saved = (await fetchApi(`/vendor/catalog/products/${selectedId}`, {
        method: "PATCH",
        body: JSON.stringify(payloadFromForm(publishForm)),
      })) as Product;
      await fetchApi(`/commerce/vendor/products/${selectedId}/channel`, {
        method: "PUT",
        body: JSON.stringify({
          channel: "woocommerce",
          listing_status: "published",
        }),
      });
      setForm(formFromProduct(saved));
      setMessage("Product published successfully.");
      await load();
    } catch (caught) {
      setError(
        caught instanceof ApiError
          ? String(caught.data.detail || caught.message)
          : "The product could not be published online.",
      );
    } finally {
      setSaving(false);
    }
  }

  async function deletePermanently() {
    if (!canManage || !selectedId || form.status !== "archived") return;
    setSaving(true);
    setError("");
    try {
      await fetchApi(`/vendor/catalog/products/${selectedId}/permanent`, {
        method: "DELETE",
      });
      setConfirmDelete(false);
      setSelectedId(null);
      setForm(emptyForm);
      setShowEditor(false);
      setMessage("Product permanently deleted.");
      await load();
    } catch (caught) {
      setError(
        caught instanceof ApiError
          ? String(caught.data.detail || caught.message)
          : "The product could not be deleted permanently.",
      );
    } finally {
      setSaving(false);
    }
  }

  function updateImage(index: number, field: keyof ImageForm, value: string) {
    setField(
      "images",
      form.images.map((image, imageIndex) =>
        imageIndex === index ? { ...image, [field]: value } : image,
      ),
    );
  }
  function updateVariant(
    index: number,
    field: keyof VariantForm,
    value: string | boolean,
  ) {
    setField(
      "variants",
      form.variants.map((variant, variantIndex) =>
        variantIndex === index ? { ...variant, [field]: value } : variant,
      ),
    );
  }

  function moveTab(event: KeyboardEvent<HTMLButtonElement>, current: Tab) {
    if (
      event.key !== "ArrowLeft" &&
      event.key !== "ArrowRight" &&
      event.key !== "Home" &&
      event.key !== "End"
    )
      return;
    event.preventDefault();
    const currentIndex = tabs.findIndex(([value]) => value === current);
    const nextIndex =
      event.key === "Home"
        ? 0
        : event.key === "End"
          ? tabs.length - 1
          : event.key === "ArrowRight"
            ? (currentIndex + 1) % tabs.length
            : (currentIndex - 1 + tabs.length) % tabs.length;
    const next = tabs[nextIndex][0];
    setTab(next);
    requestAnimationFrame(() =>
      document.getElementById(`product-tab-${next}`)?.focus(),
    );
  }

  async function uploadImage(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file || !canManage) return;
    if (!selectedId) {
      setError("Save the product before uploading an image.");
      return;
    }
    setError("");
    try {
      await fetchApi(`/vendor/catalog/products/${selectedId}/images/upload`, {
        method: "POST",
        body: (() => {
          const data = new FormData();
          data.append("file", file);
          return data;
        })(),
      });
      setMessage("Image uploaded.");
      const latest = (await fetchApi(
        `/vendor/catalog/products/${selectedId}`,
      )) as Product;
      setForm(formFromProduct(latest));
      await load();
    } catch (caught) {
      setError(
        caught instanceof ApiError
          ? String(caught.data.detail || caught.message)
          : "The image could not be uploaded.",
      );
    }
  }

  async function publish(product: Product, published: boolean) {
    if (!canManage) return;
    setError("");
    setMessage("");
    try {
      await fetchApi(`/commerce/vendor/products/${product.id}/channel`, {
        method: "PUT",
        body: JSON.stringify({
          channel: "woocommerce",
          listing_status: published ? "published" : "private",
        }),
      });
      setMessage(
        published ? "Product published successfully." : "Product kept private.",
      );
      await load();
    } catch (caught) {
      setError(
        caught instanceof ApiError
          ? String(caught.data.detail || caught.message)
          : "The online listing could not be updated.",
      );
    }
  }

  return (
    <>
      <div className={styles.pageHeader}>
        <div>
          <div className={styles.eyebrow}>Catalog and channel control</div>
          <h1 className={styles.pageTitle}>Products &amp; publishing</h1>
          <p className={styles.pageSubtitle}>
            Operate your vendor catalog from the webview with the same product
            options as the ERP desktop editor.
          </p>
        </div>
        {canManage && (
          <div className={styles.headerActions}>
            <button
              type="button"
              className={styles.primaryButton}
              onClick={openNew}
            >
              New product
            </button>
          </div>
        )}
      </div>
      {message && <div className={styles.notice}>{message}</div>}
      {error && <div className={styles.error}>{error}</div>}
      <div className={styles.notice}>
        Vendor ownership is locked to your account. Product details, stock,
        media, variants, SEO, and channel publishing are managed here.
      </div>
      <div className={styles.formGrid}>
        <section className={styles.panel}>
          <div className={styles.toolbar}>
            <div>
              <h2 className={styles.panelTitle}>My products</h2>
              <p className={styles.muted}>
                {products.length} product{products.length === 1 ? "" : "s"}{" "}
                loaded.
              </p>
            </div>
            <button
              type="button"
              className={styles.secondaryButton}
              onClick={() => void load()}
            >
              Refresh
            </button>
          </div>
          {loading ? (
            <div className={styles.empty}>Loading products…</div>
          ) : (
            <div className={styles.tableWrap}>
              <table className={`${styles.table} ${styles.mobileCardTable}`}>
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>SKU</th>
                    <th>Price</th>
                    <th>Status</th>
                    <th>Online</th>
                    {canManage && <th>Actions</th>}
                  </tr>
                </thead>
                <tbody>
                  {products.map((product) => {
                    const listing = listingByProduct.get(product.id);
                    const published = listing?.listing_status === "published";
                    return (
                      <tr key={product.id}>
                        <td data-label="Name">
                          <strong>{product.name}</strong>
                          <br />
                          <span className={styles.muted}>
                            {product.product_type || "simple"}
                          </span>
                        </td>
                        <td data-label="SKU">{product.sku || "—"}</td>
                        <td data-label="Price">
                          {money(product.regular_price_minor)}
                        </td>
                        <td data-label="Status">
                          <span
                            className={`${styles.badge} ${product.status === "active" ? styles.badgeSuccess : styles.badgeWarning}`}
                          >
                            {product.status}
                          </span>
                        </td>
                        <td data-label="Online">
                          <span
                            className={`${styles.badge} ${published ? styles.badgeSuccess : styles.badgeWarning}`}
                          >
                            {listing?.listing_status || "private"}
                          </span>
                        </td>
                        {canManage && (
                          <td data-label="Actions">
                            <div className={styles.toolbarActions}>
                              <button
                                type="button"
                                className={styles.secondaryButton}
                                onClick={() => openProduct(product)}
                              >
                                Edit
                              </button>
                              <button
                                type="button"
                                className={
                                  published
                                    ? styles.secondaryButton
                                    : styles.primaryButton
                                }
                                onClick={() =>
                                  void publish(product, !published)
                                }
                              >
                                {published ? "Keep private" : "Publish"}
                              </button>
                            </div>
                          </td>
                        )}
                      </tr>
                    );
                  })}
                  {products.length === 0 && (
                    <tr>
                      <td colSpan={canManage ? 6 : 5} className={styles.empty}>
                        No vendor products found.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          )}
        </section>
        {canManage && showEditor && (
          <section className={`${styles.panel} ${styles.productEditorPanel}`}>
            <div className={styles.toolbar}>
              <div>
                <h2 className={styles.panelTitle}>
                  {selectedId ? "Edit product" : "New product"}
                </h2>
                <p className={styles.muted}>
                  All fields use the same catalog API as the ERP desktop editor.
                </p>
              </div>
              <button
                type="button"
                className={styles.secondaryButton}
                onClick={() => setShowEditor(false)}
              >
                Close
              </button>
            </div>
            <div
              className={styles.workspaceBar}
              role="tablist"
              aria-label="Product editor sections"
            >
              {tabs.map(([value, label]) => (
                <button
                  type="button"
                  role="tab"
                  id={`product-tab-${value}`}
                  aria-controls="product-editor-panel"
                  aria-selected={tab === value}
                  tabIndex={tab === value ? 0 : -1}
                  key={value}
                  className={`${styles.workspaceButton} ${tab === value ? styles.workspaceButtonActive : ""}`}
                  onClick={() => setTab(value)}
                  onKeyDown={(event) => moveTab(event, value)}
                >
                  {label}
                </button>
              ))}
            </div>
            <form
              onSubmit={saveProduct}
              role="tabpanel"
              id="product-editor-panel"
              aria-labelledby={`product-tab-${tab}`}
            >
              {tab === "basic" && (
                <div className={styles.formGrid}>
                  <label className={styles.field}>
                    Name *
                    <input
                      value={form.name}
                      onChange={(event) => setField("name", event.target.value)}
                      required
                      minLength={2}
                    />
                  </label>
                  <label className={styles.field}>
                    Slug
                    <input
                      value={form.slug}
                      onChange={(event) => setField("slug", event.target.value)}
                    />
                  </label>
                  <label className={styles.field}>
                    SKU
                    <input
                      value={form.sku}
                      onChange={(event) => setField("sku", event.target.value)}
                    />
                  </label>
                  <label className={styles.field}>
                    Barcode
                    <input
                      value={form.barcode}
                      onChange={(event) =>
                        setField("barcode", event.target.value)
                      }
                    />
                  </label>
                  <label className={styles.field}>
                    Type
                    <select
                      value={form.product_type}
                      onChange={(event) =>
                        setField("product_type", event.target.value)
                      }
                    >
                      <option value="simple">Simple</option>
                      <option value="variable">Variable</option>
                      <option value="digital">Digital</option>
                      <option value="service">Service</option>
                    </select>
                  </label>
                  <label className={styles.field}>
                    Status
                    <select
                      value={form.status}
                      onChange={(event) =>
                        setField("status", event.target.value)
                      }
                    >
                      <option value="active">Active / Published</option>
                      <option value="draft">Draft</option>
                      <option value="archived">Trash</option>
                    </select>
                  </label>
                  <label className={styles.field}>
                    Category
                    <select
                      value={form.category_id}
                      onChange={(event) =>
                        setField("category_id", event.target.value)
                      }
                    >
                      <option value="">No category</option>
                      {categories.map((category) => (
                        <option key={category.id} value={category.id}>
                          {category.name}
                        </option>
                      ))}
                    </select>
                  </label>
                  <button
                    type="button"
                    className={styles.secondaryButton}
                    onClick={() => void createReference("category")}
                  >
                    New category
                  </button>
                  <label className={styles.field}>
                    Brand
                    <select
                      value={form.brand_id}
                      onChange={(event) =>
                        setField("brand_id", event.target.value)
                      }
                    >
                      <option value="">No brand</option>
                      {brands.map((brand) => (
                        <option key={brand.id} value={brand.id}>
                          {brand.name}
                        </option>
                      ))}
                    </select>
                  </label>
                  <button
                    type="button"
                    className={styles.secondaryButton}
                    onClick={() => void createReference("brand")}
                  >
                    New brand
                  </button>
                  <label
                    className={`${styles.field} ${styles.fullWidth}`}
                  >
                    Description
                    <textarea
                      value={form.description}
                      onChange={(event) =>
                        setField("description", event.target.value)
                      }
                    />
                  </label>
                  <label
                    className={`${styles.field} ${styles.fullWidth}`}
                  >
                    Short description
                    <textarea
                      value={form.short_description}
                      onChange={(event) =>
                        setField("short_description", event.target.value)
                      }
                    />
                  </label>
                </div>
              )}
              {tab === "pricing" && (
                <div className={styles.formGrid}>
                  <label className={styles.field}>
                    Regular price (PKR)
                    <input
                      type="number"
                      min="0"
                      step="0.01"
                      value={form.regular_price}
                      onChange={(event) =>
                        setField("regular_price", event.target.value)
                      }
                    />
                  </label>
                  <label className={styles.field}>
                    Sale price (PKR)
                    <input
                      type="number"
                      min="0"
                      step="0.01"
                      value={form.sale_price}
                      onChange={(event) =>
                        setField("sale_price", event.target.value)
                      }
                    />
                  </label>
                  <label className={styles.field}>
                    Sale starts
                    <input
                      type="datetime-local"
                      value={form.sale_start_at}
                      onChange={(event) =>
                        setField("sale_start_at", event.target.value)
                      }
                    />
                  </label>
                  <label className={styles.field}>
                    Sale ends
                    <input
                      type="datetime-local"
                      value={form.sale_end_at}
                      onChange={(event) =>
                        setField("sale_end_at", event.target.value)
                      }
                    />
                  </label>
                  <label className={styles.field}>
                    Global unique ID
                    <input
                      value={form.global_unique_id}
                      onChange={(event) =>
                        setField("global_unique_id", event.target.value)
                      }
                    />
                  </label>
                  <label className={styles.field}>
                    Tax status
                    <select
                      value={form.tax_status}
                      onChange={(event) =>
                        setField("tax_status", event.target.value)
                      }
                    >
                      <option value="taxable">Taxable</option>
                      <option value="shipping">Shipping only</option>
                      <option value="none">None</option>
                    </select>
                  </label>
                  <label className={styles.field}>
                    Tax class
                    <input
                      value={form.tax_class}
                      onChange={(event) =>
                        setField("tax_class", event.target.value)
                      }
                    />
                  </label>
                  <label className={styles.field}>
                    <span>Featured</span>
                    <input
                      type="checkbox"
                      checked={form.featured}
                      onChange={(event) =>
                        setField("featured", event.target.checked)
                      }
                    />
                  </label>
                  <label className={styles.field}>
                    Visibility
                    <select
                      value={form.visibility}
                      onChange={(event) =>
                        setField("visibility", event.target.value)
                      }
                    >
                      <option value="visible">Visible</option>
                      <option value="catalog">Catalog only</option>
                      <option value="search">Search only</option>
                      <option value="hidden">Hidden</option>
                    </select>
                  </label>
                </div>
              )}
              {tab === "inventory" && (
                <div className={styles.formGrid}>
                  <label className={styles.field}>
                    <span>Manage stock</span>
                    <input
                      type="checkbox"
                      checked={form.manage_stock}
                      onChange={(event) =>
                        setField("manage_stock", event.target.checked)
                      }
                    />
                  </label>
                  <label className={styles.field}>
                    Stock quantity
                    <input
                      type="number"
                      min="0"
                      step="1"
                      value={form.stock_quantity}
                      onChange={(event) =>
                        setField("stock_quantity", event.target.value)
                      }
                    />
                  </label>
                  <label className={styles.field}>
                    Stock status
                    <select
                      value={form.stock_status}
                      onChange={(event) =>
                        setField("stock_status", event.target.value)
                      }
                    >
                      <option value="instock">In stock</option>
                      <option value="outofstock">Out of stock</option>
                      <option value="onbackorder">On backorder</option>
                    </select>
                  </label>
                  <label className={styles.field}>
                    Backorders
                    <select
                      value={form.backorders}
                      onChange={(event) =>
                        setField("backorders", event.target.value)
                      }
                    >
                      <option value="no">Do not allow</option>
                      <option value="notify">Allow, notify customer</option>
                      <option value="yes">Allow</option>
                    </select>
                  </label>
                  <label className={styles.field}>
                    <span>Sold individually</span>
                    <input
                      type="checkbox"
                      checked={form.sold_individually}
                      onChange={(event) =>
                        setField("sold_individually", event.target.checked)
                      }
                    />
                  </label>
                </div>
              )}
              {tab === "shipping" && (
                <div className={styles.formGrid}>
                  <label className={styles.field}>
                    Weight
                    <input
                      value={form.weight}
                      onChange={(event) =>
                        setField("weight", event.target.value)
                      }
                    />
                  </label>
                  <label className={styles.field}>
                    Length
                    <input
                      value={form.length}
                      onChange={(event) =>
                        setField("length", event.target.value)
                      }
                    />
                  </label>
                  <label className={styles.field}>
                    Width
                    <input
                      value={form.width}
                      onChange={(event) =>
                        setField("width", event.target.value)
                      }
                    />
                  </label>
                  <label className={styles.field}>
                    Height
                    <input
                      value={form.height}
                      onChange={(event) =>
                        setField("height", event.target.value)
                      }
                    />
                  </label>
                  <label className={styles.field}>
                    Shipping class
                    <input
                      value={form.shipping_class}
                      onChange={(event) =>
                        setField("shipping_class", event.target.value)
                      }
                    />
                  </label>
                </div>
              )}
              {tab === "images" && (
                <div>
                  <div className={styles.formActions}>
                    <button
                      type="button"
                      className={styles.secondaryButton}
                      onClick={() =>
                        setField("images", [
                          ...form.images,
                          {
                            ...emptyImage,
                            sort_order: String(form.images.length),
                          },
                        ])
                      }
                    >
                      Add image URL
                    </button>
                    <label className={styles.secondaryButton}>
                      Upload image
                      <input
                        type="file"
                        accept="image/jpeg,image/png,image/webp,image/gif"
                        hidden
                        onChange={(event) => void uploadImage(event)}
                      />
                    </label>
                  </div>
                  <p className={styles.muted}>
                    Save the product before uploading a local file. Image URLs
                    can be added before saving.
                  </p>
                  {form.images.map((image, index) => (
                    <div
                      className={styles.panel}
                      key={`${image.id || "new"}-${index}`}
                    >
                      <div className={styles.formGrid}>
                        <label className={styles.field}>
                          URL
                          <input
                            value={image.url}
                            onChange={(event) =>
                              updateImage(index, "url", event.target.value)
                            }
                            required
                          />
                        </label>
                        <label className={styles.field}>
                          Name
                          <input
                            value={image.name}
                            onChange={(event) =>
                              updateImage(index, "name", event.target.value)
                            }
                          />
                        </label>
                        <label className={styles.field}>
                          Alt text
                          <input
                            value={image.alt_text}
                            onChange={(event) =>
                              updateImage(index, "alt_text", event.target.value)
                            }
                          />
                        </label>
                        <label className={styles.field}>
                          Sort order
                          <input
                            type="number"
                            min="0"
                            value={image.sort_order}
                            onChange={(event) =>
                              updateImage(
                                index,
                                "sort_order",
                                event.target.value,
                              )
                            }
                          />
                        </label>
                        <label className={styles.field}>
                          Variant ID
                          <input
                            value={image.variant_id}
                            onChange={(event) =>
                              updateImage(
                                index,
                                "variant_id",
                                event.target.value,
                              )
                            }
                          />
                        </label>
                        <label className={styles.field}>
                          External ID
                          <input
                            value={image.external_id}
                            onChange={(event) =>
                              updateImage(
                                index,
                                "external_id",
                                event.target.value,
                              )
                            }
                          />
                        </label>
                      </div>
                      <button
                        type="button"
                        className={styles.dangerButton}
                        onClick={() =>
                          setField(
                            "images",
                            form.images.filter(
                              (_item, itemIndex) => itemIndex !== index,
                            ),
                          )
                        }
                      >
                        Remove image
                      </button>
                    </div>
                  ))}
                  {form.images.length === 0 && (
                    <div className={styles.empty}>No images added.</div>
                  )}
                </div>
              )}
              {tab === "variants" && (
                <div>
                  <div className={styles.formActions}>
                    <button
                      type="button"
                      className={styles.secondaryButton}
                      onClick={() =>
                        setField("variants", [
                          ...form.variants,
                          { ...emptyVariant },
                        ])
                      }
                    >
                      Add variant
                    </button>
                  </div>
                  {form.variants.map((variant, index) => (
                    <div
                      className={styles.panel}
                      key={`${variant.id || "new"}-${index}`}
                    >
                      <div className={styles.toolbar}>
                        <h3 className={styles.panelTitle}>
                          Variant {index + 1}
                        </h3>
                        <button
                          type="button"
                          className={styles.dangerButton}
                          onClick={() =>
                            setField(
                              "variants",
                              form.variants.filter(
                                (_item, itemIndex) => itemIndex !== index,
                              ),
                            )
                          }
                        >
                          Remove
                        </button>
                      </div>
                      <div className={styles.formGrid}>
                        <label className={styles.field}>
                          Name
                          <input
                            value={variant.name}
                            onChange={(event) =>
                              updateVariant(index, "name", event.target.value)
                            }
                          />
                        </label>
                        <label className={styles.field}>
                          SKU
                          <input
                            value={variant.sku}
                            onChange={(event) =>
                              updateVariant(index, "sku", event.target.value)
                            }
                          />
                        </label>
                        <label className={styles.field}>
                          Barcode
                          <input
                            value={variant.barcode}
                            onChange={(event) =>
                              updateVariant(
                                index,
                                "barcode",
                                event.target.value,
                              )
                            }
                          />
                        </label>
                        <label className={styles.field}>
                          Price (PKR)
                          <input
                            type="number"
                            min="0"
                            step="0.01"
                            value={variant.price}
                            onChange={(event) =>
                              updateVariant(index, "price", event.target.value)
                            }
                          />
                        </label>
                        <label className={styles.field}>
                          Sale price (PKR)
                          <input
                            type="number"
                            min="0"
                            step="0.01"
                            value={variant.sale_price}
                            onChange={(event) =>
                              updateVariant(
                                index,
                                "sale_price",
                                event.target.value,
                              )
                            }
                          />
                        </label>
                        <label className={styles.field}>
                          Cost (PKR)
                          <input
                            type="number"
                            min="0"
                            step="0.01"
                            value={variant.cost}
                            onChange={(event) =>
                              updateVariant(index, "cost", event.target.value)
                            }
                          />
                        </label>
                        <label className={styles.field}>
                          Currency
                          <input
                            value={variant.currency}
                            onChange={(event) =>
                              updateVariant(
                                index,
                                "currency",
                                event.target.value,
                              )
                            }
                            maxLength={3}
                          />
                        </label>
                        <label className={styles.field}>
                          <span>Active</span>
                          <input
                            type="checkbox"
                            checked={variant.is_active}
                            onChange={(event) =>
                              updateVariant(
                                index,
                                "is_active",
                                event.target.checked,
                              )
                            }
                          />
                        </label>
                        <label className={styles.field}>
                          <span>Manage stock</span>
                          <input
                            type="checkbox"
                            checked={variant.manage_stock}
                            onChange={(event) =>
                              updateVariant(
                                index,
                                "manage_stock",
                                event.target.checked,
                              )
                            }
                          />
                        </label>
                        <label className={styles.field}>
                          Stock quantity
                          <input
                            type="number"
                            min="0"
                            value={variant.stock_quantity}
                            onChange={(event) =>
                              updateVariant(
                                index,
                                "stock_quantity",
                                event.target.value,
                              )
                            }
                          />
                        </label>
                        <label className={styles.field}>
                          Stock status
                          <select
                            value={variant.stock_status}
                            onChange={(event) =>
                              updateVariant(
                                index,
                                "stock_status",
                                event.target.value,
                              )
                            }
                          >
                            <option value="instock">In stock</option>
                            <option value="outofstock">Out of stock</option>
                            <option value="onbackorder">On backorder</option>
                          </select>
                        </label>
                        <label className={styles.field}>
                          Backorders
                          <select
                            value={variant.backorders}
                            onChange={(event) =>
                              updateVariant(
                                index,
                                "backorders",
                                event.target.value,
                              )
                            }
                          >
                            <option value="no">No</option>
                            <option value="notify">Notify</option>
                            <option value="yes">Yes</option>
                          </select>
                        </label>
                        <label className={styles.field}>
                          Weight
                          <input
                            value={variant.weight}
                            onChange={(event) =>
                              updateVariant(index, "weight", event.target.value)
                            }
                          />
                        </label>
                        <label className={styles.field}>
                          Length
                          <input
                            value={variant.length}
                            onChange={(event) =>
                              updateVariant(index, "length", event.target.value)
                            }
                          />
                        </label>
                        <label className={styles.field}>
                          Width
                          <input
                            value={variant.width}
                            onChange={(event) =>
                              updateVariant(index, "width", event.target.value)
                            }
                          />
                        </label>
                        <label className={styles.field}>
                          Height
                          <input
                            value={variant.height}
                            onChange={(event) =>
                              updateVariant(index, "height", event.target.value)
                            }
                          />
                        </label>
                        <label className={styles.field}>
                          Shipping class
                          <input
                            value={variant.shipping_class}
                            onChange={(event) =>
                              updateVariant(
                                index,
                                "shipping_class",
                                event.target.value,
                              )
                            }
                          />
                        </label>
                        <label className={styles.field}>
                          Image URL
                          <input
                            value={variant.image_url}
                            onChange={(event) =>
                              updateVariant(
                                index,
                                "image_url",
                                event.target.value,
                              )
                            }
                          />
                        </label>
                        <label
                          className={`${styles.field} ${styles.fullWidth}`}
                        >
                          Attributes JSON
                          <textarea
                            value={variant.attributes}
                            onChange={(event) =>
                              updateVariant(
                                index,
                                "attributes",
                                event.target.value,
                              )
                            }
                          />
                        </label>
                        <label
                          className={`${styles.field} ${styles.fullWidth}`}
                        >
                          Description
                          <textarea
                            value={variant.description}
                            onChange={(event) =>
                              updateVariant(
                                index,
                                "description",
                                event.target.value,
                              )
                            }
                          />
                        </label>
                        <label
                          className={`${styles.field} ${styles.fullWidth}`}
                        >
                          Metadata JSON
                          <textarea
                            value={variant.metadata}
                            onChange={(event) =>
                              updateVariant(
                                index,
                                "metadata",
                                event.target.value,
                              )
                            }
                          />
                        </label>
                      </div>
                    </div>
                  ))}
                  {form.variants.length === 0 && (
                    <div className={styles.empty}>No variants added.</div>
                  )}
                </div>
              )}
              {tab === "seo" && (
                <div className={styles.formGrid}>
                  <label className={styles.field}>
                    SEO title
                    <input
                      value={form.seo_title}
                      onChange={(event) =>
                        setField("seo_title", event.target.value)
                      }
                    />
                  </label>
                  <label className={styles.field}>
                    <span>Reviews allowed</span>
                    <input
                      type="checkbox"
                      checked={form.reviews_allowed}
                      onChange={(event) =>
                        setField("reviews_allowed", event.target.checked)
                      }
                    />
                  </label>
                  <label
                    className={`${styles.field} ${styles.fullWidth}`}
                  >
                    SEO description
                    <textarea
                      value={form.seo_description}
                      onChange={(event) =>
                        setField("seo_description", event.target.value)
                      }
                    />
                  </label>
                  <label
                    className={`${styles.field} ${styles.fullWidth}`}
                  >
                    Purchase note
                    <textarea
                      value={form.purchase_note}
                      onChange={(event) =>
                        setField("purchase_note", event.target.value)
                      }
                    />
                  </label>
                  <label className={styles.field}>
                    Menu order
                    <input
                      type="number"
                      value={form.menu_order}
                      onChange={(event) =>
                        setField("menu_order", event.target.value)
                      }
                    />
                  </label>
                </div>
              )}
              {tab === "advanced" && (
                <div className={styles.formGrid}>
                  <label className={styles.field}>
                    Tags
                    <input
                      value={form.tags}
                      onChange={(event) => setField("tags", event.target.value)}
                      placeholder="Comma-separated tags"
                    />
                  </label>
                  <label className={styles.field}>
                    Upsell product IDs
                    <input
                      value={form.upsell_ids}
                      onChange={(event) =>
                        setField("upsell_ids", event.target.value)
                      }
                    />
                  </label>
                  <label className={styles.field}>
                    Cross-sell product IDs
                    <input
                      value={form.cross_sell_ids}
                      onChange={(event) =>
                        setField("cross_sell_ids", event.target.value)
                      }
                    />
                  </label>
                  <label className={styles.field}>
                    Grouped product IDs
                    <input
                      value={form.grouped_product_ids}
                      onChange={(event) =>
                        setField("grouped_product_ids", event.target.value)
                      }
                    />
                  </label>
                  <label
                    className={`${styles.field} ${styles.fullWidth}`}
                  >
                    Attributes JSON
                    <textarea
                      value={form.attributes}
                      onChange={(event) =>
                        setField("attributes", event.target.value)
                      }
                    />
                  </label>
                  <label
                    className={`${styles.field} ${styles.fullWidth}`}
                  >
                    Default attributes JSON
                    <textarea
                      value={form.default_attributes}
                      onChange={(event) =>
                        setField("default_attributes", event.target.value)
                      }
                    />
                  </label>
                  <label
                    className={`${styles.field} ${styles.fullWidth}`}
                  >
                    Custom metadata JSON
                    <textarea
                      value={form.custom_metadata}
                      onChange={(event) =>
                        setField("custom_metadata", event.target.value)
                      }
                    />
                  </label>
                  <label
                    className={`${styles.field} ${styles.fullWidth}`}
                  >
                    Metadata JSON
                    <textarea
                      value={form.metadata}
                      onChange={(event) =>
                        setField("metadata", event.target.value)
                      }
                    />
                  </label>
                </div>
              )}
              <div
                className={`${styles.formActions} ${styles.productSaveActions}`}
              >
                <button
                  type="submit"
                  className={styles.primaryButton}
                  disabled={saving}
                >
                  {saving ? "Saving…" : "Save product"}
                </button>
                {selectedId && (
                  <>
                    <button
                      type="button"
                      className={styles.secondaryButton}
                      disabled={saving}
                      onClick={() =>
                        void changeStatus(
                          form.status === "archived" ? "active" : "archived",
                        )
                      }
                    >
                      {form.status === "archived" ? "Restore" : "Move to trash"}
                    </button>
                    <button
                      type="button"
                      className={styles.secondaryButton}
                      disabled={saving}
                      onClick={() => void changeStatus("draft")}
                    >
                      Save as draft
                    </button>
                    <button
                      type="button"
                      className={styles.primaryButton}
                      disabled={saving}
                      onClick={() => void publishSelectedProduct()}
                    >
                      Publish product
                    </button>
                    {form.status === "archived" && (
                      <button
                        type="button"
                        className={styles.dangerButton}
                        disabled={saving}
                        onClick={() => setConfirmDelete(true)}
                      >
                        Delete permanently
                      </button>
                    )}
                  </>
                )}
              </div>
            </form>
          </section>
        )}
      </div>
      <div className={`${styles.muted} ${styles.relationshipHint}`}>
        Available product references for relationships:{" "}
        {productOptions
          .map((product) => `${product.name} (${product.id})`)
          .join(" · ") || "none"}
      </div>
      <ConfirmDialog
        open={confirmDelete}
        title="Delete product permanently?"
        description={`${form.name || "This product"} and its editable catalog data will be permanently deleted. This action cannot be undone.`}
        confirmLabel="Delete permanently"
        destructive
        busy={saving}
        onCancel={() => setConfirmDelete(false)}
        onConfirm={() => void deletePermanently()}
      />
    </>
  );
}
