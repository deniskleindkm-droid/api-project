"""
Variant normalizer — converts any CJ variant format into a clean grouped dict.

Handles formats:
  A: {variantName, variantValue, vid}
  B: {propertyName, propertyValue, vid}
  C: {name: "Size:7", vid}
  D: {variantSku: "Size:7-Color:Gold", vid}
  E: {variantKey: "Gold-US 6", vid}          — NEW: CJ ring size format
  F: {propertyList: [{name:"Size",value:"6"}]} — NEW: structured property array
"""

VALID_US_RING_SIZES = {
    "5", "5.5", "6", "6.5", "7", "7.5", "8", "8.5", "9", "9.5", "10"
}


def _extract_ring_size(s: str):
    """
    Extract a valid US ring size from strings like:
      "US 6", "US-6", "US6", "6", "6.5", "US 6.5"
    Returns the size string (e.g. "6") or None.
    """
    s = s.strip()
    for prefix in ("US-", "US ", "US"):
        if s.upper().startswith(prefix):
            candidate = s[len(prefix):].strip()
            if candidate in VALID_US_RING_SIZES:
                return candidate
    if s in VALID_US_RING_SIZES:
        return s
    return None


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

        # Format A: {variantName, variantValue}
        if raw.get("variantName") and raw.get("variantValue"):
            _add(raw["variantName"], raw["variantValue"], vid)

        # Format B: {propertyName, propertyValue}
        elif raw.get("propertyName") and raw.get("propertyValue"):
            _add(raw["propertyName"], raw["propertyValue"], vid)

        else:
            # Format C/D — parse from colon-separated string fields
            name_str = (
                raw.get("variantNameEn") or
                raw.get("name") or
                raw.get("variantSku") or
                ""
            )
            if name_str:
                if ":" in name_str:
                    for pair in name_str.split("-"):
                        if ":" in pair:
                            parts = pair.split(":", 1)
                            _add(parts[0], parts[1], vid)
                else:
                    _add("Option", name_str, vid)

        # Format E: variantKey — always check regardless of A/B/C/D
        # Handles "Gold-US 6", "Silver-US 7.5", "US 6", "US-6", "7"
        vk = str(raw.get("variantKey") or "").strip()
        if vk:
            size_extracted = False
            for part in vk.split("-"):
                part = part.strip()
                if not part:
                    continue
                size_val = _extract_ring_size(part)
                if size_val:
                    _add("Size", size_val, vid)
                    size_extracted = True
                else:
                    _add("Color", part, vid)
            if is_rings:
                print(f"[Variant] Format E variantKey='{vk}' size_extracted={size_extracted}")

        # Format F: propertyList [{name: "Size", value: "6"}]
        prop_list = raw.get("propertyList") or []
        if isinstance(prop_list, list) and prop_list:
            for prop in prop_list:
                if not isinstance(prop, dict):
                    continue
                pname = (prop.get("name") or prop.get("propertyName") or "").strip()
                pval = str(prop.get("value") or prop.get("propertyValue") or "").strip()
                if not pname or not pval:
                    continue
                if pname.lower() in ("size", "ring size") and is_rings:
                    normalized_size = _extract_ring_size(pval)
                    if normalized_size:
                        pval = normalized_size
                _add(pname, pval, vid)

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
            print(f"[Variant] Ring size FAIL — no Size group. Groups: {list(groups.keys())}")
        else:
            ring_size_valid = any(e["value"] in VALID_US_RING_SIZES for e in size_group)
            if not ring_size_valid:
                vals = [e["value"] for e in size_group]
                print(f"[Variant] Ring size FAIL — values not in valid set: {vals}")

    variant_count = sum(len(v) for v in groups.values())

    return {
        "groups": groups,
        "has_variants": variant_count > 0,
        "variant_count": variant_count,
        "ring_size_valid": ring_size_valid,
    }
