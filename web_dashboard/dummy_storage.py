#!/usr/bin/env python3
"""
Thread-safe persistent storage for Dummy GTT records.
Enforces the mandatory execution mode:
  - Simulate order placement only.
  - Never submit real orders or GTTs to broker.
  - Generates DUMMY- prefixed trigger IDs.
  - Atomic read/write with duplicate prevention.
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

DUMMY_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(DUMMY_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)
DUMMY_FILE = os.path.join(DATA_DIR, "dummy_gtts.json")

_lock = threading.Lock()


class DummyGTTStorage:
    def __init__(self, filepath: str = DUMMY_FILE):
        self.filepath = filepath
        self._ensure_file()

    def _ensure_file(self) -> None:
        with _lock:
            if not os.path.isfile(self.filepath):
                with open(self.filepath, "w", encoding="utf-8") as f:
                    json.dump({"records": [], "counter": 0}, f, indent=2)

    def _load(self) -> Dict[str, Any]:
        try:
            with open(self.filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {"records": [], "counter": 0}

    def _save(self, data: Dict[str, Any]) -> None:
        with open(self.filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def get_all_records(self) -> List[Dict[str, Any]]:
        with _lock:
            data = self._load()
            return data.get("records", [])

    def find_active_record(self, symbol: str, buy_price: Optional[float] = None) -> Optional[Dict[str, Any]]:
        """Check if an active dummy buy GTT exists for symbol or symbol+trigger."""
        with _lock:
            data = self._load()
            clean_sym = symbol.strip().upper()
            for r in data.get("records", []):
                if r.get("symbol") == clean_sym and r.get("status") in ("active", "success"):
                    if buy_price is None:
                        return r
                    if abs(float(r.get("buy_price", 0.0)) - float(buy_price)) < 0.01:
                        return r
            return None

    def create_dummy_gtt(
        self,
        symbol: str,
        buy_price: float,
        stoploss: float,
        quantity: int = 1,
        tick_size: float = 0.05,
        last_price: Optional[float] = None,
    ) -> Tuple[bool, Dict[str, Any], str]:
        """
        Atomically create a simulated dummy GTT record.
        Returns: (success: bool, record_or_existing: dict, message: str)
        """
        clean_sym = symbol.strip().upper()
        with _lock:
            data = self._load()
            records = data.get("records", [])
            counter = data.get("counter", 0)

            # Check if active dummy already exists for symbol
            for r in records:
                if r.get("symbol") == clean_sym and r.get("status") in ("active", "success"):
                    return False, r, "Skipped: dummy buy GTT already active."

            # Generate unique DUMMY- trigger ID
            counter += 1
            trigger_id = f"DUMMY-{clean_sym}-{counter:06d}"
            now_iso = datetime.now().isoformat()

            record = {
                "trigger_id": trigger_id,
                "symbol": clean_sym,
                "exchange": "NSE",
                "transaction_type": "BUY",
                "product": "CNC",
                "order_type": "LIMIT",
                "quantity": quantity,
                "buy_price": round(buy_price, 2),
                "trigger_price": round(buy_price, 2),
                "stoploss": round(stoploss, 2),
                "tick_size": tick_size,
                "last_price": last_price,
                "status": "active",
                "stoploss_status": "planned_after_buy",
                "created_at": now_iso,
                "is_dummy": True,
            }

            records.append(record)
            data["records"] = records
            data["counter"] = counter
            self._save(data)

            msg = "Dummy buy GTT created. No order sent to Kite. Stoploss planned after buy execution."
            return True, record, msg

    def clear_all_records(self) -> None:
        """Utility for test suite reset."""
        with _lock:
            self._save({"records": [], "counter": 0})
