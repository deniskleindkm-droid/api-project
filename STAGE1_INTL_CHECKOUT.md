# Stage 1 — SilverBene-compatible international checkout foundation

Branch: `intl-checkout-stage1`. **Default OFF.** Nothing changes for customers until the flag is turned on.

## Turning it on / off
- Env var `INTL_CHECKOUT=1` (wins), or StoreConfig `intl_checkout_enabled=true`. Unset = legacy checkout, byte-for-byte.
- Enabled countries: StoreConfig `intl_enabled_countries` (comma list). Default = US,CA,GB,AU,NG,GH (the legacy dropdown minus `other`).
- Shipping policy: `INTL_SHIPPING_POLICY=dhl_only` (default, preserves "always DHL, absorbed in price") or `all`.
- Quote lifetime: `INTL_QUOTE_TTL_MIN` (default 15).

## Flow
1. `GET /checkout/config` -> flag + country registry (frontend selector; no hardcoded list).
2. `POST /checkout/delivery` -> validates structured address + cart (option_id, variant/size required, live stock),
   asks Silverbene for rates for the actual cart and destination, stores a `CheckoutTransaction`.
3. `POST /checkout/{id}/pay` -> locks the chosen method (re-quotes if stale; never silently swaps), creates the Stripe
   session with **legacy-identical** line items/currency/methods, `checkout_id` in metadata.
4. Webhook -> `process_order_background` loads the transaction; `place_order(shipping_method=<exact chosen way>)`
   skips rate lookup entirely. `order_recovery_agent` does the same for retries (also fixes its lost phone/name for these orders).

## Files
New: `app/checkout_intl/{flags,countries,_iso_countries,address,rates,items,transaction,payment_providers,fulfillment}.py`,
`app/models/checkout_transaction.py`, `app/routes/intl_checkout.py`, `scripts/probe_silverbene_markets.py`, `tests/`.
Modified: `silverbene_adapter.py` (new optional params only), `payments.py` (checkout_id plumbing + duplicate-payment guard),
`order_recovery_agent.py`, `models/order.py` + `database.py` (nullable `order.checkout_id`), `main.py`, `docs/index.html` (new modal, opened only when flag on).

## Proven Silverbene contract (from the working adapter)
- Rates: POST `/api/dropshipping/get_shipping_method` `{country_id, postcode, city, products:[{option_id, qty}], token}`
  -> `data[]` items with `way`, `title`, `price`. ETA is NOT a proven field (parsed from title when present).
- Order: POST `/api/dropshipping/create_order` `{products, shipping_method:<way>, use_credit:false,
  shipping_address:{firstname,lastname,email,telephone,street,city,region,postcode,country_id}}`.
- Not proven (not sent): company, tax/customs ID, address line 2 as its own field (merged into `street`), order comment.

## Known limits / unresolved
- Authenticated Silverbene docs not available to this stage; `country_id` assumed = ISO alpha-2 (as today's orders). Override map exists.
- Country support + shipping-family matrix requires the live probe (`scripts/probe_silverbene_markets.py`) — not run.
- Fulfillment still creates one supplier order per cart line (as before); the cart is quoted as one shipment. Shipping cost is
  bookkeeping-only while pricing is frozen. Consolidating to one supplier order per cart is a later decision.
- `use_credit=False`: supplier orders still await manual payment (pre-existing).
- Customer-facing option shows "Included" (no shipping charge in Stage 1); supplier cost/route names never reach the browser.
- PayPal: contract slot only. Stripe: card method (wallets surface inside Checkout); no regional methods/currencies yet.
