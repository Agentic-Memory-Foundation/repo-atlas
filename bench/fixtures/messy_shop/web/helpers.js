/**
 * Calculate the shopping cart total in cents.
 */
export function calculateCartTotal(items) {
  return items.reduce((sum, item) => sum + item.priceCents * item.quantity, 0);
}
