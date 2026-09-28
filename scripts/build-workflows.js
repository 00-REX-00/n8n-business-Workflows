#!/usr/bin/env node
// Builds the n8n workflow JSON files in workflows/ from the Code-node sources
// in src/code-nodes/. Run: node scripts/build-workflows.js
//
// Optional: fill in your own IDs so the output is ready to paste:
//   SHEET_ID=1AbC... TELEGRAM_CHAT_ID=123456 node scripts/build-workflows.js

const fs = require('fs');
const path = require('path');

const root = path.join(__dirname, '..');
const code = (file) => fs.readFileSync(path.join(root, 'src/code-nodes', file), 'utf8').trim();

const SHEET_ID = process.env.SHEET_ID || 'YOUR_GOOGLE_SHEET_ID';
const CHAT_ID = process.env.TELEGRAM_CHAT_ID || 'YOUR_TELEGRAM_CHAT_ID';
const GOTENBERG_URL = process.env.GOTENBERG_URL || 'http://gotenberg:3000/forms/chromium/convert/html';

let idCounter = 0;
const uid = () => `0f1d2c3b-4a59-4e6f-8a7b-${String(++idCounter).padStart(12, '0')}`;

// ---------- node helpers ----------
const node = (name, type, typeVersion, position, parameters, extra = {}) =>
  ({ parameters, id: uid(), name, type, typeVersion, position, ...extra });

const retry = (maxTries = 3, waitBetweenTries = 2000) => ({ retryOnFail: true, maxTries, waitBetweenTries });
const catchErrors = { onError: 'continueErrorOutput' };

const codeNode = (name, position, file, extra) =>
  node(name, 'n8n-nodes-base.code', 2, position, { jsCode: code(file) }, extra);

const setNode = (name, position, fields) => node(name, 'n8n-nodes-base.set', 3.4, position, {
  assignments: {
    assignments: Object.entries(fields).map(([k, v]) => ({
      id: uid(), name: k, value: v, type: typeof v === 'number' ? 'number' : 'string',
    })),
  },
  options: {},
});

const ifNode = (name, position, leftValue, operator, rightValue = '') => node(name, 'n8n-nodes-base.if', 2.2, position, {
  conditions: {
    options: { caseSensitive: true, leftValue: '', typeValidation: 'loose', version: 2 },
    conditions: [{ id: uid(), leftValue, rightValue, operator }],
    combinator: 'and',
  },
  looseTypeValidation: true,
  options: {},
});
const op = {
  isTrue: { type: 'boolean', operation: 'true', singleValue: true },
  notEmpty: { type: 'string', operation: 'notEmpty', singleValue: true },
  equals: { type: 'string', operation: 'equals' },
  notEquals: { type: 'string', operation: 'notEquals' },
};

const sheetRef = (sheetName) => ({
  documentId: { __rl: true, value: SHEET_ID, mode: 'id' },
  sheetName: { __rl: true, value: sheetName, mode: 'name' },
});
const sheetsNode = (name, position, parameters, extra) =>
  node(name, 'n8n-nodes-base.googleSheets', 4.5, position, parameters, extra);
const schemaCol = (id) => ({
  id, displayName: id, required: false, defaultMatch: false, display: true, type: 'string', canBeUsedToMatch: true,
});

const telegram = (name, position, text, extra) => node(name, 'n8n-nodes-base.telegram', 1.2, position, {
  chatId: CHAT_ID,
  text,
  additionalFields: { appendAttribution: false },
}, extra);

const sticky = (name, position, width, height, content, color) =>
  node(name, 'n8n-nodes-base.stickyNote', 1, position, { content, width, height, color });

const N = "$('Normalize Order').first().json";

