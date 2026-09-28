// Decide if we can fulfil the order from the Inventory sheet.
// Anything odd (unknown SKU, duplicate rows, non-numeric stock) is treated
// as "needs a human" - never as "probably fine".
const order = $('Normalize Order').first().json;
const rows = $input.all().map((i) => i.json).filter((r) => r.sku);

const notOk = (reason) => [{ json: { in_stock: false, reason } }];

if (rows.length === 0) return notOk(`SKU "${order.sku}" is not in the Inventory sheet`);
if (rows.length > 1) return notOk(`SKU "${order.sku}" appears ${rows.length} times in the Inventory sheet`);

const row = rows[0];
const stock = Number(row.stock);
const reorderLevel = Number(row.reorder_level) || 0;

if (row.stock === '' || !Number.isFinite(stock)) {
  return notOk(`Stock value "${row.stock}" for ${order.sku} is not a number`);
}
if (stock < order.quantity) {
  return notOk(`Out of stock: only ${stock} x ${order.sku} left, customer paid for ${order.quantity}`);
}

const newStock = stock - order.quantity;
return [{
  json: {
    in_stock: true,
    sku: order.sku,
    stock_before: stock,
    new_stock: newStock,
    reorder_level: reorderLevel,
    low_stock: newStock <= reorderLevel,
  },
}];
