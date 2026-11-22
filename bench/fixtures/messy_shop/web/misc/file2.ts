/**
 * Format a currency amount in cents for checkout display.
 */
export function formatCurrency(cents: number, currency: string): string {
  return new Intl.NumberFormat("en-US", { style: "currency", currency }).format(cents / 100);
}
