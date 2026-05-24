from dotenv import load_dotenv
load_dotenv()

import requests
import json
import os
import time
import anthropic
from datetime import datetime
from sqlmodel import Session, select
from app.database import engine
from app.models.agent import AgentMemory

CJ_API_BASE = "https://developers.cjdropshipping.com/api2.0/v1"
CJ_EMAIL = os.getenv("CJ_EMAIL")
CJ_API_KEY = os.getenv("CJ_API_KEY")

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

# Token cache
_token_cache = {"token": None, "expires_at": 0}


def get_access_token():
    global _token_cache
    now = time.time()
    if _token_cache["token"] and now < _token_cache["expires_at"]:
        return _token_cache["token"]
    try:
        response = requests.post(
            f"{CJ_API_BASE}/authentication/getAccessToken",
            json={"email": CJ_EMAIL, "password": CJ_API_KEY},
            timeout=30
        )
        data = response.json()
        if data.get("result"):
            token = data["data"]["accessToken"]
            _token_cache["token"] = token
            _token_cache["expires_at"] = now + 3600
            return token
        print(f"[CJ] Auth failed: {data.get('message')}")
        return None
    except Exception as e:
        print(f"[CJ] Auth error: {e}")
        return None


def search_products(keyword, page=1, limit=20):
    token = get_access_token()
    if not token:
        return None
    try:
        response = requests.get(
            f"{CJ_API_BASE}/product/list",
            headers={"CJ-Access-Token": token},
            params={"productNameEn": keyword, "pageNum": page, "pageSize": limit},
            timeout=30
        )
        data = response.json()
        if data.get("result"):
            return data.get("data", {}).get("list", [])
        return []
    except Exception as e:
        print(f"[CJ] Search error: {e}")
        return []


def get_product_details(pid):
    token = get_access_token()
    if not token:
        return None
    try:
        response = requests.get(
            f"{CJ_API_BASE}/product/query",
            headers={"CJ-Access-Token": token},
            params={"pid": pid},
            timeout=30
        )
        data = response.json()
        if data.get("result"):
            return data.get("data")
        return None
    except Exception as e:
        print(f"[CJ] Product detail error: {e}")
        return None


def extract_image_url(cj_product):
    raw = (
        cj_product.get("productImage") or
        cj_product.get("productImageUrl") or
        cj_product.get("mainImage") or
        cj_product.get("imageUrl") or
        ""
    )
    if isinstance(raw, list):
        return raw[0] if raw else ""
    if isinstance(raw, str) and raw.strip().startswith("["):
        try:
            parsed = json.loads(raw)
            return parsed[0] if parsed else ""
        except:
            return raw
    return raw


def get_or_create_collection(product_name, category_name, description=""):
    """Use AI to determine the right collection, then find or create it"""
    from app.models.collection import Collection

    with Session(engine) as session:
        existing_collections = session.exec(
            select(Collection).where(Collection.is_active == True)
        ).all()

    existing_names = [c.name for c in existing_collections]

    try:
        prompt = f"""You are the collection manager for Mikisi — a women's beauty accessories store.

Product being added:
- Name: {product_name}
- Category from supplier: {category_name}
- Description preview: {description[:200] if description else ''}

Existing collections in Mikisi store: {existing_names if existing_names else 'None yet'}

Determine which collection this product belongs to.
Rules:
- If it fits an existing collection, use that exact name
- If it does not fit any existing collection, create a new meaningful collection name
- Collection names should be simple, elegant, and relevant to women's beauty
- Examples of good collection names: Hair Care, Skincare, Jewelry, Makeup Tools, Nail Care, Body Care
- Never create a collection that is too narrow like Clay Masks — use Skincare instead
- Never create a collection that is too broad like Products

Return JSON only:
{{
    "collection_name": "the collection this product belongs to",
    "is_new": true,
    "reason": "brief reason for this choice"
}}"""

        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}]
        )

        text = message.content[0].text.strip()
        if text.startswith("```"):
            parts = text.split("```")
            if len(parts) >= 2:
                text = parts[1]
                if text.startswith("json"):
                    text = text[4:]

        result = json.loads(text.strip())
        collection_name = result.get("collection_name", "Beauty")
        print(f"[CJ] AI determined collection: {collection_name} — {result.get('reason', '')}")

    except Exception as e:
        print(f"[CJ] AI collection detection failed: {e} — using category fallback")
        if ">" in category_name:
            collection_name = category_name.split(">")[-1].strip()
        elif "," in category_name:
            collection_name = category_name.split(",")[0].strip()
        else:
            collection_name = category_name.strip()
        if len(collection_name) > 30 or not collection_name:
            collection_name = "Beauty"

    with Session(engine) as session:
        existing = session.exec(
            select(Collection).where(
                Collection.name == collection_name,
                Collection.is_active == True
            )
        ).first()

        if existing:
            return existing.id

        new_col = Collection(
            name=collection_name,
            description=f"Curated {collection_name.lower()} products for the Mikisi woman",
            is_active=True,
            sort_order=len(existing_names),
            created_at=datetime.utcnow()
        )
        session.add(new_col)
        session.commit()
        session.refresh(new_col)
        print(f"[CJ] ✅ New collection created: {collection_name}")
        return new_col.id


