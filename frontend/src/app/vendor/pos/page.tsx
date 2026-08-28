"use client";

import { useEffect, useMemo, useState } from "react";
import { fetchApi } from "@/lib/api";
import styles from "@/components/commerce.module.css";

type Product = { id: string; name: string; sku?: string | null; regular_price_minor: number; stock_quantity?: number | null };
type Warehouse = { id: string; name: string; code: string };
type CartItem = Product & { quantity: number };

function CartList({ cart, onRemove }: { cart: CartItem[]; onRemove: (productId: string) => void }) {
  if (cart.length === 0) return <div className={styles.empty}>Your cart is empty. Add products to start a sale.</div>;
  return (
    <div className={styles.cartList}>
      {cart.map((item) => (
        <div className={styles.cartRow} key={item.id}>
          <span>
            <strong>{item.name}</strong>
            <br />
            <span className={styles.muted}>{item.quantity} × PKR {(item.regular_price_minor / 100).toFixed(2)}</span>
          </span>
          <button type="button" className={styles.dangerButton} onClick={() => onRemove(item.id)}>Remove</button>
        </div>
      ))}
    </div>
  );
}

export default function VendorPos() {
  const [products, setProducts] = useState<Product[]>([]);
  const [warehouses, setWarehouses] = useState<Warehouse[]>([]);
  const [cart, setCart] = useState<CartItem[]>([]);
  const [warehouseId, setWarehouseId] = useState("");
  const [customerName, setCustomerName] = useState("");
  const [paymentMethod, setPaymentMethod] = useState("cash");
  const [search, setSearch] = useState("");
  const [cartOpen, setCartOpen] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    Promise.all([fetchApi("/marketplace/vendor/products"), fetchApi("/commerce/vendor/warehouses")])
      .then(([productData, warehouseData]) => {
        setProducts(productData as Product[]);
        const rows = warehouseData as Warehouse[];
        setWarehouses(rows);
        setWarehouseId(rows[0]?.id || "");
      })
      .catch(() => setError("POS setup could not be loaded."));
  }, []);

  const filtered = products.filter((product) => `${product.name} ${product.sku || ""}`.toLowerCase().includes(search.toLowerCase()));
  const total = useMemo(() => cart.reduce((sum, item) => sum + item.regular_price_minor * item.quantity, 0), [cart]);

  function add(product: Product) {
    setCart((current) => {
      const found = current.find((item) => item.id === product.id);
      return found
        ? current.map((item) => item.id === product.id ? { ...item, quantity: item.quantity + 1 } : item)
        : [...current, { ...product, quantity: 1 }];
    });
    setMessage("");
  }

  function remove(productId: string) {
    setCart((current) => current.filter((item) => item.id !== productId));
  }

  async function completeSale() {
    if (!warehouseId || cart.length === 0) {
      setError("Choose a warehouse and add at least one product.");
      return;
    }
    setError("");
    setMessage("");
    try {
      const sale = await fetchApi("/commerce/vendor/pos/sales", {
        method: "POST",
        body: JSON.stringify({
          warehouse_id: warehouseId,
          customer_name: customerName || "Walk-in Customer",
          currency: "PKR",
          items: cart.map((item) => ({ product_id: item.id, quantity: item.quantity, unit_price_minor: item.regular_price_minor })),
          payments: [{ amount_minor: total, currency: "PKR", method: paymentMethod, status: "paid" }],
          idempotency_key: crypto.randomUUID(),
        }),
      }) as { order_number: string; total_minor: number };
      setMessage(`Sale ${sale.order_number} completed for PKR ${(sale.total_minor / 100).toFixed(2)}.`);
      setCart([]);
      setCustomerName("");
      setCartOpen(false);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Sale could not be completed.");
    }
  }

  const cartContent = (
    <>
      <div className={styles.sheetHeader}>
        <div>
          <h2 className={styles.panelTitle}>Current sale</h2>
          <p className={styles.muted}>{cart.length} item{cart.length === 1 ? "" : "s"} in cart</p>
        </div>
        {cartOpen && <button type="button" className={styles.secondaryButton} onClick={() => setCartOpen(false)}>Close</button>}
      </div>
      <CartList cart={cart} onRemove={remove} />
      <div className={styles.posCartTotal}>
        <div className={styles.metricLabel}>Total</div>
        <div className={styles.metricValue}>PKR {(total / 100).toFixed(2)}</div>
      </div>
      <div className={styles.formActions}>
        <button type="button" className={styles.primaryButton} disabled={!cart.length} onClick={completeSale}>Complete sale</button>
        <button type="button" className={styles.secondaryButton} onClick={() => setCart([])}>Clear</button>
      </div>
    </>
  );

  return (
    <>
      <div className={styles.pageHeader}>
        <div>
          <div className={styles.eyebrow}>Shop / offline workspace</div>
          <h1 className={styles.pageTitle}>Quick POS sale</h1>
          <p className={styles.pageSubtitle}>Sell from shared warehouse stock and post payment into the ERP ledger.</p>
        </div>
      </div>
      {message && <div className={styles.notice} role="status">{message}</div>}
      {error && <div className={styles.error} role="alert">{error}</div>}

      <section className={`${styles.panel} ${styles.posSetup}`} aria-label="Sale setup">
        <div className={styles.sectionHeading}>
          <div>
            <h2 className={styles.panelTitle}>Sale setup</h2>
            <p className={styles.muted}>Choose where the stock should be deducted and how the customer paid.</p>
          </div>
        </div>
        <div className={styles.formGrid}>
          <label className={styles.field}>Warehouse<select value={warehouseId} onChange={(event) => setWarehouseId(event.target.value)}>{warehouses.map((warehouse) => <option key={warehouse.id} value={warehouse.id}>{warehouse.code} · {warehouse.name}</option>)}</select></label>
          <label className={styles.field}>Customer / walk-in name<input value={customerName} onChange={(event) => setCustomerName(event.target.value)} placeholder="Walk-in Customer" /></label>
          <label className={styles.field}>Payment method<select value={paymentMethod} onChange={(event) => setPaymentMethod(event.target.value)}><option value="cash">Cash</option><option value="bank">Bank</option><option value="card">Card</option><option value="cod">COD</option></select></label>
        </div>
      </section>

      <div className={styles.posLayout}>
        <section className={styles.panel}>
          <div className={styles.toolbar}>
            <div>
              <h2 className={styles.panelTitle}>Products</h2>
              <p className={styles.muted}>Tap a product to add it to the sale.</p>
            </div>
            <input aria-label="Search products" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search SKU or name" />
          </div>
          <div className={styles.posProductGrid}>
            {filtered.map((product) => (
              <article className={styles.posProductCard} key={product.id}>
                <div className={styles.posProductCardInfo}>
                  <strong>{product.name}</strong>
                  <span>{product.sku || "No SKU"}</span>
                </div>
                <div className={styles.posProductMeta}>
                  <strong>PKR {(product.regular_price_minor / 100).toFixed(2)}</strong>
                  {product.stock_quantity !== undefined && <span>{product.stock_quantity ?? 0} available</span>}
                </div>
                <button type="button" className={styles.primaryButton} onClick={() => add(product)}>Add</button>
              </article>
            ))}
            {filtered.length === 0 && <div className={styles.empty}>No products found.</div>}
          </div>
        </section>

        <section className={`${styles.panel} ${styles.posCartPanel}`} aria-label="Current sale">
          {cartContent}
        </section>
      </div>

      {cart.length > 0 && (
        <div className={styles.mobileCartBar}>
          <div className={styles.cartBarLabel}><strong>{cart.length} item{cart.length === 1 ? "" : "s"} in sale</strong><span>PKR {(total / 100).toFixed(2)}</span></div>
          <button type="button" className={styles.primaryButton} onClick={() => setCartOpen(true)}>Review sale</button>
        </div>
      )}

      {cartOpen && (
        <>
          <div className={styles.sheetBackdrop} onClick={() => setCartOpen(false)} />
          <section className={styles.sheet} role="dialog" aria-modal="true" aria-label="Current sale">
            <div className={styles.sheetHandle} />
            {cartContent}
          </section>
        </>
      )}
    </>
  );
}
