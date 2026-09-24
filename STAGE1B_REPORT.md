# Stage 1B — International checkout qualification & payment completion

Branch `intl-checkout-stage1` (Stage 1 committed as 29283b6). **Not deployed. No prices changed. No supplier orders created.**
Tests: 86 passing (`venv/Scripts/python.exe -m pytest tests`).

## 1. Market plan (per your revision)
`LAUNCH_WAVE_1 = US, GB, DE, FR, AU, CA` · `LAUNCH_WAVE_2_CANDIDATE = CH, JP, SG, NZ`.
Default *enabled* set is `US, GB, AU, CA` (the legacy-working markets); **DE and FR are candidates that stay OFF** until enabled
explicitly (`INTL_ENABLED_COUNTRIES` / StoreConfig `intl_enabled_countries`). NG and GH: removed from checkout, rollout, probes
and address rules; they remain inert ISO records (`checkout_enabled=false`). Other ISO markets stay in discovery state.

## 2. Supplier contract — what could and could not be verified
- Authenticated Silverbene API docs: **not accessible to me** (login-gated; I did not attempt to sign in). Public page
  (silverbene.com/silverbene-jewelry-dropshipping-rest-api) only says "send your products (option_id + qty) and destination
  (country_id + postcode)" and "send your products, the shipping_address and the chosen shipping method"; it says nothing on
  multi-product orders, rate expiry, ETA fields, country list, customs/tax-ID/comment fields or settlement.
- Country-list endpoints guessed (`get_country`, `country_list`, `countries`): **404**. No authoritative country list found.
- **Rate response shape (proven live):** `{code, message, currency:"USD", data:[{way, title, price}]}` — no ETA field; ETA/notes are inside `title`
  (e.g. "DHL Express(4 - 9 workdays, customs duty included)"). `country_id` = ISO alpha-2 worked for all six.
- Rate lookup **needs postcode + city**: without them DHL/FedEx are not returned (only two economy options).
- **`way` is not a unique id:** US returned `ITDIDA_ECO` twice ("International Economy" $3.50 and "International Standard" $5.52). `create_order`
  takes only `way`, so a customer's exact pick between them can't be expressed. Handled: keep the dearer, flag `ambiguous_method_id`. **Ask Silverbene.**
- Rate expiry: not documented. We use our own 15-minute TTL and refresh in the background.
- Multi-product `create_order`: **still unverified** (creating an order is prohibited in this stage). See §7.

## 3. Live read-only probe (artifacts/silverbene_*)
31 successful rate calls, 13 locations (2–3 per country), 3 real in-stock option_ids. **Latency: median 51 s, min 6 s, max 110 s per call**, plus
occasional connect timeouts under parallel load. Consequences, all implemented: the Delivery step is now **asynchronous** (returns immediately, browser polls
`/checkout/{id}/options`), stale-quote refresh is background-only, supplier failure fails closed as "unavailable".

Qualification matrix (all: country_id = ISO code, postcode/city required, currency USD, prices identical across cities within a country):

| Market | Supported | EXPRESS methods (price) | STANDARD methods (price) |
|---|---|---|---|
| US | yes | DHL Express 4–9d $57.83 (**customs duty included**), FedEx $62.41 | International Standard 12–20d $5.52 (id dup. w/ Economy $3.50) |
| GB | yes | DHL $45.89, FedEx $27.56 | Cainiao $10.64, ITDIDA_ECO 9d $4.21, YunExpress $13.22 (some cities) |
| DE | yes | DHL $49.37, FedEx $32.13 | Cainiao $15.57, YunExpress $17.76, ITDIDA_ECO $12.18 (Munich only) |
| FR | yes | DHL $49.37, FedEx $32.13 | Cainiao $16.48, YunExpress $17.90, ITDIDA_ECO $11.93 |
| AU | yes | DHL $36.02, FedEx $36.36 | Cainiao $9.96, YunExpress $16.34 |
| CA | yes | DHL $36.93, FedEx $33.71 | Cainiao $14.13, YunExpress $15.02 |

**The dedicated lanes cited in the research (USPS, Hermes, DHL Global Mail, La Poste, Australia Post, Canada Post) did not appear** for these three products.
They may be product/warehouse-specific; not confirmed. "Usable for dropshipping vs wholesale-only" is not exposed by the rate API (undetermined).

## 4. STANDARD / EXPRESS abstraction
Both tiers are always quoted and persisted; customers choose a **tier** (`shipping_tier`), never a supplier method id or carrier name. Tier heuristics
(economy wording beats "express"; DHL/FedEx/UPS = express; ETA ≤ 8d = express) are tested on real titles ("Economic Express" → STANDARD).
Exposure is flag-controlled: `INTL_TIER_EXPOSURE=frozen` (default) offers ONE option — DHL Express if offered (your standing rule, even where FedEx is cheaper), else the
cheapest express, else standard — so Standard $5 vs Express $50 can't shift margin before pricing charges for it. `both` exposes two tiers (tested, not for real customers).

