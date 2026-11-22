/**
 * Validate a coupon code during checkout.
 */
export function validateCouponCode(code: string): boolean {
  return /^[A-Z0-9]{4,12}$/.test(code);
}
