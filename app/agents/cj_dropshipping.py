from dotenv import load_dotenv
load_dotenv()

import requests
import json
import os
from datetime import datetime
from sqlmodel import Session, select
from app.database import engine
from app.models.agent import AgentMemory

CJ_API_BASE = "https://developers.cjdropshipping.com/api2.0/v1"
CJ_EMAIL = os.getenv("CJ_EMAIL")
CJ_API_KEY = os.getenv("CJ_API_KEY")

def get_access_token():
    """Get CJ API access token"""
    try:
        response = requests.post(
            f"{CJ_API_BASE}/authentication/getAccessToken",
            json={
                "email": CJ_EMAIL,
                "password": CJ_API_KEY
            }
        )
        data = response.json()
        if data.get("result"):
            return data["data"]["accessToken"]
        print(f"[CJ] Auth failed: {data.get('message')}")
        return None
    except Exception as e:
        print(f"[CJ] Auth error: {e}")
        return None


def search_products(keyword, page=1, limit=20):
    """Search CJ products by keyword"""
    token = get_access_token()
    if not token:
        return None

    try:
        response = requests.get(
            f"{CJ_API_BASE}/product/list",
            headers={"CJ-Access-Token": token},
            params={
                "productNameEn": keyword,
                "pageNum": page,
                "pageSize": limit
            }
        )
        data = response.json()
        if data.get("result"):
            return data.get("data", {}).get("list", [])
        return []
    except Exception as e:
        print(f"[CJ] Search error: {e}")
        return []


def get_product_details(pid):
    """Get full product details from CJ"""
    token = get_access_token()
    if not token:
        return None

    try:
        response = requests.get(
            f"{CJ_API_BASE}/product/query",
            headers={"CJ-Access-Token": token},
            params={"pid": pid}
        )
        data = response.json()
        if data.get("result"):
            return data.get("data")
        return None
    except Exception as e:
        print(f"[CJ] Product detail error: {e}")
        return None


def import_product_to_store(cj_product):
    """Import a CJ product into Mikisi store"""
    from app.agents.store_manager import add_product_to_store

    try:
        name = cj_product.get("productNameEn", "")
        category = cj_product.get("categoryName", "Beauty")
        sell_price = float(cj_product.get("sellPrice", 0))
        original_price = round(sell_price * 1.8, 2)
        discount = round((1 - sell_price / original_price) * 100, 1)
        image_url = cj_product.get("productImage", "")
        
        product_data = {
            "name": name[:100],
            "brand": "Mikisi",
            "category": category,
            "description": cj_product.get("description", name),
            "original_price": original_price,
            "discount_percent": discount,
            "final_price": sell_price,
            "image_url": image_url,
            "stock": 999,
            "shipping_days": 7,
            "supplier_name": "CJDropshipping",
            "supplier_url": f"https://cjdropshipping.com/product/{cj_product.get('pid', '')}"
        }

        product, status = add_product_to_store(product_data)
        
        if status == "added":
            print(f"[CJ] ✅ Imported: {name[:60]}")
            return {"success": True, "product": name, "price": sell_price}
        else:
            return {"success": False, "reason": "Already exists"}

    except Exception as e:
        print(f"[CJ] Import error: {e}")
        return {"success": False, "reason": str(e)}


def search_and_import(keyword, limit=5):
    """Search CJ and import products to Mikisi"""
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
    return {
        "imported": len(imported),
        "products": imported,
        "keyword": keyword
    }

def import_product_by_id(pid):
    """Import a specific CJ product by its product ID"""
    print(f"[CJ] Fetching product: {pid}")
    product = get_product_details(pid)
    
    if not product:
        return {"success": False, "reason": "Product not found"}
    
    return import_product_to_store(product)