def get_shipping_methods(cj_vid, country_code="US"):
    token = get_access_token()
    if not token:
        return []
    try:
        time.sleep(1)
        response = requests.post(
            f"{CJ_API_BASE}/logistic/freightCalculate",
            headers={
                "CJ-Access-Token": token,
                "Content-Type": "application/json"
            },
            json={
                "startCountryCode": "CN",
                "endCountryCode": country_code,
                "products": [{"vid": cj_vid, "quantity": 1}]
            },
            timeout=30
        )
        data = response.json()
        print(f"[CJ] Shipping methods: {data}")
        if data.get("result"):
            return data.get("data", [])
        return []
    except Exception as e:
        print(f"[CJ] Shipping error: {e}")
        return []


def import_product_to_store(cj_product, markup=3.0):
    from app.agents.store_manager import add_product_to_store
    try:
        name = cj_product.get("productNameEn", "")
        category = cj_product.get("categoryName", "Beauty")
        raw_price = cj_product.get("sellPrice", "0")
        if isinstance(raw_price, str) and "-" in raw_price:
            sell_price = float(raw_price.split("-")[0].strip())
        else:
            sell_price = float(raw_price)

        marked_up = sell_price * markup
        final_price = int(marked_up) + 0.99
        original_price = int(final_price * 1.4) + 0.99
        discount = round((1 - final_price / original_price) * 100)

        image_url = extract_image_url(cj_product)
        print(f"[CJ] Image: {image_url[:80] if image_url else 'NONE'}")

        variants = cj_product.get("variants", [])
        cj_vid = variants[0].get("vid", "") if variants else ""
        cj_sku = variants[0].get("variantSku", cj_product.get("productSku", "")) if variants else cj_product.get("productSku", "")

        # AI determines collection
        try:
            collection_id = get_or_create_collection(
                product_name=name,
                category_name=category,
                description=cj_product.get("description", "")
            )
        except Exception as e:
            print(f"[CJ] Collection lookup failed: {e}")
            collection_id = None

        product_data = {
            "name": name[:100],
            "brand": "Mikisi",
            "category": category,
            "description": cj_product.get("description", name),
            "original_price": original_price,
            "discount_percent": discount,
            "final_price": final_price,
            "image_url": image_url,
            "stock": 999,
            "shipping_days": 7,
            "supplier_name": "CJDropshipping",
            "supplier_url": f"https://cjdropshipping.com/product/{cj_product.get('pid', '')}",
            "cj_product_id": cj_product.get("pid", ""),
            "cj_sku": cj_sku,
            "collection_id": collection_id,
        }

        product, status = add_product_to_store(product_data)
        if status == "added":
            return {
                "success": True,
                "product": name,
                "cj_cost": sell_price,
                "store_price": final_price,
                "markup_applied": markup,
                "cj_vid": cj_vid,
                "collection_id": collection_id
            }
        return {"success": False, "reason": "Already exists"}
    except Exception as e:
        return {"success": False, "reason": str(e)}


