// Every technical error output in the workflow lands here.
// We work out WHICH step failed (the furthest step that ran) and attach
// a plain-English "what to do" so the person alerted doesn't need the logs.
const ran = (name) => { try { return $(name).isExecuted; } catch { return false; } };

// Pipeline order, last step first.
const steps = [
  ['Email Customer', 'Email customer',
    'Money taken, stock reserved, invoice created - only the email failed (after 3 tries). Check the Gmail credential, then resend the confirmation manually and set status to fulfilled.'],
  ['Render Invoice PDF', 'Generate invoice PDF',
    'Money taken and stock reserved, but no invoice was made. Check that Gotenberg is running, then re-run or send the invoice manually.'],
  ['Reserve Stock', 'Reserve stock',
    'Money taken but stock was NOT reduced. Reduce the stock in the Inventory sheet by hand, then fulfil the order.'],
  ['Look Up Stock', 'Inventory check',
    'Could not read the Inventory sheet. Check the Google Sheets credential and that the "Inventory" tab exists.'],
  ['Claim Order', 'Log order (claim)',
    'Could not write to the Orders sheet. Check the Google Sheets credential and that the "Orders" tab exists.'],
  ['Find Existing Order', 'Duplicate check',
    'Could not read the Orders sheet. Check the Google Sheets credential and that the "Orders" tab exists.'],
  ['Fetch Session from Stripe', 'Verify payment with Stripe',
    'Could not confirm this payment with Stripe. If the session id is unknown the webhook may be fake; otherwise check the Stripe credential.'],
];

const [, step, action] = steps.find(([node]) => ran(node)) ?? [null, 'Unknown step', 'Open the execution in n8n to investigate.'];

const err = $json.error;
const reason = typeof err === 'string'
  ? err
  : (err?.message || err?.description || JSON.stringify(err ?? $json).slice(0, 300));

return [{ json: { status: 'failed', failed_step: step, reason, action } }];
