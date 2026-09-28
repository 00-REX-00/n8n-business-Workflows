// Build the invoice as an HTML page and hand it on as a file called
// index.html - that is the file name Gotenberg expects.
const o = $('Normalize Order').first().json;
const money = (n) => `${Number(n).toFixed(2)} ${o.currency}`;
const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

const html = `<!doctype html>
<html><head><meta charset="utf-8"><style>
  body { font-family: Helvetica, Arial, sans-serif; color: #222; margin: 40px; }
  h1 { margin: 0; font-size: 28px; }
  .muted { color: #777; }
  .head { display: flex; justify-content: space-between; margin-bottom: 40px; }
  table { width: 100%; border-collapse: collapse; margin-top: 24px; }
  th, td { text-align: left; padding: 10px; border-bottom: 1px solid #ddd; }
  th:last-child, td:last-child { text-align: right; }
  .total td { font-weight: bold; border-bottom: none; font-size: 18px; }
</style></head><body>
  <div class="head">
    <div><h1>INVOICE</h1><div class="muted">${esc(o.order_number)}</div></div>
    <div style="text-align:right"><b>Demo Store</b><br>hello@demostore.test</div>
  </div>
  <p><b>Billed to:</b><br>${esc(o.customer_name)}<br>${esc(o.customer_email)}</p>
  <p><b>Date:</b> ${o.created_at.slice(0, 10)}<br><b>Status:</b> PAID (Stripe ${esc(o.order_id)})</p>
  <table>
    <tr><th>Item</th><th>SKU</th><th>Qty</th><th>Unit price</th><th>Amount</th></tr>
    <tr><td>${esc(o.product_name)}</td><td>${esc(o.sku)}</td><td>${o.quantity}</td>
        <td>${money(o.unit_price)}</td><td>${money(o.unit_price * o.quantity)}</td></tr>
    <tr class="total"><td colspan="4">Total paid</td><td>${money(o.amount_total)}</td></tr>
  </table>
  <p class="muted" style="margin-top:40px">Thank you for your order!</p>
</body></html>`;

return [{
  json: { order_number: o.order_number },
  binary: {
    data: {
      data: Buffer.from(html).toString('base64'),
      mimeType: 'text/html',
      fileName: 'index.html',
    },
  },
}];
