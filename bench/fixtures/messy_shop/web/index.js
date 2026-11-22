import { calculateCartTotal } from "./helpers.js";
import { formatCurrency } from "./misc/file2";
import { validateCouponCode } from "./misc/stuff";

export function renderCheckout(items, code) {
  const total = calculateCartTotal(items);
  if (!validateCouponCode(code)) {
    return formatCurrency(total, "USD");
  }
  return formatCurrency(total, "USD");
}
