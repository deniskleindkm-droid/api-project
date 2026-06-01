"""
Variant normalizer — converts any CJ variant format into a clean grouped dict.

Handles 4 CJ formats:
  A: {variantName, variantValue, vid}
  B: {propertyName, propertyValue, vid}
  C: {name: "Size:7", vid}
  D: {variantSku: "Size:7-Color:Gold", vid}
"""

VALID_US_RING_SIZES = {
    "5", "5.5", "6", "6.5", "7", "7.5", "8", "8.5", "9", "9.5", "10"
}


def normalize_variants(raw_variants: list, category: str) -> dict:
    """
    Normalize raw CJ variants into grouped structure.

    Returns:
        {
          "groups": {"Size": [{"value": "7", "vid": "xxx"}, ...], ...},
          "has_variants": bool,
          "variant_count": int,
          "ring_size_valid": bool
        }
    """
    is_rings = category.lower() in ("rings", "ring")

    if not raw_variants:
        return {
            "groups": {},
            "has_variants": False,
            "variant_count": 0,
            "ring_size_valid": not is_rings,
        }

    groups: dict = {}

    def _add(group: str, value: str, vid: str):
        g = group.strip()
        v = value.strip()
        if not g or not v:
            return
        if g not in groups:
            groups[g] = []
        if not any(e["vid"] == vid for e in groups[g]):
            groups[g].append({"value": v, "vid": vid})

    for raw in raw_variants:
        vid = str(raw.get("vid", ""))

        # Format A
        if raw.get("variantName") and raw.get("variantValue"):
            _add(raw["variantName"], raw["variantValue"], vid)
            continue

        # Format B
        if raw.get("propertyName") and raw.get("propertyValue"):
            _add(raw["propertyName"], raw["propertyValue"], vid)
            continue

        # Format C/D — parse from string fields
        name_str = (
            raw.get("variantNameEn") or
            raw.get("name") or
            raw.get("variantSku") or
            ""
        )
        if not name_str:
            continue

        # "Size:7-Color:Gold" or "Size:7"
        if ":" in name_str:
            for pair in name_str.split("-"):
                if ":" in pair:
                    parts = pair.split(":", 1)
                    _add(parts[0], parts[1], vid)
        # fallback — treat whole string as unnamed option
        else:
            _add("Option", name_str, vid)

    # Ring size validation
    ring_size_valid = True
    if is_rings:
        size_group = (
            groups.get("Size") or
            groups.get("size") or
            groups.get("Ring Size") or
            groups.get("ring size")
        )
        if not size_group:
            ring_size_valid = False
        else:
            ring_size_valid = any(e["value"] in VALID_US_RING_SIZES for e in size_group)

    variant_count = sum(len(v) for v in groups.values())

    return {
        "groups": groups,
        "has_variants": variant_count > 0,
        "variant_count": variant_count,
        "ring_size_valid": ring_size_valid,
    }