## 5. Compliance
Hardcoded `KP/IR/CU/SY` removed. New versioned `compliance_policy.json` (ships empty) requires country, action, jurisdiction, source, reason, effective_from,
review_date (optional effective_until); malformed entries raise (never fail open); overdue reviews are queryable. Blocked markets are removed from the enabled set.

## 6. Payments
**Stripe (test key, real API):** sessions created with the exact checkout parameters; legacy card-only resolves `[card]`; dynamic mode (`INTL_STRIPE_DYNAMIC_METHODS=1`,
omits `payment_method_types`) resolves — USD: card, klarna, link, affirm, cashapp, amazon_pay; GBP/AUD/CAD: card, link; EUR: card, bancontact, eps, link, mb_way.
Dashboard config (test account): card on, link on, **apple_pay on, google_pay OFF**. Stripe's hosted page showed an express-wallet button + Card. Apple/Google Pay
cannot be exercised headlessly — verify by hand on a real device, and turn Google Pay on in the Dashboard. I deliberately did **not** complete a test payment (a test webhook could reach your live server).
Production presentment stays USD; local currencies are a pricing-stage item.
**PayPal:** real Orders v2 implementation (`app/checkout_intl/paypal.py`, flag `INTL_PAYPAL`, sandbox default, live refused without `PAYPAL_ALLOW_LIVE=1`): create, approval redirect,
capture (idempotent `PayPal-Request-Id`, replay-safe), amount verification, return route + `CHECKOUT.ORDER.APPROVED` webhook capture, signature verification (rejects when
unverifiable), cancel/retry (fresh order), denied/reversed/refunded handling, full & partial refund. **Tested against a faithful mock only — no sandbox credentials
exist here (`PAYPAL_CLIENT_ID` missing), so the real sandbox has not been exercised.**

## 7. Multi-item semantics (economics — decide before pricing)
Live evidence, 3 items to one address: one combined shipment vs three separate supplier orders — US DHL **$66.22 vs $169.87**; DE/FR DHL **$49.37 vs $148.11**;
GB FedEx $27.56 vs $82.68; AU DHL $36.02 vs $108.06; CA DHL $36.93 vs $110.79. Shipping is ~flat per shipment. Today's fulfillment creates one supplier order per cart
line, i.e. ~3× shipping on a 3-item cart. **Strongly recommend one supplier order per paid cart** — but whether `create_order` accepts several `products` is unverified
(needs authenticated docs or a supplier answer; the adapter already sends `products` as a list). Fulfillment unchanged this stage.

## 8. Supplier settlement
Unchanged: `use_credit=False`, orders wait for manual payment. Public docs give nothing on credit/auto-pay; a direct call to the balance endpoint returned non-JSON
(not investigated further). **Separate gate before scaling:** ask Silverbene about API-payable credit, `use_credit=true` behavior, top-up and auto-top-up.

## 9. Browser qualification (real page, local scratch DB, real Stripe test sessions, scripted supplier)
Desktop + 375×812 mobile: modal renders, no horizontal overflow, bottom-sheet on mobile. Country selector shows exactly the 6 markets; state/postcode labels and examples switch per country.
Verified: US Chicago/Atlanta, CA, GB, DE (EU), FR (standard-only), AU; invalid US/DE postcode; missing state; missing phone; no supplier rates; ring without size (blocked) / with
size; multi-item cart; sold-out item; empty cart; back-navigation; loading state ("Finding delivery options…"); stale quote → "Refreshing…" → change detected → "choose again";
double-tap on Pay → exactly one payment session (server-verified); redirect to Stripe test checkout with unchanged price. **Not covered:** an Asian market (JP is Wave 2 and not enabled),
real-supplier latency in the UI (scripted delay only), wallet buttons.

## 10. Acceptance gate
| Gate | Status |
|---|---|
| Real Silverbene country/method mapping | **Done for Wave 1** (read-only) |
| Address matches authenticated contract | **Open** — matches the proven adapter contract; authenticated docs unavailable |
| STANDARD/EXPRESS abstraction | Done |
| Stripe test suite | Done (sessions/methods); wallets need manual device check |
| PayPal sandbox suite | **Open** — mock only; needs sandbox credentials |
| Browser checkout | Done (see gaps) |
| Legacy regression | Green (legacy checkout parity tests) |
| No prices changed / no supplier orders | Confirmed |

## Security note
The Silverbene API token appeared in one probe error string (a URL in a timeout message) and in tool output. Files were scrubbed and the scripts now redact it; **rotate the key.**
