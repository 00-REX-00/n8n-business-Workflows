// Turn the Stripe checkout session into one clean "order" object
// and list every problem that means a human must look at it.
const session = $json;
const event = $('Extract Event').first().json;

const lineItems = session.line_items?.data ?? [];
const item = lineItems[0];
const product = item?.price?.product ?? {};

const rawEmail = session.customer_details?.email ?? session.customer_email ?? '';
const email = String(rawEmail).trim().toLowerCase();
const emailLooksValid = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(email);

const issues = [];
if (session.payment_status !== 'paid') issues.push(`Payment status is "${session.payment_status}", not "paid"`);
if (!item) issues.push('Order has no line items');
if (lineItems.length > 1) issues.push('Order has more than one product - only single-product orders are automated');
if (!product.metadata?.sku) issues.push(`Stripe product "${product.name ?? 'unknown'}" has no "sku" in its metadata`);
if (!emailLooksValid) issues.push(`Customer email "${rawEmail}" is missing or badly formatted`);

return [{
  json: {
    order_id: session.id,
    order_number: 'INV-' + String(session.id).slice(-8).toUpperCase(),
    stripe_event_id: event.event_id,
    created_at: new Date((session.created ?? Date.now() / 1000) * 1000).toISOString(),
    customer_name: session.customer_details?.name ?? '',
    customer_email: email,
    sku: product.metadata?.sku ?? '',
    product_name: product.name ?? item?.description ?? '',
    quantity: item?.quantity ?? 0,
    unit_price: (item?.price?.unit_amount ?? 0) / 100,
    amount_total: (session.amount_total ?? 0) / 100,
    currency: String(session.currency ?? '').toUpperCase(),
    valid: issues.length === 0,
    issues: issues.join(' | '),
  },
}];
