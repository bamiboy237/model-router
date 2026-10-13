import { formatCents } from "../money";
import type { Product } from "../products";

interface Props {
  products: readonly Product[];
  onAdd: (productId: string) => void;
}

export function ProductList({ products, onAdd }: Props) {
  return (
    <section aria-label="Products">
      <h2>Products</h2>
      <ul>
        {products.map((product) => (
          <li key={product.id} data-testid="product">
            <span>{product.name}</span> <span>{formatCents(product.priceCents)}</span>{" "}
            <button type="button" onClick={() => onAdd(product.id)}>
              Add {product.name} to cart
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
