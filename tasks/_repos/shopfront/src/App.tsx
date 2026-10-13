import { useState } from "react";
import { addItem, type Cart, type DiscountCode, removeItem, setQuantity } from "./cart";
import { CartView } from "./components/CartView";
import { ProductList } from "./components/ProductList";
import { CATALOG, type Product } from "./products";

export function App({ products = CATALOG }: { products?: readonly Product[] }) {
  const [cart, setCart] = useState<Cart>([]);
  const [code, setCode] = useState<DiscountCode | null>(null);

  return (
    <main>
      <h1>Shopfront</h1>
      <ProductList products={products} onAdd={(id) => setCart((c) => addItem(c, id))} />
      <CartView
        cart={cart}
        products={products}
        code={code}
        onQuantity={(id, quantity) => setCart((c) => setQuantity(c, id, quantity))}
        onRemove={(id) => setCart((c) => removeItem(c, id))}
        onCode={setCode}
      />
    </main>
  );
}