// ---------- main workflow ----------
const nodes = [
  sticky('Note: 1 Event', [-60, 80], 700, 560,
    '## 1. The event\nStripe calls this webhook when a checkout is paid. Nobody clicks anything.\n\nFailure plan: Stripe re-sends automatically for up to 3 days if n8n is down.', 7),
  sticky('Note: 2 Verify', [660, -120], 1100, 760,
    "## 2. Verify, dedupe, claim\nDon't trust the webhook body - fetch the order from Stripe. Skip if we've already seen this order. Write a \"processing\" row straight away so nothing is invisible.\n\nFailure plan: retry 3x (network blips), then alert a human.", 5),
  sticky('Note: 3 Stock', [1960, -120], 1120, 760,
    "## 3. Inventory\nValidate the order, check stock, reserve it.\n\nOut of stock / bad data is NOT retried - a human decides (restock or refund).", 6),
  sticky('Note: 4 Invoice', [3060, -160], 820, 800,
    '## 4. Invoice + email\nHTML -> PDF (Gotenberg) -> email with attachment.\n\nFailure plan: retry 3x with a pause, then alert a human.', 4),
  sticky('Note: 5 Outcome', [2800, 720], 1860, 380,
    '## 5. Every path ends in ONE place\nfulfilled / needs_attention / failed -> one row in the Orders sheet. Anything not fulfilled -> Telegram alert with order, step, reason and what to do.', 3),

  node('Stripe Webhook', 'n8n-nodes-base.webhook', 2, [0, 300],
    { httpMethod: 'POST', path: 'stripe-order', options: {} },
    { webhookId: '7c1e5a90-3b2d-4f6e-9a8c-5712order0001' }),
  codeNode('Extract Event', [220, 300], '01-extract-event.js'),
  ifNode('Is Checkout Paid Event?', [440, 300], '={{ $json.event_type }}', op.equals, 'checkout.session.completed'),
  node('Ignore Other Events', 'n8n-nodes-base.noOp', 1, [660, 500], {}),

  node('Fetch Session from Stripe', 'n8n-nodes-base.httpRequest', 4.2, [700, 300], {
    url: '=https://api.stripe.com/v1/checkout/sessions/{{ $json.session_id }}',
    authentication: 'predefinedCredentialType',
    nodeCredentialType: 'stripeApi',
    sendQuery: true,
    queryParameters: { parameters: [{ name: 'expand[]', value: 'line_items.data.price.product' }] },
    options: {},
  }, { ...retry(), ...catchErrors }),
  codeNode('Normalize Order', [920, 280], '02-normalize-order.js'),

  sheetsNode('Find Existing Order', [1140, 280], {
    operation: 'read',
    ...sheetRef('Orders'),
    filtersUI: { values: [{ lookupColumn: 'order_id', lookupValue: '={{ $json.order_id }}' }] },
    options: {},
  }, { alwaysOutputData: true, ...retry(), ...catchErrors }),
  ifNode('Already Processed?', [1360, 280], '={{ $json.order_id }}', op.notEmpty),
  node('Duplicate - Stop Here', 'n8n-nodes-base.noOp', 1, [1580, 80], {}),

  setNode('Processing Row', [1580, 300], {
    order_id: `={{ ${N}.order_id }}`,
    order_number: `={{ ${N}.order_number }}`,
    status: 'processing',
    customer_name: `={{ ${N}.customer_name }}`,
    customer_email: `={{ ${N}.customer_email }}`,
    sku: `={{ ${N}.sku }}`,
    product_name: `={{ ${N}.product_name }}`,
    quantity: `={{ ${N}.quantity }}`,
    amount_total: `={{ ${N}.amount_total }}`,
    currency: `={{ ${N}.currency }}`,
    stripe_event_id: `={{ ${N}.stripe_event_id }}`,
    created_at: `={{ ${N}.created_at }}`,
    updated_at: '={{ $now.toISO() }}',
    execution_id: '={{ $execution.id }}',
  }),
  sheetsNode('Claim Order', [1800, 300], {
    operation: 'appendOrUpdate',
    ...sheetRef('Orders'),
    columns: { mappingMode: 'autoMapInputData', value: {}, matchingColumns: ['order_id'], schema: [] },
    options: {},
  }, { ...retry(), ...catchErrors }),

  ifNode('Order Valid?', [2020, 280], `={{ ${N}.valid }}`, op.isTrue),
  setNode('Flag: Invalid Order', [2240, 520], {
    status: 'needs_attention',
    failed_step: 'Validate order',
    reason: `={{ ${N}.issues }}`,
    action: 'Check the payment in the Stripe dashboard, fix the data (e.g. product sku), then contact the customer.',
  }),

  sheetsNode('Look Up Stock', [2240, 260], {
    operation: 'read',
    ...sheetRef('Inventory'),
    filtersUI: { values: [{ lookupColumn: 'sku', lookupValue: `={{ ${N}.sku }}` }] },
    options: {},
  }, { alwaysOutputData: true, ...retry(), ...catchErrors }),
  codeNode('Check Stock', [2460, 260], '03-check-stock.js'),
  ifNode('In Stock?', [2680, 260], '={{ $json.in_stock }}', op.isTrue),
  setNode('Flag: Out of Stock', [2900, 520], {
    status: 'needs_attention',
    failed_step: 'Inventory check',
    reason: '={{ $json.reason }}',
    action: 'Payment was taken but nothing was shipped. Restock and fulfil, or refund in Stripe and email the customer.',
  }),

  sheetsNode('Reserve Stock', [2900, 240], {
    operation: 'update',
    ...sheetRef('Inventory'),
    columns: {
      mappingMode: 'defineBelow',
      value: { sku: '={{ $json.sku }}', stock: '={{ $json.new_stock }}' },
      matchingColumns: ['sku'],
      schema: [schemaCol('sku'), schemaCol('stock')],
    },
    options: {},
  }, { ...retry(), ...catchErrors }),

  ifNode('Low Stock?', [3120, 20], "={{ $('Check Stock').first().json.low_stock }}", op.isTrue),
  telegram('Low Stock Warning', [3340, 0],
    "=⚠️ Low stock warning\n\n{{ $('Check Stock').first().json.sku }} is down to {{ $('Check Stock').first().json.new_stock }} (reorder level {{ $('Check Stock').first().json.reorder_level }}).\nTime to reorder.",
    { ...retry(), onError: 'continueRegularOutput' }),

  codeNode('Build Invoice HTML', [3120, 240], '04-build-invoice-html.js'),
  node('Render Invoice PDF', 'n8n-nodes-base.httpRequest', 4.2, [3340, 240], {
    method: 'POST',
    url: GOTENBERG_URL,
    sendHeaders: true,
    headerParameters: { parameters: [{ name: 'Gotenberg-Output-Filename', value: "={{ $json.order_number }}" }] },
    sendBody: true,
    contentType: 'multipart-form-data',
    bodyParameters: { parameters: [{ parameterType: 'formBinaryData', name: 'files', inputDataFieldName: 'data' }] },
    options: { response: { response: { responseFormat: 'file', outputPropertyName: 'data' } } },
  }, { ...retry(), ...catchErrors }),
  node('Email Customer', 'n8n-nodes-base.gmail', 2.1, [3560, 240], {
    sendTo: `={{ ${N}.customer_email }}`,
    subject: `=Your order {{ ${N}.order_number }} is confirmed`,
    message: `=<p>Hi {{ ${N}.customer_name || 'there' }},</p>
<p>Thanks for your order! We've received your payment of <b>{{ ${N}.amount_total }} {{ ${N}.currency }}</b> for
<b>{{ ${N}.quantity }} x {{ ${N}.product_name }}</b>.</p>
<p>Your invoice <b>{{ ${N}.order_number }}</b> is attached. We'll let you know when it ships.</p>
<p>Demo Store</p>`,
    options: { appendAttribution: false, attachmentsUi: { attachmentsBinary: [{ property: 'data' }] } },
  }, { ...retry(3, 5000), ...catchErrors }),
  setNode('Mark Fulfilled', [3780, 240], { status: 'fulfilled', failed_step: '', reason: '', action: '' }),

  codeNode('Describe Failure', [3340, 880], '05-describe-failure.js'),
  codeNode('Build Log Row', [4000, 520], '06-build-log-row.js'),
  ifNode('Needs Human?', [4220, 420], '={{ $json.status }}', op.notEquals, 'fulfilled'),
  telegram('Alert Human', [4440, 400],
    `=🚨 Order needs attention

Order: {{ $json.order_number || '-' }}
Stripe session: {{ $json.order_id }}
Customer: {{ $json.customer_name }} <{{ $json.customer_email }}>
Item: {{ $json.quantity }} x {{ $json.product_name }} ({{ $json.sku }})
Paid: {{ $json.amount_total }} {{ $json.currency }}

Status: {{ $json.status }}
Failed step: {{ $json.failed_step }}
Why: {{ $json.reason }}

What to do: {{ $json.action }}

n8n execution: {{ $json.execution_id }}`,
    retry()),
  sheetsNode('Update Order Log', [4220, 640], {
    operation: 'appendOrUpdate',
    ...sheetRef('Orders'),
    columns: { mappingMode: 'autoMapInputData', value: {}, matchingColumns: ['order_id'], schema: [] },
    options: {},
  }, retry()),
];

