import { fetchApi } from './api';

export type ProductType = 'simple' | 'variable' | 'digital' | 'service';
export type ProductStatus = 'draft' | 'active' | 'archived';

export interface Product {
  id: string;
  company_id: string;
  category_id?: string | null;
  brand_id?: string | null;
  vendor_id?: string | null;
  category_ids: string[];
  name: string;
  slug: string;
  sku: string | null;
  barcode: string | null;
  product_type: ProductType;
  status: ProductStatus;
  description: string | null;
  short_description: string | null;
  seo_title: string | null;
  seo_description: string | null;
  visibility: string;
  featured: boolean;
  global_unique_id?: string | null;
  regular_price_minor: number;
  stock_quantity?: number | null;
}

export interface ProductCreate {
  name: string;
  slug: string;
  sku?: string;
  barcode?: string;
  product_type: ProductType;
  status: ProductStatus;
  regular_price_minor: number;
}

export async function getProducts(): Promise<Product[]> {
  const data = await fetchApi('/catalog/products');
  return data as Product[];
}

export async function getProduct(id: string): Promise<Product> {
  const data = await fetchApi(`/catalog/products/${id}`);
  return data as Product;
}

export async function createProduct(payload: ProductCreate): Promise<Product> {
  const data = await fetchApi('/catalog/products', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
  return data as Product;
}

export async function updateProduct(id: string, payload: Partial<ProductCreate>): Promise<Product> {
  const data = await fetchApi(`/catalog/products/${id}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  });
  return data as Product;
}

export async function deleteProduct(id: string): Promise<void> {
  await fetchApi(`/catalog/products/${id}`, {
    method: 'DELETE',
  });
}
