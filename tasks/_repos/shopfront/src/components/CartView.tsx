import { useState } from "react";
import { type Cart, type DiscountCode, itemCount, parseDiscountCode, totals } from "../cart";
import { formatCents } from "../money";
import { findProduct, type Product } from "../products";

interface Props {
  cart: Cart;
  products: readonly Product[];
  code: DiscountCode | null;
  onQuantity: (productId: string, quantity: number) => void;
  onRemove: (productId: string) => void;
  onCode: (code: DiscountCode | null) => void;
}

export function CartView({ cart, products, code, onQuantity, onRemove, onCode }: Props) {
  const [codeInput, setCodeInput] = useState("");
  const [codeError, setCodeError] = useState<string | null>(null);
  const sums = totals(cart, products, code);

  function applyCode() {
    const parsed = parseDiscountCode(codeInput);
    setCodeError(parsed ? null : `"${codeInput}" is not a valid code.`);
    onCode(parsed);
  }

  return (
    <section aria-label="Cart">
      <h2>Cart ({itemCount(cart)})</h2>
      {cart.length === 0 ? (
        <p>Your cart is empty.</p>
      ) : (
        <ul>
          {cart.map((line) => {
            const product = findProduct(products, line.productId);
            if (!product) return null;
            return (
              <li key={line.productId} data-testid="cart-line">
                <span>{product.name}</span>{" "}
                <input
                  type="number"
                  min={0}
                  aria-label={`Quantity of ${product.name}`}
                  value={line.quantity}
                  onChange={(e) => onQuantity(line.productId, Number(e.target.value))}
                />{" "}
                <span>{formatCents(product.priceCents * line.quantity)}</span>{" "}
                <button type="button" onClick={() => onRemove(line.productId)}>
                  Remove {product.name}
                </button>
              </li>
            );
          })}
        </ul>
      )}
      <label>
        Discount code{" "}
        <input value={codeInput} onChange={(e) => setCodeInput(e.target.value)} />
      </label>{" "}
      <button type="button" onClick={applyCode}>
        Apply
      </button>
      {codeError && <p role="alert">{codeError}</p>}
      <dl>
        <dt>Subtotal</dt>
        <dd data-testid="subtotal">{formatCents(sums.subtotalCents)}</dd>
        <dt>Discount</dt>
        <dd data-testid="discount">{formatCents(sums.discountCents)}</dd>
        <dt>Total</dt>
        <dd data-testid="total">{formatCents(sums.totalCents)}</dd>
      </dl>
    </section>
  );
}