// ---------- connections ----------
const to = (...names) => names.map((n) => ({ node: n, type: 'main', index: 0 }));
const connections = {
  'Stripe Webhook': { main: [to('Extract Event')] },
  'Extract Event': { main: [to('Is Checkout Paid Event?')] },
  'Is Checkout Paid Event?': { main: [to('Fetch Session from Stripe'), to('Ignore Other Events')] },
  'Fetch Session from Stripe': { main: [to('Normalize Order'), to('Describe Failure')] },
  'Normalize Order': { main: [to('Find Existing Order')] },
  'Find Existing Order': { main: [to('Already Processed?'), to('Describe Failure')] },
  'Already Processed?': { main: [to('Duplicate - Stop Here'), to('Processing Row')] },
  'Processing Row': { main: [to('Claim Order')] },
  'Claim Order': { main: [to('Order Valid?'), to('Describe Failure')] },
  'Order Valid?': { main: [to('Look Up Stock'), to('Flag: Invalid Order')] },
  'Look Up Stock': { main: [to('Check Stock'), to('Describe Failure')] },
  'Check Stock': { main: [to('In Stock?')] },
  'In Stock?': { main: [to('Reserve Stock'), to('Flag: Out of Stock')] },
  'Reserve Stock': { main: [to('Low Stock?', 'Build Invoice HTML'), to('Describe Failure')] },
  'Low Stock?': { main: [to('Low Stock Warning'), []] },
  'Build Invoice HTML': { main: [to('Render Invoice PDF')] },
  'Render Invoice PDF': { main: [to('Email Customer'), to('Describe Failure')] },
  'Email Customer': { main: [to('Mark Fulfilled'), to('Describe Failure')] },
  'Mark Fulfilled': { main: [to('Build Log Row')] },
  'Flag: Invalid Order': { main: [to('Build Log Row')] },
  'Flag: Out of Stock': { main: [to('Build Log Row')] },
  'Describe Failure': { main: [to('Build Log Row')] },
  'Build Log Row': { main: [to('Needs Human?', 'Update Order Log')] },
  'Needs Human?': { main: [to('Alert Human'), []] },
};