def search_and_import(keyword, limit=5):
    print(f"[CJ] Searching: {keyword}")
    products = search_products(keyword, limit=limit)
    if not products:
        return {"imported": 0, "message": "No products found"}
    imported = []
    for product in products[:limit]:
        result = import_product_to_store(product)
        if result.get("success"):
            imported.append(result.get("product"))
    print(f"[CJ] Imported {len(imported)} products for '{keyword}'")
    return {"imported": len(imported), "products": imported, "keyword": keyword}


def import_product_by_id(pid, markup=3.0):
    print(f"[CJ] Fetching product: {pid}")
    product = get_product_details(pid)
    if not product:
        return {"success": False, "reason": "Product not found"}
    return import_product_to_store(product, markup)


def place_order_on_cj(cj_sku, customer_name, shipping_address, quantity=1):
    token = get_access_token()
    if not token:
        print(f"[CJ] Auth failed — cannot place order")
        return {"success": False, "reason": "CJ auth failed"}

    try:
        parts = [p.strip() for p in shipping_address.split(",")]
        street = parts[0] if len(parts) > 0 else ""
        city = parts[1] if len(parts) > 1 else ""
        state_zip = parts[2] if len(parts) > 2 else ""
        country = parts[3] if len(parts) > 3 else "US"
        state_zip_parts = state_zip.split(" ")
        state = state_zip_parts[0] if state_zip_parts else ""
        zipcode = state_zip_parts[1] if len(state_zip_parts) > 1 else ""

        name_parts = customer_name.split(" ")
        first_name = name_parts[0]
        last_name = name_parts[-1] if len(name_parts) > 1 else first_name

        country_code = country.strip()
        print(f"[CJ] Getting shipping methods for {cj_sku}")
        methods = get_shipping_methods(cj_sku, country_code)

        if methods:
            logistic_name = methods[0].get("logisticName", "")
            print(f"[CJ] Using shipping: {logistic_name}")
        else:
            logistic_name = "CJPacket Ordinary"
            print(f"[CJ] Defaulting to: {logistic_name}")

        time.sleep(1)

        payload = {
            "orderNumber": f"MIKISI-{int(datetime.now().timestamp())}",
            "fromCountryCode": "CN",
            "shippingCountry": country_code,
            "shippingCountryCode": country_code,
            "shippingCustomerName": f"{first_name} {last_name}".strip(),
            "shippingFirstName": first_name,
            "shippingLastName": last_name,
            "shippingAddress": street,
            "shippingCity": city,
            "shippingProvince": state,
            "shippingZip": zipcode,
            "shippingPhone": "0000000000",
            "logisticName": logistic_name,
            "products": [{"vid": cj_sku, "quantity": quantity}]
        }

        print(f"[CJ] Placing order: {json.dumps(payload)}")
        response = requests.post(
            f"{CJ_API_BASE}/shopping/order/createOrder",
            headers={
                "CJ-Access-Token": token,
                "Content-Type": "application/json"
            },
            json=payload,
            timeout=30
        )
        print(f"[CJ] Response status: {response.status_code}")
        data = response.json()
        print(f"[CJ] Response: {data}")

        if data.get("result"):
            cj_order_id = data.get("data", "")
            if isinstance(cj_order_id, dict):
                cj_order_id = cj_order_id.get("orderId", "")
            print(f"[CJ] ✅ Order placed: {cj_order_id}")
            return {"success": True, "cj_order_id": cj_order_id}
        else:
            print(f"[CJ] Order failed: {data.get('message')}")
            return {"success": False, "reason": data.get("message")}
    except Exception as e:
        print(f"[CJ] Order error: {e}")
        return {"success": False, "reason": str(e)}