import { findProduct, type Product } from "./products";

export interface CartLine {
  productId: string;
  quantity: number;
}

export type Cart = readonly CartLine[];

export interface Totals {
  subtotalCents: number;
  discountCents: number;
  totalCents: number;
}

export const DISCOUNT_CODES = {
  SAVE10: "10% off the whole order",
  FIVEOFF: "$5 off orders of $25 or more",
} as const;

export type DiscountCode = keyof typeof DISCOUNT_CODES;

const FIVEOFF_MINIMUM_CENTS = 2500;

export function addItem(cart: Cart, productId: string, quantity = 1): Cart {
  if (cart.some((line) => line.productId === productId)) {
    return cart.map((line) =>
      line.productId === productId ? { ...line, quantity: line.quantity + quantity } : line,
    );
  }
  return [...cart, { productId, quantity }];
}

export function removeItem(cart: Cart, productId: string): Cart {
  return cart.filter((line) => line.productId !== productId);
}

/** Set a line's quantity. Zero or less removes the line. */
export function setQuantity(cart: Cart, productId: string, quantity: number): Cart {
  if (quantity <= 0) {
    return removeItem(cart, productId);
  }
  return cart.map((line) => (line.productId === productId ? { ...line, quantity } : line));
}

export function itemCount(cart: Cart): number {
  return cart.reduce((sum, line) => sum + line.quantity, 0);
}

export function parseDiscountCode(input: string): DiscountCode | null {
  const code = input.trim().toUpperCase();
  return code in DISCOUNT_CODES ? (code as DiscountCode) : null;
}

export function discountFor(subtotalCents: number, code: DiscountCode | null): number {
  switch (code) {
    case "SAVE10":
      return Math.round(subtotalCents / 10);
    case "FIVEOFF":
      return subtotalCents >= FIVEOFF_MINIMUM_CENTS ? 500 : 0;
    default:
      return 0;
  }
}

export function totals(
  cart: Cart,
  products: readonly Product[],
  code: DiscountCode | null = null,
): Totals {
  const subtotalCents = cart.reduce((sum, line) => {
    const product = findProduct(products, line.productId);
    return product ? sum + product.priceCents * line.quantity : sum;
  }, 0);
  const discountCents = discountFor(subtotalCents, code);
  return { subtotalCents, discountCents, totalCents: subtotalCents - discountCents };
}