const mainWorkflow = {
  name: 'Order-to-Fulfillment Pipeline',
  nodes,
  connections,
  pinData: {},
  settings: { executionOrder: 'v1' },
  active: false,
  tags: [],
};

// ---------- error-handler workflow (safety net) ----------
idCounter = 900;
const errorWorkflow = {
  name: 'Order Pipeline - Error Handler',
  nodes: [
    sticky('Note', [-60, 60], 560, 400,
      "## Safety net\nRuns if the main workflow crashes somewhere the in-workflow failure handling can't catch (e.g. the alert or the log step itself). Set it in the main workflow: Settings -> Error workflow.", 3),
    node('Error Trigger', 'n8n-nodes-base.errorTrigger', 1, [0, 280], {}),
    telegram('Alert: Workflow Crashed', [240, 280],
      `=🔥 Order workflow crashed

Workflow: {{ $json.workflow.name }}
Failed node: {{ $json.execution.lastNodeExecuted }}
Error: {{ $json.execution.error.message }}

Open the execution: {{ $json.execution.url }}
Then check the Orders sheet for any order stuck on "processing".`,
      retry()),
  ],
  connections: { 'Error Trigger': { main: [to('Alert: Workflow Crashed')] } },
  pinData: {},
  settings: { executionOrder: 'v1' },
  active: false,
  tags: [],
};

// ---------- sanity checks ----------
const names = new Set(nodes.map((n) => n.name));
for (const [from, { main }] of Object.entries(connections)) {
  if (!names.has(from)) throw new Error(`Unknown source node: ${from}`);
  for (const out of main) for (const c of out) if (!names.has(c.node)) throw new Error(`Unknown target node: ${c.node}`);
}

const write = (file, wf) => {
  fs.writeFileSync(path.join(root, 'workflows', file), JSON.stringify(wf, null, 2) + '\n');
  console.log(`wrote workflows/${file} (${wf.nodes.length} nodes)`);
};
write('order-fulfillment-pipeline.json', mainWorkflow);
write('order-error-handler.json', errorWorkflow);
