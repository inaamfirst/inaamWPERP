"use client";

import { useEffect, useMemo, useState } from "react";
import { fetchApi } from "@/lib/api";
import styles from "@/components/commerce.module.css";

type Product = { id: string; name: string; sku?: string | null; barcode?: string | null; regular_price_minor: number; sale_price_minor?: number | null; stock_quantity: number; low_stock?: boolean; online_status?: string };
type CartItem = Product & { quantity: number };
type Supplier = { id: string; name: string; phone?: string | null; contact_name?: string | null; outstanding_minor?: number };
type Category = { id: string; name: string };
type Purchase = { id: string; purchase_number: string; total_minor: number; paid_minor: number; payment_status: string; created_at: string };
type Sale = { id: string; bill_number: string; created_at: string; customer: string; total_minor: number; payment_method: string; payment_status: string; status: string };
type Receipt = { id: string; order_number: string; total_minor: number };
type Modal = "new-product" | "receive-stock" | "suppliers" | "purchases" | "sales" | null;

const money = (minor: number) => `PKR ${(minor / 100).toFixed(2)}`;
const toMinor = (value: string) => Math.max(0, Math.round(Number(value || 0) * 100));

export default function VendorPos() {
  const [products, setProducts] = useState<Product[]>([]);
  const [suppliers, setSuppliers] = useState<Supplier[]>([]);
  const [categories, setCategories] = useState<Category[]>([]);
  const [purchases, setPurchases] = useState<Purchase[]>([]);
  const [sales, setSales] = useState<Sale[]>([]);
  const [cart, setCart] = useState<CartItem[]>([]);
  const [search, setSearch] = useState("");
  const [customerName, setCustomerName] = useState("");
  const [paymentMethod, setPaymentMethod] = useState("cash");
  const [cashReceived, setCashReceived] = useState("");
  const [discount, setDiscount] = useState("");
  const [tax, setTax] = useState("");
  const [notes, setNotes] = useState("");
  const [moreOptions, setMoreOptions] = useState(false);
  const [modal, setModal] = useState<Modal>(null);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [receipt, setReceipt] = useState<Receipt | null>(null);
  const [newProduct, setNewProduct] = useState({ name: "", price: "", sku: "", stock: "", cost: "", category: "" });
  const [receive, setReceive] = useState({ productId: "", quantity: "", cost: "", supplierId: "", paymentStatus: "paid", payment: "", notes: "" });
  const [supplierForm, setSupplierForm] = useState({ id: "", name: "", phone: "", contactName: "" });

  async function loadShop() {
    const [catalog, supplierRows, purchaseRows, saleRows, categoryRows] = await Promise.all([
      fetchApi("/commerce/vendor/shop/catalog"), fetchApi("/commerce/vendor/shop/suppliers"),
      fetchApi("/commerce/vendor/shop/purchases"), fetchApi("/commerce/vendor/shop/sales"), fetchApi("/vendor/catalog/categories"),
    ]);
    setProducts(catalog as Product[]); setSuppliers(supplierRows as Supplier[]);
    setPurchases(purchaseRows as Purchase[]); setSales(saleRows as Sale[]);
    setCategories(categoryRows as Category[]);
  }
  useEffect(() => { loadShop().catch(() => setError("Shop could not be loaded. Please refresh and try again.")); }, []);

  const filtered = useMemo(() => { const term = search.trim().toLowerCase(); return !term ? products : products.filter((p) => `${p.name} ${p.sku || ""} ${p.barcode || ""}`.toLowerCase().includes(term)); }, [products, search]);
  const subtotal = useMemo(() => cart.reduce((sum, item) => sum + (item.sale_price_minor ?? item.regular_price_minor) * item.quantity, 0), [cart]);
  const total = Math.max(0, subtotal - toMinor(discount) + toMinor(tax));
  const received = toMinor(cashReceived);
  const change = Math.max(0, received - total);

  function printReceipt(bill: Receipt) {
    const printWindow = window.open("", "shop-bill", "width=420,height=640");
    if (!printWindow) { window.print(); return; }
    printWindow.document.write(`<!doctype html><html><head><title>Bill ${bill.order_number}</title><style>body{font-family:Arial,sans-serif;padding:24px;color:#111}h1{font-size:22px;margin:0 0 18px}p{margin:8px 0}.total{font-size:24px;font-weight:700;border-top:1px solid #111;padding-top:12px;margin-top:18px}</style></head><body><h1>Shop bill</h1><p>Bill number: <strong>${bill.order_number}</strong></p><p>Date: ${new Date().toLocaleString()}</p><p class="total">Total: ${money(bill.total_minor)}</p></body></html>`);
    printWindow.document.close(); printWindow.focus(); printWindow.print(); printWindow.close();
  }

  function startNewSale() { setCart([]); setCustomerName(""); setCashReceived(""); setDiscount(""); setTax(""); setNotes(""); setMessage(""); setError(""); setModal(null); }
  function add(product: Product) {
    const inCart = cart.find((item) => item.id === product.id)?.quantity || 0;
    if (inCart >= product.stock_quantity) { setError(`Only ${product.stock_quantity} available.`); return; }
    setCart((current) => current.some((item) => item.id === product.id) ? current.map((item) => item.id === product.id ? { ...item, quantity: item.quantity + 1 } : item) : [...current, { ...product, quantity: 1 }]); setError("");
  }
  function changeQuantity(product: Product, delta: number) {
    const current = cart.find((item) => item.id === product.id)?.quantity || 0;
    if (delta > 0 && current >= product.stock_quantity) { setError(`Only ${product.stock_quantity} available.`); return; }
    setCart((items) => items.map((item) => item.id === product.id ? { ...item, quantity: Math.max(0, item.quantity + delta) } : item).filter((item) => item.quantity > 0));
  }
  function scanKey(event: React.KeyboardEvent<HTMLInputElement>) { if (event.key !== "Enter") return; const code = search.trim().toLowerCase(); const exact = products.find((p) => p.sku?.toLowerCase() === code || p.barcode?.toLowerCase() === code); if (exact) { add(exact); setSearch(""); } }

  async function completeSale() {
    if (!cart.length) { setError("Add a product first."); return; }
    if (paymentMethod === "cash" && received < total) { setError(`Cash received must cover ${money(total)}.`); return; }
    setBusy(true); setError("");
    try {
      const sale = await fetchApi("/commerce/vendor/pos/sales", { method: "POST", body: JSON.stringify({
        customer_name: customerName || "Walk-in Customer", currency: "PKR", discount_minor: toMinor(discount), tax_minor: toMinor(tax), notes: notes || null,
        items: cart.map((item) => ({ product_id: item.id, quantity: item.quantity, unit_price_minor: item.sale_price_minor ?? item.regular_price_minor })),
        payments: [{ amount_minor: total, currency: "PKR", method: paymentMethod, status: "paid" }], idempotency_key: crypto.randomUUID(),
      }) }) as { id: string; order_number: string; total_minor: number };
      setReceipt({ id: sale.id, order_number: sale.order_number, total_minor: sale.total_minor }); setMessage("Sale complete!"); setCart([]); setCashReceived(""); setCustomerName(""); await loadShop();
    } catch (caught) { setError(caught instanceof Error ? caught.message : "Sale could not be completed."); } finally { setBusy(false); }
  }

  async function createProduct(event: React.FormEvent) {
    event.preventDefault(); setBusy(true); setError("");
    try {
      const created = await fetchApi("/vendor/catalog/products", { method: "POST", body: JSON.stringify({ name: newProduct.name, regular_price_minor: toMinor(newProduct.price), sku: newProduct.sku || null, barcode: newProduct.sku || null, category_id: newProduct.category || null, manage_stock: true, stock_status: "instock", visibility: "visible", metadata: newProduct.cost ? { purchase_cost_minor: toMinor(newProduct.cost) } : {} }) }) as { id: string };
      if (Number(newProduct.stock) > 0) await fetchApi("/commerce/vendor/shop/stock-in", { method: "POST", body: JSON.stringify({ product_id: created.id, quantity: Number(newProduct.stock), reason: "Opening shop stock" }) });
      setMessage("Product added to your shop. It is private online until you publish it."); setNewProduct({ name: "", price: "", sku: "", stock: "", cost: "", category: "" }); setModal(null); await loadShop();
    } catch (caught) { setError(caught instanceof Error ? caught.message : "Product could not be added."); } finally { setBusy(false); }
  }

  async function receiveStock(event: React.FormEvent) {
    event.preventDefault(); if (!receive.productId || !receive.supplierId) { setError("Choose a product and supplier."); return; }
    const totalCost = Number(receive.quantity || 0) * toMinor(receive.cost); const payment = receive.paymentStatus === "paid" ? totalCost : receive.paymentStatus === "unpaid" ? 0 : Math.min(totalCost, toMinor(receive.payment)); setBusy(true); setError("");
    try {
      const result = await fetchApi("/commerce/vendor/shop/purchases", { method: "POST", body: JSON.stringify({ supplier_id: receive.supplierId, payment_minor: payment, currency: "PKR", notes: receive.notes || null, items: [{ product_id: receive.productId, quantity: Number(receive.quantity), unit_cost_minor: toMinor(receive.cost) }] }) }) as { purchase_number: string };
      setMessage(`Stock received. Purchase ${result.purchase_number} saved.`); setReceive({ productId: "", quantity: "", cost: "", supplierId: "", paymentStatus: "paid", payment: "", notes: "" }); setModal(null); await loadShop();
    } catch (caught) { setError(caught instanceof Error ? caught.message : "Stock could not be received."); } finally { setBusy(false); }
  }

  async function saveSupplier(event: React.FormEvent) {
    event.preventDefault(); setBusy(true); setError("");
    try { const body = { name: supplierForm.name, phone: supplierForm.phone || null, contact_name: supplierForm.contactName || null }; await fetchApi(supplierForm.id ? `/commerce/vendor/shop/suppliers/${supplierForm.id}` : "/commerce/vendor/shop/suppliers", { method: supplierForm.id ? "PATCH" : "POST", body: JSON.stringify(body) }); setSupplierForm({ id: "", name: "", phone: "", contactName: "" }); await loadShop(); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "Supplier could not be saved."); } finally { setBusy(false); }
  }

  const modalTitle = modal === "new-product" ? "Add a product" : modal === "receive-stock" ? "Receive stock" : modal === "suppliers" ? "Suppliers" : modal === "purchases" ? "Purchases" : "Recent sales and bills";
  return <div className={styles.posShell}>
    <div className={styles.posTopBar}><div><div className={styles.eyebrow}>Your shop</div><h1 className={styles.pageTitle}>Shop POS</h1></div><div className={styles.posStockBadge}>Shop stock active</div></div>
    <nav className={styles.posActionBar} aria-label="Shop actions"><button className={`${styles.posActionButton} ${styles.posActionPrimary}`} onClick={startNewSale}>+ New Sale</button><button className={styles.posActionButton} onClick={() => setModal("new-product")}>+ New Product</button><button className={styles.posActionButton} onClick={() => setModal("receive-stock")}>Receive Stock</button><button className={styles.posActionButton} onClick={() => setModal("suppliers")}>Suppliers</button><button className={styles.posActionButton} onClick={() => setModal("purchases")}>Purchases</button><button className={styles.posActionButton} onClick={() => setModal("sales")}>Recent Sales</button><button className={styles.posActionButton} onClick={() => setModal("sales")}>Bills</button><a className={styles.posActionButton} href="/vendor/shop">Reports</a><a className={styles.posActionButton} href="/vendor/products">Online Store</a></nav>
    {message && <div className={styles.notice} role="status">{message}</div>}{error && <div className={styles.error} role="alert">{error}</div>}{receipt && <div className={styles.posSuccess}><strong>Bill {receipt.order_number}</strong><span>{money(receipt.total_minor)}</span><button className={styles.posSmallButton} onClick={() => printReceipt(receipt)}>Print Bill</button><button className={styles.posSmallButton} onClick={() => window.location.assign(`/vendor/orders?order=${receipt.id}`)}>View Bill</button><button className={styles.posSmallButton} onClick={startNewSale}>New Sale</button></div>}
    <div className={styles.posMainGrid}>
      <section className={styles.posCatalogPanel} aria-label="Products"><div className={styles.posPanelHeading}><div><h2 className={styles.panelTitle}>Choose a product</h2><p className={styles.muted}>Tap Add, or scan a barcode and press Enter.</p></div><input className={styles.posSearch} autoFocus aria-label="Search product name, SKU, or barcode" value={search} onChange={(event) => setSearch(event.target.value)} onKeyDown={scanKey} placeholder="Search products..." /></div><div className={styles.posProductGrid}>{filtered.map((product) => { const inCart = cart.find((item) => item.id === product.id)?.quantity || 0; const available = product.stock_quantity - inCart; return <article className={styles.posProductCard} key={product.id}><div className={styles.posProductCardInfo}><strong>{product.name}</strong><span>{product.sku || product.barcode || "No code"}</span></div><div className={styles.posProductMeta}><strong>{money(product.sale_price_minor ?? product.regular_price_minor)}</strong><span className={available <= 5 ? styles.posLowStock : ""}>{available} available{product.online_status === "published" ? " - Online" : ""}</span></div><button className={styles.posAddButton} disabled={available <= 0} onClick={() => add(product)}>{available > 0 ? "Add" : "Out"}</button></article>; })}{filtered.length === 0 && <div className={styles.empty}>No products found. Add a new product to begin.</div>}</div></section>
      <section className={styles.posCheckoutPanel} aria-label="Current sale"><div className={styles.posPanelHeading}><div><h2 className={styles.panelTitle}>Current sale</h2><p className={styles.muted}>{cart.reduce((sum, item) => sum + item.quantity, 0)} item(s)</p></div><button className={styles.posClearButton} onClick={() => setCart([])}>Clear sale</button></div><div className={styles.posCartList}>{cart.length === 0 ? <div className={styles.empty}>Your sale is empty.<br />Tap Add on a product.</div> : cart.map((item) => <div className={styles.posCartRow} key={item.id}><div><strong>{item.name}</strong><span>{money((item.sale_price_minor ?? item.regular_price_minor) * item.quantity)}</span></div><div className={styles.posQtyControls}><button className={styles.posQtyButton} onClick={() => changeQuantity(item, -1)} aria-label={`Remove one ${item.name}`}>-</button><strong>{item.quantity}</strong><button className={styles.posQtyButton} onClick={() => changeQuantity(item, 1)} aria-label={`Add one ${item.name}`}>+</button><button className={styles.posRemoveButton} onClick={() => setCart((rows) => rows.filter((row) => row.id !== item.id))}>Remove</button></div></div>)}</div><div className={styles.posTotals}><div><span>Items</span><strong>{cart.reduce((sum, item) => sum + item.quantity, 0)}</strong></div><div><span>Subtotal</span><strong>{money(subtotal)}</strong></div>{moreOptions && <><div><span>Discount</span><strong>- {money(toMinor(discount))}</strong></div><div><span>Tax</span><strong>+ {money(toMinor(tax))}</strong></div></>}<div className={styles.posGrandTotal}><span>Total</span><strong>{money(total)}</strong></div></div><div className={styles.posCheckoutForm}><label className={styles.posField}>Customer name<input value={customerName} onChange={(event) => setCustomerName(event.target.value)} placeholder="Walk-in customer" /></label><div className={styles.posPaymentGrid}>{["cash", "card", "bank", "cod"].map((method) => <button type="button" key={method} className={`${styles.posPaymentButton} ${paymentMethod === method ? styles.posPaymentSelected : ""}`} onClick={() => setPaymentMethod(method)}>{method === "cod" ? "COD" : method[0].toUpperCase() + method.slice(1)}</button>)}</div>{paymentMethod === "cash" && <div className={styles.posCashBox}><label className={styles.posField}>Cash received<input inputMode="decimal" value={cashReceived} onChange={(event) => setCashReceived(event.target.value)} placeholder="0.00" /></label><div><span>Change to return</span><strong>{money(change)}</strong></div></div>}<button className={styles.posMoreButton} onClick={() => setMoreOptions((value) => !value)}>{moreOptions ? "Hide options" : "More options"}</button>{moreOptions && <div className={styles.posMoreOptions}><label className={styles.posField}>Discount<input inputMode="decimal" value={discount} onChange={(event) => setDiscount(event.target.value)} placeholder="0.00" /></label><label className={styles.posField}>Tax<input inputMode="decimal" value={tax} onChange={(event) => setTax(event.target.value)} placeholder="0.00" /></label><label className={styles.posField}>Notes<textarea value={notes} onChange={(event) => setNotes(event.target.value)} rows={2} /></label></div>}<button className={styles.posCompleteButton} disabled={!cart.length || busy || (paymentMethod === "cash" && received < total)} onClick={completeSale}>{busy ? "Saving..." : "Complete Sale"}</button></div></section>
    </div><div className={styles.posMobileBar}><span>{cart.reduce((sum, item) => sum + item.quantity, 0)} items - {money(total)}</span><button className={styles.posCompleteButton} disabled={!cart.length} onClick={completeSale}>Complete Sale</button></div>

    {modal && <div className={styles.posModalBackdrop} role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setModal(null); }}><section className={styles.posModal} role="dialog" aria-modal="true" aria-label={modalTitle}><div className={styles.posModalHeader}><h2>{modalTitle}</h2><button className={styles.posCloseButton} onClick={() => setModal(null)} aria-label="Close">X</button></div>
      {modal === "new-product" && <form className={styles.posModalBody} onSubmit={createProduct}><label className={styles.posField}>Product name<input required value={newProduct.name} onChange={(event) => setNewProduct({ ...newProduct, name: event.target.value })} autoFocus /></label><div className={styles.posFormTwo}><label className={styles.posField}>Selling price<input required inputMode="decimal" value={newProduct.price} onChange={(event) => setNewProduct({ ...newProduct, price: event.target.value })} placeholder="0.00" /></label><label className={styles.posField}>Purchase cost (optional)<input inputMode="decimal" value={newProduct.cost} onChange={(event) => setNewProduct({ ...newProduct, cost: event.target.value })} placeholder="0.00" /></label></div><div className={styles.posFormTwo}><label className={styles.posField}>SKU / barcode (optional)<input value={newProduct.sku} onChange={(event) => setNewProduct({ ...newProduct, sku: event.target.value })} /></label><label className={styles.posField}>Category (optional)<select value={newProduct.category} onChange={(event) => setNewProduct({ ...newProduct, category: event.target.value })}><option value="">No category</option>{categories.map((category) => <option key={category.id} value={category.id}>{category.name}</option>)}</select></label></div><label className={styles.posField}>Opening stock (optional)<input inputMode="numeric" value={newProduct.stock} onChange={(event) => setNewProduct({ ...newProduct, stock: event.target.value })} /></label><p className={styles.posHint}>This product stays private online until you publish it.</p><div className={styles.posModalActions}><button className={styles.posCompleteButton} disabled={busy}>{busy ? "Saving..." : "Add Product"}</button><a className={styles.posLinkButton} href="/vendor/products">Edit full product</a></div></form>}
      {modal === "receive-stock" && <form className={styles.posModalBody} onSubmit={receiveStock}><label className={styles.posField}>Product<select required value={receive.productId} onChange={(event) => setReceive({ ...receive, productId: event.target.value })}><option value="">Choose product</option>{products.map((product) => <option key={product.id} value={product.id}>{product.name}</option>)}</select></label><div className={styles.posFormTwo}><label className={styles.posField}>Quantity<input required type="number" min="1" value={receive.quantity} onChange={(event) => setReceive({ ...receive, quantity: event.target.value })} /></label><label className={styles.posField}>Unit cost<input required inputMode="decimal" value={receive.cost} onChange={(event) => setReceive({ ...receive, cost: event.target.value })} placeholder="0.00" /></label></div><label className={styles.posField}>Supplier<select required value={receive.supplierId} onChange={(event) => setReceive({ ...receive, supplierId: event.target.value })}><option value="">Choose supplier</option>{suppliers.map((supplier) => <option key={supplier.id} value={supplier.id}>{supplier.name}</option>)}</select></label><div className={styles.posPaymentGrid}>{["paid", "partial", "unpaid"].map((status) => <button type="button" key={status} className={`${styles.posPaymentButton} ${receive.paymentStatus === status ? styles.posPaymentSelected : ""}`} onClick={() => setReceive({ ...receive, paymentStatus: status })}>{status[0].toUpperCase() + status.slice(1)}</button>)}</div>{receive.paymentStatus === "partial" && <label className={styles.posField}>Payment amount<input inputMode="decimal" value={receive.payment} onChange={(event) => setReceive({ ...receive, payment: event.target.value })} /></label>}<label className={styles.posField}>Notes<textarea value={receive.notes} onChange={(event) => setReceive({ ...receive, notes: event.target.value })} rows={2} /></label><div className={styles.posModalActions}><button className={styles.posCompleteButton} disabled={busy}>{busy ? "Saving..." : "Receive Stock"}</button></div></form>}
      {modal === "suppliers" && <div className={styles.posModalBody}><form onSubmit={saveSupplier} className={styles.posInlineForm}><input required placeholder="Supplier name" value={supplierForm.name} onChange={(event) => setSupplierForm({ ...supplierForm, name: event.target.value })} /><input placeholder="Phone" value={supplierForm.phone} onChange={(event) => setSupplierForm({ ...supplierForm, phone: event.target.value })} /><button className={styles.posSmallButton}>{supplierForm.id ? "Save" : "Add supplier"}</button></form><div className={styles.posSimpleList}>{suppliers.length === 0 ? <p className={styles.empty}>No suppliers yet.</p> : suppliers.map((supplier) => <div className={styles.posSimpleRow} key={supplier.id}><div><strong>{supplier.name}</strong><span>{supplier.phone || "No phone"}</span><span>Outstanding: {money(supplier.outstanding_minor || 0)}</span></div><button className={styles.posSmallButton} onClick={() => setSupplierForm({ id: supplier.id, name: supplier.name, phone: supplier.phone || "", contactName: supplier.contact_name || "" })}>Edit</button></div>)}</div></div>}
      {modal === "purchases" && <div className={styles.posModalBody}><div className={styles.posSimpleList}>{purchases.length === 0 ? <p className={styles.empty}>No purchases yet.</p> : purchases.map((purchase) => <div className={styles.posSimpleRow} key={purchase.id}><div><strong>{purchase.purchase_number}</strong><span>{new Date(purchase.created_at).toLocaleString()}</span></div><div><strong>{money(purchase.total_minor)}</strong><span>{purchase.payment_status}</span></div></div>)}</div><a className={styles.posLinkButton} href="/vendor/shop">Open full shop reports</a></div>}
      {modal === "sales" && <div className={styles.posModalBody}><div className={styles.posSimpleList}>{sales.length === 0 ? <p className={styles.empty}>No sales yet.</p> : sales.map((sale) => <div className={styles.posSimpleRow} key={sale.id}><div><strong>{sale.bill_number}</strong><span>{sale.customer} · {new Date(sale.created_at).toLocaleString()}</span></div><div><strong>{money(sale.total_minor)}</strong><span>{sale.payment_method}</span></div><button className={styles.posSmallButton} onClick={() => window.location.assign(`/vendor/orders?order=${sale.id}`)}>View</button><button className={styles.posSmallButton} onClick={() => printReceipt({ id: sale.id, order_number: sale.bill_number, total_minor: sale.total_minor })}>Print</button></div>)}</div></div>}
    </section></div>}
  </div>;
}
