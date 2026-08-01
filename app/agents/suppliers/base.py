from abc import ABC, abstractmethod
from typing import Optional


class SupplierAdapter(ABC):
    """
    Base interface every supplier must implement.
    CJ, Alibaba, any future supplier — all speak this language.
    """

    @abstractmethod
    def search(self, keyword: str, limit: int = 20) -> list:
        """
        Search for products by keyword.
        Returns list of products in Mikisi standard format.
        """
        pass

    @abstractmethod
    def get_product(self, product_id: str) -> Optional[dict]:
        """
        Get full product details by supplier product ID.
        Returns product in Mikisi standard format.
        """
        pass

    @abstractmethod
    def place_order(self, product_id: str, customer: dict, address: dict, quantity: int = 1) -> dict:
        """
        Place an order with the supplier.
        Returns order confirmation with supplier order ID.
        """
        pass

    @abstractmethod
    def get_tracking(self, order_id: str) -> dict:
        """
        Get tracking information for an order.
        Returns tracking status and details.
        """
        pass

    def standard_product(self, **kwargs) -> dict:
        """
        Standard product format all adapters must return.
        This is what Mikisi understands — not supplier-specific fields.
        """
        return {
            "supplier_product_id": kwargs.get("supplier_product_id", ""),
            "supplier_variant_id": kwargs.get("supplier_variant_id", ""),
            "name": kwargs.get("name", ""),
            "category": kwargs.get("category", ""),
            "description": kwargs.get("description", ""),
            "cost_price": kwargs.get("cost_price", 0.0),
            "image_url": kwargs.get("image_url", ""),
            "stock": kwargs.get("stock", 999),
            "shipping_days": kwargs.get("shipping_days", 15),
            "supplier_name": kwargs.get("supplier_name", ""),
            "supplier_url": kwargs.get("supplier_url", ""),
            "variants": kwargs.get("variants", []),
        }

    def standard_order(self, **kwargs) -> dict:
        """
        Standard order response format. success/supplier_order_id/reason are
        the required core fields every caller can rely on; any extra kwargs
        (e.g. Silverbene's real cost-detail fields — see place_order()) pass
        through as-is so a supplier can enrich its response without every
        other adapter needing to know about those fields.
        """
        return {
            "success": kwargs.get("success", False),
            "supplier_order_id": kwargs.get("supplier_order_id", ""),
            "reason": kwargs.get("reason", ""),
            **{k: v for k, v in kwargs.items() if k not in ("success", "supplier_order_id", "reason")},
        }

    def standard_tracking(self, **kwargs) -> dict:
        """
        Standard tracking response format.
        """
        return {
            "order_id": kwargs.get("order_id", ""),
            "status": kwargs.get("status", "unknown"),
            "tracking_number": kwargs.get("tracking_number", ""),
            "carrier": kwargs.get("carrier", ""),
            "estimated_delivery": kwargs.get("estimated_delivery", ""),
            "last_update": kwargs.get("last_update", ""),
        }