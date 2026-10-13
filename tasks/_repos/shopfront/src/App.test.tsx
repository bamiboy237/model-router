import { fireEvent, render, screen, within } from "@testing-library/react";
import { App } from "./App";

describe("App", () => {
  it("shows an empty cart at first", () => {
    render(<App />);
    expect(screen.getByText("Your cart is empty.")).toBeTruthy();
    expect(screen.getByTestId("total").textContent).toBe("$0.00");
  });

  it("adds products and totals them", () => {
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "Add Field Guide to Ferns to cart" }));
    fireEvent.click(screen.getByRole("button", { name: "Add Bench Scraper to cart" }));
    const cart = screen.getByRole("region", { name: "Cart" });
    expect(within(cart).getAllByTestId("cart-line")).toHaveLength(2);
    expect(screen.getByTestId("subtotal").textContent).toBe("$27.98");
  });

  it("applies a discount code", () => {
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "Add Cast Iron Skillet to cart" }));
    fireEvent.change(screen.getByLabelText("Discount code"), { target: { value: "fiveoff" } });
    fireEvent.click(screen.getByRole("button", { name: "Apply" }));
    expect(screen.getByTestId("discount").textContent).toBe("$5.00");
    expect(screen.getByTestId("total").textContent).toBe("$34.99");
  });

  it("rejects an unknown code", () => {
    render(<App />);
    fireEvent.change(screen.getByLabelText("Discount code"), { target: { value: "FREE" } });
    fireEvent.click(screen.getByRole("button", { name: "Apply" }));
    expect(screen.getByRole("alert").textContent).toBe('"FREE" is not a valid code.');
  });
});
