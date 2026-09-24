# $45 clean profit per product sold (REVIEW ONLY, not live)

Each product is priced on its own, with its own DHL Express shipment (that is how fulfillment works today: one Silverbene order per cart line). No tax is collected by Mikisi.

- **Prepaid (DDP):** Mikisi pays duty + import VAT up front; the customer pays nothing at the door.
- **Receiver pays:** the customer pays duty + VAT to DHL at the door (a surprise bill); the price is lower.

Assumes profit $45 per product, Stripe fees, 2% reserve, duty on the wholesale declared value, USD.

## Inputs: DHL Express cost basis (max observed) and border rules

| Country | DHL Express | Duty | Border VAT/GST | Confidence |
|---|---|---|---|---|
| US | $64.73 | 43.8% | 0% | unverified |
| GB | $45.89 | 0.0% | 20% | sourced |
| DE | $49.37 | EUR3/item flat (<EUR150), else 2.5% | 19% | sourced |
| FR | $49.37 | EUR3/item flat (<EUR150), else 2.5% | 20% | sourced |
| AU | $36.02 | 0.0% | 0% | unverified |
| CA | $36.93 | 8.0% | 13% | unverified |

## ONE ITEM PRICE + DHL EXPRESS DELIVERY FEE PER COUNTRY - PREPAID: duty and taxes included in the delivery fee

| Wholesale | ITEM price (worldwide) | US | GB | DE | FR | AU | CA |
|---|---|---|---|---|---|---|---|
| $10 | **$60** | +$72 | +$62 | +$70 | +$71 | +$39 | +$47 |
| $20 | **$71** | +$77 | +$63 | +$72 | +$72 | +$39 | +$50 |
| $30 | **$82** | +$81 | +$65 | +$73 | +$74 | +$38 | +$52 |
| $40 | **$92** | +$86 | +$68 | +$76 | +$77 | +$39 | +$55 |
| $60 | **$114** | +$94 | +$72 | +$80 | +$81 | +$39 | +$59 |
| $80 | **$135** | +$104 | +$77 | +$84 | +$86 | +$39 | +$64 |
| $100 | **$157** | +$112 | +$81 | +$88 | +$90 | +$39 | +$68 |
| $150 | **$211** | +$134 | +$91 | +$98 | +$100 | +$38 | +$80 |

(Delivery fee per country; profit at W=$40 in every country is at least $45.24.)

## ONE ITEM PRICE + DHL EXPRESS DELIVERY FEE PER COUNTRY - RECEIVER PAYS: customer also pays duty + tax to DHL at the door

| Wholesale | ITEM price (worldwide) | US | GB | DE | FR | AU | CA |
|---|---|---|---|---|---|---|---|
| $10 | **$60** | +$68 | +$49 | +$53 | +$53 | +$39 | +$40 |
| $20 | **$71** | +$67 | +$49 | +$53 | +$53 | +$39 | +$40 |
| $30 | **$82** | +$67 | +$49 | +$53 | +$53 | +$38 | +$39 |
| $40 | **$92** | +$67 | +$50 | +$53 | +$53 | +$39 | +$40 |
| $60 | **$114** | +$67 | +$49 | +$53 | +$53 | +$39 | +$40 |
| $80 | **$135** | +$67 | +$50 | +$54 | +$54 | +$39 | +$40 |
| $100 | **$157** | +$66 | +$49 | +$53 | +$53 | +$39 | +$40 |
| $150 | **$211** | +$65 | +$49 | +$53 | +$53 | +$38 | +$39 |

(Delivery fee per country; profit at W=$40 in every country is at least $45.00.)

## ONE ALL-IN PRICE (no separate delivery fee) - PREPAID

| Wholesale | ONE price | Driven by | Live ladder today | Profit in US | GB | DE | FR | AU | CA |
|---|---|---|---|---|---|---|---|---|---|
| $10 | **$132** | US | $128 | $45 | $55 | $47 | $47 | $76 | $68 |
| $20 | **$148** | US | $198 | $46 | $58 | $50 | $50 | $81 | $71 |
| $30 | **$163** | US | $228 | $46 | $60 | $52 | $52 | $85 | $73 |
| $40 | **$178** | US | $298 | $45 | $62 | $55 | $54 | $89 | $75 |
| $60 | **$208** | US | $348 | $45 | $66 | $59 | $58 | $97 | $78 |
| $80 | **$239** | US | $448 | $46 | $71 | $64 | $62 | $106 | $82 |
| $100 | **$269** | US | $498 | $45 | $75 | $68 | $66 | $114 | $86 |
| $150 | **$345** | US | $698 | $45 | $85 | $79 | $77 | $134 | $96 |

