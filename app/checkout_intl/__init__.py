"""
International checkout foundation -- Stage 1.

Scope: make the customer -> address -> Silverbene shipping quote -> shipping
choice -> payment -> fulfillment route structurally correct for every
destination Silverbene can serve. Deliberately NOT in scope: pricing, margins,
tax/duty economics, target contribution. Prices, Stripe line items and Meta
values are exactly what the legacy checkout produces.

Everything here is inert unless the INTL_CHECKOUT flag is on (flags.py).
"""
