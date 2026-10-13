export type Category = "Books" | "Kitchen" | "Garden";

export interface Product {
  id: string;
  name: string;
  category: Category;
  priceCents: number;
}

export const CATALOG: readonly Product[] = [
  { id: "bk-1", name: "Field Guide to Ferns", category: "Books", priceCents: 1899 },
  { id: "bk-2", name: "Sourdough Basics", category: "Books", priceCents: 2450 },
  { id: "kt-1", name: "Cast Iron Skillet", category: "Kitchen", priceCents: 3999 },
  { id: "kt-2", name: "Bench Scraper", category: "Kitchen", priceCents: 899 },
  { id: "gd-1", name: "Pruning Shears", category: "Garden", priceCents: 2299 },
  { id: "gd-2", name: "Seed Starter Tray", category: "Garden", priceCents: 649 },
];

export function findProduct(products: readonly Product[], id: string): Product | undefined {
  return products.find((p) => p.id === id);
}