## ONE ALL-IN PRICE (no separate delivery fee) - RECEIVER PAYS

| Wholesale | ONE price | Driven by | Live ladder today | Profit in US | GB | DE | FR | AU | CA |
|---|---|---|---|---|---|---|---|---|---|
| $10 | **$128** | US | $128 | $46 | $63 | $59 | $59 | $73 | $72 |
| $20 | **$138** | US | $198 | $45 | $62 | $58 | $58 | $72 | $71 |
| $30 | **$149** | US | $228 | $46 | $62 | $59 | $59 | $72 | $71 |
| $40 | **$159** | US | $298 | $45 | $62 | $58 | $58 | $71 | $70 |
| $60 | **$181** | US | $348 | $46 | $62 | $58 | $58 | $72 | $71 |
| $80 | **$202** | US | $448 | $46 | $62 | $58 | $58 | $71 | $70 |
| $100 | **$223** | US | $498 | $46 | $61 | $58 | $58 | $71 | $70 |
| $150 | **$276** | US | $698 | $46 | $60 | $57 | $57 | $70 | $69 |

## What a customer is billed at the door if you do NOT prepay (W=$40)

| Country | Duty | VAT/GST | Total surprise (before DHL's own handling fee) |
|---|---|---|---|
| US | $17.52 | $0.00 | **$17.52** |
| GB | $0.00 | $17.18 | **$17.18** |
| DE | $3.51 | $17.65 | **$21.16** |
| FR | $3.51 | $18.58 | **$22.09** |
| AU | $0.00 | $0.00 | **$0.00** |
| CA | $3.20 | $10.42 | **$13.62** |

## Sensitivities: the ONE all-in price at W=$40 (prepaid / receiver pays)

| Scenario | Prepaid | Receiver pays |
|---|---|---|
| Base | $178 | $159 |
| US duty LOW 22.5% (not 43.8%) | $169 | $159 |
| Customs uses RETAIL as declared value | $297 | $159 |
| DHL duty/tax fee $19 per order | $198 | $159 |
| Silverbene fee 3% of price | $184 | $165 |
| PayPal instead of Stripe | $178 | $159 |
| Reserve 5% | $184 | $165 |

## Assumptions still to verify

- TARGET: $45 is per ORDER (a cart), not per item; the shipping cost basis is single-item.
- Silverbene's own fees/taxes on an order (e.g. a fee when paying by card/PayPal on their page) -- unknown, modelled 0.
- Customs declared value = Silverbene's invoice value (wholesale). Customs may instead use the price the customer paid (see the 'retail declared value' sensitivity) -- ask Silverbene what they declare, and get a customs broker's view.
- US duty stack (22.5% vs 43.8%) -- confirm the HS code and declared value with Silverbene/DHL or a customs broker.
- Whether DHL's duty-and-tax-paid fee (Europe: 2%, min ~EUR16.50) applies to shipments Silverbene books -- modelled 0.
- Whether a Silverbene DHL shipment can actually be booked duty-and-tax-PREPAID (the 'prepaid' mode) -- unconfirmed.
- Payment provider rates (Stripe 2.9%+30c, +1.5% international; PayPal 3.49%+49c / 4.99%+49c) -- not re-verified.
- Reserve for refunds/chargebacks/lost parcels: 2% of price (assumed).

## Country notes

**US**
- De minimis suspended (Federal Register 2026-06-24). Duty stack for China-origin silver jewelry uncertain: 22.5%-43.8%.
- Owner's DHL sample was charged duty at delivery despite 'customs duty included' -> duty is a real cost.
- US state sales tax not modelled (economic-nexus thresholds not reached; revisit as volume grows).
**GB**
- Duty relief on consignments <= GBP135 (2% otherwise) until 2029 (GOV.UK).
- VAT 20% is charged on import when the seller has not charged it at checkout (unregistered seller).
**DE**
- EU flat EUR3 duty per item on parcels < EUR150 from 2026-07-01 (until 2028-07-01); 2.5% above (TARIC).
- Import VAT 19% is charged at the border when the seller has no IOSS registration.
**FR**
- Same EU rules as Germany; import VAT 20%.
**AU**
- Imports <= A$1,000 are generally duty/GST free at the border; overseas sellers only register for GST at A$75,000 of Australian sales (ATO). A 5% duty on finished jewelry was NOT confirmed for <= A$1,000.
- Modelled as 0 -- monitor Australian sales against the threshold.
**CA**
- China-origin courier duty-free limit is only CAD 20; jewelry duty 6.5-8% (CBSA); 8% used.
- GST 5% + provincial tax 0-10% on duty-paid value at import; 13% (Ontario HST) used as a planning value.
