// Pull the few fields we need out of the raw Stripe webhook body.
// We deliberately do NOT trust anything else in this payload - the next step
// re-fetches the checkout session straight from Stripe's API.
const body = $json.body ?? {};

return [{
  json: {
    event_id: body.id ?? '',
    event_type: body.type ?? '',
    session_id: body.data?.object?.id ?? '',
  },
}];
