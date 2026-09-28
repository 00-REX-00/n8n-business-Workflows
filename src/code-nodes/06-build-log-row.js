// Every path (fulfilled, needs attention, failed) ends here, so each order
// gets exactly one row in the Orders sheet with its final status.
const ran = (name) => { try { return $(name).isExecuted; } catch { return false; } };

const event = $('Extract Event').first().json;
const order = ran('Normalize Order') ? $('Normalize Order').first().json : {};
const outcome = $json;

return [{
  json: {
    order_id: order.order_id || event.session_id,
    order_number: order.order_number || '',
    status: outcome.status,
    failed_step: outcome.failed_step || '',
    reason: outcome.reason || '',
    action: outcome.action || '',
    customer_name: order.customer_name || '',
    customer_email: order.customer_email || '',
    sku: order.sku || '',
    product_name: order.product_name || '',
    quantity: order.quantity ?? '',
    amount_total: order.amount_total ?? '',
    currency: order.currency || '',
    stripe_event_id: event.event_id,
    created_at: order.created_at || '',
    updated_at: new Date().toISOString(),
    execution_id: $execution.id,
  },
}];
