"""
Backfill product specs from existing DB data.

Extracts from:
1. ARIA-written description prose (stone, setting, closure, finish, earring type)
2. Stored colors/variants (plating finish)
3. Existing specs (weight, width already stored)

Also updates _extract_specs_from_desc for any future re-imports.

Run:  python backfill_specs.py [--dry-run] [--limit N]
"""
import sys, io, json, re, psycopg2
from collections import defaultdict
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

DB = "postgresql://postgres:hraGohaQTwNssSkopCGAfQhcAkGVhjCH@yamabiko.proxy.rlwy.net:47017/railway"

DRY_RUN = "--dry-run" in sys.argv
LIMIT   = next((int(sys.argv[i+1]) for i, a in enumerate(sys.argv) if a == "--limit"), 9999)

# ── Extraction helpers ────────────────────────────────────────────────────────

def find_any(patterns, text):
    """Return first match for any pattern, case-insensitive."""
    for p in patterns:
        m = re.search(p, text, re.I)
        if m:
            g = m.group(1) if m.lastindex else m.group(0)
            return g.strip().rstrip('.,')
    return None

# Stone types — ordered most-specific first
STONE_PATTERNS = [
    r'\b(cubic zirconia)\b', r'\b(cz)\b', r'\b(moissanite)\b',
    r'\b(natural pearl)s?\b', r'\b(freshwater pearl)s?\b', r'\b(baroque pearl)s?\b',
    r'\b(shell pearl)s?\b', r'\b(pearl)s?\b',
    r'\b(turquoise)\b', r'\b(opal)\b', r'\b(malachite)\b',
    r'\b(amethyst)\b', r'\b(citrine)\b', r'\b(topaz)\b',
    r'\b(garnet)\b', r'\b(peridot)\b', r'\b(aquamarine)\b',
    r'\b(labradorite)\b', r'\b(moonstone)\b', r'\b(tanzanite)\b',
    r'\b(tiger.?eye)\b', r'\b(lapis lazuli)\b', r'\b(malachite)\b',
    r'\b(jade)\b', r'\b(onyx)\b', r'\b(rose quartz)\b',
    r'\b(enamel)\b', r'\b(resin)\b',
]

SETTING_PATTERNS = [
    r'\b(micro[ -]?pav[eé])\b', r'\b(pav[eé])\b',
    r'\b(prong[ -]?set)\w*\b', r'\b(bezel[ -]?set)\w*\b',
    r'\b(channel[ -]?set)\w*\b', r'\b(flush[ -]?set)\w*\b',
    r'\b(prong)\b', r'\b(bezel)\b', r'\b(channel)\b',
]

CLOSURE_PATTERNS = [
    r'\b(lobster clasp)\b', r'\b(toggle clasp)\b', r'\b(spring ring clasp)\b',
    r'\b(box clasp)\b', r'\b(magnetic clasp)\b', r'\b(hook clasp)\b',
    r'\b(push-back)\b', r'\b(butterfly back)s?\b', r'\b(screw back)s?\b',
    r'\b(latch back)\b', r'\b(french wire)\b', r'\b(omega back)\b',
    r'\b(clasp)\b', r'\b(hook)\b',
]

CRAFT_PATTERNS = [
    r'\b(micro[ -]?setting)\b', r'\b(micro[ -]?inlay)\b',
    r'\b(hammered)\b', r'\b(textured)\b', r'\b(engraved)\b',
    r'\b(filigree)\b', r'\b(oxidized)\b',
]

EARRING_BACKS = [
    r'\b(butterfly back)s?\b', r'\b(push back)s?\b', r'\b(rubber back)s?\b',
    r'\b(screw back)s?\b', r'\b(lever back)s?\b', r'\b(clip[ -]?on)\b',
    r'\b(hinged hoop)\b',
]

PLATING_MAP = {
    'silver': None,    # plain silver — no plating line
    'white gold': 'Rhodium',
    'rhodium': 'Rhodium',
    '18k yellow gold': '18K Yellow Gold',
    '18k gold': '18K Yellow Gold',
    'yellow gold': '18K Yellow Gold',
    'gold': '18K Yellow Gold',
    'rose gold': 'Rose Gold',
}

def stone_display(raw):
    """Normalise stone name to title case."""
    if not raw: return None
    s = raw.replace('-', ' ').strip()
    # Common normalisations
    if s.lower() == 'cz': return 'Cubic Zirconia'
    return s.title()

def extract_from_prose(desc, colors_json):
    """Extract spec fields from ARIA prose description + stored color variants."""
    specs = {}
    text = re.sub(r'<[^>]+>', ' ', desc or '')

    # Stone
    st = find_any(STONE_PATTERNS, text)
    if st: specs['stone'] = stone_display(st)

    # Setting
    se = find_any(SETTING_PATTERNS, text)
    if se: specs['setting'] = se.title()

    # Closure
    cl = find_any(CLOSURE_PATTERNS, text)
    if cl: specs['closure'] = cl.title()

    # Craftsmanship
    cr = find_any(CRAFT_PATTERNS, text)
    if cr: specs['craftsmanship'] = cr.title()

    # Earring backs (from description prose)
    eb = find_any(EARRING_BACKS, text)
    if eb: specs['earring_backs'] = eb.title()

    # Plating from stored color variants
    if colors_json:
        try:
            colors = json.loads(colors_json)
            platings = []
            for c in colors:
                key = c.lower().strip()
                mapped = PLATING_MAP.get(key)
                if mapped and mapped not in platings:
                    platings.append(mapped)
            # If multiple finishes, format as "Rhodium / 18K Yellow Gold"
            if platings:
                specs['plating'] = ' / '.join(platings)
        except Exception:
            pass

    return specs

# ── Main ──────────────────────────────────────────────────────────────────────

conn = psycopg2.connect(DB)
cur  = conn.cursor()
cur.execute("SELECT id, name, description, specs, colors FROM product ORDER BY id")
products = cur.fetchall()

updated = 0; field_stats = defaultdict(int)

print(f"Products: {min(len(products), LIMIT)}  |  Dry run: {DRY_RUN}\n")

for pid, name, desc, specs_json, colors_json in products[:LIMIT]:
    existing = {}
    try: existing = json.loads(specs_json) if specs_json else {}
    except: pass

    extracted = extract_from_prose(desc, colors_json)

    # Only add fields that aren't already stored
    added = {k: v for k, v in extracted.items() if k not in existing and v}
    if not added:
        continue

    merged = {**existing, **added}
    for k in added: field_stats[k] += 1

    status = "DRY" if DRY_RUN else "OK "
    print(f"  [{status}] [{pid}] {name[:45]:<45}  +{list(added.keys())}")

    if not DRY_RUN:
        cur.execute("UPDATE product SET specs=%s WHERE id=%s", (json.dumps(merged), pid))
    updated += 1

if not DRY_RUN:
    conn.commit()
cur.close(); conn.close()

print(f"\n-- Summary --")
print(f"  Enriched: {updated} products")
print(f"\n  Fields added:")
for k, c in sorted(field_stats.items(), key=lambda x: -x[1]):
    print(f"    {k:<22} {c} products")
