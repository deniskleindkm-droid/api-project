# Price model: $45 clean profit per order (REVIEW ONLY, not live)

Target contribution $45/order, reserve 2%, Stripe rates, duty on wholesale declared value, one item per order, USD. Net = price before VAT/GST; Gross = what the customer pays incl. VAT where Mikisi collects it.

## Shipping cost basis (max observed) and duty/tax assumptions

| Country | Express (DHL) | Standard | Duty on declared value | VAT/GST Mikisi collects | Confidence |
|---|---|---|---|---|---|
| US | $64.73 | $7.28 | 43.8% | 0% | unverified |
| GB | $45.89 | $22.50 | 0.0% | 20% (needs registration) | sourced |
| DE | $49.37 | $27.06 | EUR3/item flat (<EUR150), else 2.5% | 19% (needs registration) | sourced |
| FR | $49.37 | $27.19 | EUR3/item flat (<EUR150), else 2.5% | 20% (needs registration) | sourced |
| AU | $36.02 | $25.59 | 0.0% | 0% | unverified |
| CA | $36.93 | $24.22 | 8.0% | 0% | unverified |

## Required NET price for $45 profit, by wholesale cost (Express / Standard)

| Country | W=$10 | W=$20 | W=$40 | W=$60 | W=$100 |
|---|---|---|---|---|---|
| US | $131 / $71 | $146 / $86 | $177 / $116 | $207 / $147 | $267 / $207 |
| GB | $110 / $84 | $120 / $95 | $142 / $117 | $164 / $138 | $207 / $181 |
| DE | $117 / $93 | $128 / $104 | $149 / $125 | $171 / $147 | $214 / $190 |
| FR | $117 / $93 | $128 / $104 | $150 / $126 | $171 / $147 | $214 / $190 |
| AU | $98 / $87 | $109 / $98 | $130 / $119 | $151 / $140 | $194 / $183 |
| CA | $100 / $86 | $111 / $98 | $135 / $121 | $158 / $144 | $204 / $190 |

## Customer-facing GROSS price (incl. VAT where collected), Express / Standard

| Country | W=$10 | W=$20 | W=$40 | W=$60 | W=$100 |
|---|---|---|---|---|---|
| US | $131 / $71 | $146 / $86 | $177 / $116 | $207 / $147 | $267 / $207 |
| GB | $131 / $101 | $144 / $114 | $170 / $140 | $196 / $166 | $248 / $218 |
| DE | $139 / $111 | $152 / $123 | $178 / $149 | $203 / $175 | $255 / $226 |
| FR | $141 / $112 | $153 / $125 | $179 / $151 | $205 / $177 | $257 / $228 |
| AU | $98 / $87 | $109 / $98 | $130 / $119 | $151 / $140 | $194 / $183 |
| CA | $100 / $86 | $111 / $98 | $135 / $121 | $158 / $144 | $204 / $190 |

## Today's live ladder vs the price needed (US Express) and the profit today's price actually leaves

| Wholesale | Live price | Needed for $45 (US Express) | Profit at live price (US Express) | Profit at live price (GB Express, ex-VAT) |
|---|---|---|---|---|
| $10 | $128 | $131 | $42 | $43 |
| $20 | $198 | $146 | $95 | $87 |
| $40 | $298 | $177 | $161 | $144 |
| $60 | $348 | $207 | $180 | $163 |
| $100 | $498 | $267 | $265 | $239 |

## Express upcharge over Standard (net price difference, W=$40)

- US: Express costs $60.41 more than Standard
- GB: Express costs $25.23 more than Standard
- DE: Express costs $24.05 more than Standard
- FR: Express costs $23.92 more than Standard
- AU: Express costs $11.14 more than Standard
- CA: Express costs $13.58 more than Standard

## Sensitivities (W=$40, Express): how much the uncertain inputs move the NET price

| Scenario | US | GB | DE | AU | CA |
|---|---|---|---|---|---|
| Base | $176 | $141 | $149 | $130 | $134 |
| US duty LOW 22.5% | $167 | $141 | $149 | $130 | $134 |
| Customs uses RETAIL as declared value | $292 | $141 | $149 | $130 | $143 |
| DHL duty/tax fee $19 per order | $196 | $162 | $169 | $150 | $154 |
| Silverbene fee 3% of net | $182 | $146 | $154 | $134 | $138 |
| PayPal instead of Stripe | $177 | $143 | $150 | $131 | $135 |
| Reserve 5% | $182 | $146 | $154 | $134 | $138 |

## Assumptions still to verify

- TARGET: $45 is per ORDER (a cart), not per item.
- Silverbene's own fees/taxes on an order (e.g. a fee when paying by card/PayPal on their page) -- unknown, modelled 0.
- Customs declared value = Silverbene's invoice value (wholesale). If Silverbene declares something else, duty changes.
- US duty stack (22.5% vs 43.8%) -- get the HS code and declared value from Silverbene/DHL, or a customs broker.
- DHL 'duty & tax paid' service fee (Europe: 2%, min ~EUR16.50) -- unknown whether it applies to our DHL shipments; modelled 0.
- Payment provider rates (Stripe 2.9%+30c, +1.5% international; PayPal 3.49%+49c / 4.99%+49c) -- not re-verified.
- Reserve for refunds/chargebacks/lost parcels: 2% of net price (assumed).
- UK VAT, EU IOSS and Australian GST registrations -- legal decisions for an accountant; not confirmed.
- Shipping cost basis is single-item; multi-item carts are cheaper per item only if Silverbene combines them into ONE order.

## Country notes

**US**
- De minimis suspended (Federal Register 2026-06-24). Duty stack for China-origin silver jewelry uncertain: 22.5%-43.8%.
- Owner's DHL sample was charged duty at delivery despite 'customs duty included' -> treat duty as a real cost.
- US state sales tax NOT modelled (economic-nexus thresholds not reached; revisit).
**GB**
- Duty relief on consignments <= GBP135 (2% otherwise) until 2029 (GOV.UK).
- Seller must REGISTER for UK VAT and charge 20% at checkout for consignments <= GBP135.
- Requires a UK VAT registration -- confirm with an accountant.
**DE**
- EU flat EUR3 duty per item on parcels < EUR150 from 2026-07-01 (until 2028-07-01); 2.5% above (TARIC).
- VAT 19% collectable at checkout via IOSS registration (parcels <= EUR150).
**FR**
- Same EU rules as Germany; VAT 20%. IOSS registration needed to collect VAT at checkout.
**AU**
- Imports <= A$1,000 are generally duty/GST free at the border; overseas seller must register and charge 10% GST once Australian sales reach A$75,000 (ATO). Duty 5% on finished jewelry was NOT confirmed for <= A$1,000.
- Modelled as 0 until the threshold is reached -- monitor Australian sales.
**CA**
- China-origin courier duty-free limit is only CAD 20; jewelry duty 6.5-8% (CBSA); 8% used.
- GST 5% / HST 13-15% is charged on duty-paid value at import and collected from the receiver by the carrier -- modelled as receiver-paid (customer surprise!) because Mikisi has no CA registration.
