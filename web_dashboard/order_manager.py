#!/usr/bin/env python3
"""
Order Manager for GTT Placement Workflow.
Implements PROMPT 4 mandatory simulation execution mode:
  - Check Kite state: orders, positions, holdings, active GTTs.
  - Check local dummy storage for active DUMMY- GTTs.
  - Block duplicates across restarts atomically.
  - NEVER call kite.place_gtt() or kite.place_order().
  - Round buy price and stoploss precisely to valid tick size multiples.
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Optional, Tuple

from web_dashboard.dummy_storage import DummyGTTStorage


def round_to_tick(price: Optional[float], tick_size: float = 0.05) -> float:
    """
    Round price to the nearest valid multiple of tick_size using Decimal arithmetic.
    Ensures precise decimal rounding without floating-point representation errors.
    """
    if price is None or price <= 0:
        return 0.0
    d_price = Decimal(str(round(price, 4)))
    d_tick = Decimal(str(tick_size))
    # Number of ticks = round(price / tick_size)
    ticks = (d_price / d_tick).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    rounded = (ticks * d_tick).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(rounded)


def compute_stoploss(buy_price: float, tick_size: float = 0.05) -> float:
    """Stoploss = 5% below buy price (buy_price * 0.95), rounded to tick size."""
    raw_sl = buy_price * 0.95
    return round_to_tick(raw_sl, tick_size)


class OrderManager:
    def __init__(self, dummy_storage: Optional[DummyGTTStorage] = None, kite_client: Optional[Any] = None):
        self.dummy_storage = dummy_storage or DummyGTTStorage()
        self.kite_client = kite_client

    def _fetch_kite_state(self) -> Dict[str, Any]:
        """Fetch Kite orders, positions, holdings, gtts if authenticated."""
        state = {
            "authenticated": False,
            "orders": [],
            "positions": [],
            "holdings": [],
            "gtts": [],
        }
        if not self.kite_client:
            return state

        kite = getattr(self.kite_client, "kite", None)
        is_auth = getattr(self.kite_client, "is_authenticated", lambda: False)()
        if not kite or not is_auth:
            return state

        state["authenticated"] = True
        try:
            state["orders"] = kite.orders() or []
        except Exception:
            pass
        try:
            pos = kite.positions() or {}
            state["positions"] = pos.get("net", []) if isinstance(pos, dict) else []
        except Exception:
            pass
        try:
            state["holdings"] = kite.holdings() or []
        except Exception:
            pass
        try:
            state["gtts"] = kite.get_gtts() or []
        except Exception:
            pass

        return state

    def check_candidate_state(
        self,
        candidate: Dict[str, Any],
        kite_state: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Evaluate candidate state against duplicate prevention rules:
          1. Invalid check (missing or invalid buy price)
          2. Dummy GTT storage check (active DUMMY- record exists)
          3. Kite holdings check (holding quantity > 0)
          4. Kite positions check (net position quantity > 0)
          5. Kite day orders check (open/pending current-day BUY CNC order)
          6. Kite active GTT check (active buy GTT in broker)
        Returns structured dict with state, trigger_id, message, can_submit.
        """
        symbol = str(candidate.get("symbol", "")).strip().upper()
        raw_buy = candidate.get("buy_price")
        raw_sl = candidate.get("stoploss")
        last_price = candidate.get("last_price")
        quantity = int(candidate.get("quantity", 1))

        if not raw_buy or float(raw_buy) <= 0:
            return {
                "symbol": symbol,
                "quantity": quantity,
                "buy_price": None,
                "stoploss": None,
                "last_price": last_price,
                "state": "invalid",
                "trigger_id": None,
                "stoploss_status": "unavailable",
                "message": "Buy price is unavailable. Cannot simulate order.",
                "can_submit": False,
            }

        buy_price = round_to_tick(float(raw_buy))
        stoploss = round_to_tick(float(raw_sl)) if raw_sl else compute_stoploss(buy_price)

        # 1. Check local persistent dummy storage
        active_dummy = self.dummy_storage.find_active_record(symbol)
        if active_dummy:
            return {
                "symbol": symbol,
                "quantity": quantity,
                "buy_price": buy_price,
                "stoploss": stoploss,
                "last_price": last_price,
                "state": "already_active",
                "trigger_id": active_dummy.get("trigger_id"),
                "stoploss_status": "planned_after_buy",
                "message": f"Active dummy buy GTT already exists ({active_dummy.get('trigger_id')}).",
                "can_submit": False,
            }

        # 2. Check Kite state if available
        if kite_state is None:
            kite_state = self._fetch_kite_state()

        if kite_state.get("authenticated"):
            # Check holdings
            for h in kite_state.get("holdings", []):
                h_sym = str(h.get("tradingsymbol", "")).strip().upper()
                if h_sym == symbol and float(h.get("quantity", 0)) > 0:
                    return {
                        "symbol": symbol,
                        "quantity": quantity,
                        "buy_price": buy_price,
                        "stoploss": stoploss,
                        "last_price": last_price,
                        "state": "blocked",
                        "trigger_id": None,
                        "stoploss_status": "planned_after_buy",
                        "message": f"Blocked: existing holding exists for {symbol} (qty: {h.get('quantity')}).",
                        "can_submit": False,
                    }

            # Check positions
            for p in kite_state.get("positions", []):
                p_sym = str(p.get("tradingsymbol", "")).strip().upper()
                if p_sym == symbol and float(p.get("quantity", 0)) > 0:
                    return {
                        "symbol": symbol,
                        "quantity": quantity,
                        "buy_price": buy_price,
                        "stoploss": stoploss,
                        "last_price": last_price,
                        "state": "blocked",
                        "trigger_id": None,
                        "stoploss_status": "planned_after_buy",
                        "message": f"Blocked: open net position exists for {symbol} (qty: {p.get('quantity')}).",
                        "can_submit": False,
                    }

            # Check current-day orders
            for o in kite_state.get("orders", []):
                o_sym = str(o.get("tradingsymbol", "")).strip().upper()
                o_exch = str(o.get("exchange", "")).strip().upper()
                o_type = str(o.get("transaction_type", "")).strip().upper()
                o_prod = str(o.get("product", "")).strip().upper()
                o_status = str(o.get("status", "")).strip().upper()

                if o_sym == symbol and o_exch == "NSE" and o_type == "BUY":
                    if o_prod in ("CNC", "NRML"):
                        if o_status not in ("CANCELLED", "REJECTED"):
                            return {
                                "symbol": symbol,
                                "quantity": quantity,
                                "buy_price": buy_price,
                                "stoploss": stoploss,
                                "last_price": last_price,
                                "state": "blocked",
                                "trigger_id": None,
                                "stoploss_status": "planned_after_buy",
                                "message": f"Blocked: active current-day BUY order exists for {symbol} (status: {o_status}).",
                                "can_submit": False,
                            }

            # Check active Kite GTTs
            for g in kite_state.get("gtts", []):
                g_status = str(g.get("status", "")).strip().lower()
                if g_status == "active":
                    cond = g.get("condition", {})
                    g_sym = str(cond.get("tradingsymbol", "")).strip().upper()
                    if g_sym == symbol:
                        return {
                            "symbol": symbol,
                            "quantity": quantity,
                            "buy_price": buy_price,
                            "stoploss": stoploss,
                            "last_price": last_price,
                            "state": "blocked",
                            "trigger_id": None,
                            "stoploss_status": "planned_after_buy",
                            "message": f"Blocked: active Kite GTT exists for {symbol} (ID: {g.get('id')}).",
                            "can_submit": False,
                        }

        # Clear for dummy simulation
        return {
            "symbol": symbol,
            "quantity": quantity,
            "buy_price": buy_price,
            "stoploss": stoploss,
            "last_price": last_price,
            "state": "clear",
            "trigger_id": None,
            "stoploss_status": "planned_after_buy",
            "message": "Clear: ready for simulated dummy GTT placement.",
            "can_submit": True,
        }

    def evaluate_all_states(self, orders: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Batch evaluate GTT candidate states for POST /api/algo-orders/gtt-state."""
        kite_state = self._fetch_kite_state()
        results = []
        for order in orders:
            res = self.check_candidate_state(order, kite_state)
            results.append(res)
        return results

    def simulate_live_gtts(
        self,
        orders: List[Dict[str, Any]],
        confirm_live: bool,
    ) -> Tuple[bool, List[Dict[str, Any]], str]:
        """
        Process dummy GTT simulation for POST /api/algo-orders/live-gtt.
        MANDATORY SAFETY:
          - Never calls kite.place_gtt() or kite.place_order().
          - Requires confirm_live == True.
          - Re-checks states server-side atomically.
          - Returns DUMMY- trigger IDs for created records.
        """
        if not confirm_live:
            return False, [], "Request rejected: confirm_live must be true to authorize dummy simulation."

        kite_state = self._fetch_kite_state()
        results: List[Dict[str, Any]] = []

        for order in orders:
            eval_res = self.check_candidate_state(order, kite_state)
            sym = eval_res["symbol"]
            state = eval_res["state"]

            if state == "already_active":
                results.append({
                    "symbol": sym,
                    "buy_status": "already_active",
                    "trigger_id": eval_res["trigger_id"],
                    "buy_price": eval_res["buy_price"],
                    "stoploss": eval_res["stoploss"],
                    "stoploss_status": "planned_after_buy",
                    "quantity": eval_res["quantity"],
                    "is_dummy": True,
                    "message": eval_res["message"],
                })
            elif state == "blocked":
                results.append({
                    "symbol": sym,
                    "buy_status": "skipped",
                    "trigger_id": None,
                    "buy_price": eval_res["buy_price"],
                    "stoploss": eval_res["stoploss"],
                    "stoploss_status": "planned_after_buy",
                    "quantity": eval_res["quantity"],
                    "is_dummy": False,
                    "message": eval_res["message"],
                })
            elif state == "invalid":
                results.append({
                    "symbol": sym,
                    "buy_status": "failed",
                    "trigger_id": None,
                    "buy_price": None,
                    "stoploss": None,
                    "stoploss_status": "unavailable",
                    "quantity": eval_res["quantity"],
                    "is_dummy": False,
                    "message": eval_res["message"],
                })
            elif state == "clear":
                # Create dummy record in persistent storage atomically
                buy_price = eval_res["buy_price"]
                stoploss = eval_res["stoploss"]
                success, record, msg = self.dummy_storage.create_dummy_gtt(
                    symbol=sym,
                    buy_price=buy_price,
                    stoploss=stoploss,
                    quantity=eval_res["quantity"],
                    tick_size=0.05,
                    last_price=eval_res.get("last_price"),
                )

                if success:
                    results.append({
                        "symbol": sym,
                        "buy_status": "success",
                        "trigger_id": record["trigger_id"],
                        "order_price": record["buy_price"],
                        "trigger_price": record["trigger_price"],
                        "buy_price": record["buy_price"],
                        "stoploss": record["stoploss"],
                        "stoploss_status": "planned_after_buy",
                        "quantity": record["quantity"],
                        "exchange": "NSE",
                        "product": "CNC",
                        "order_type": "LIMIT",
                        "is_dummy": True,
                        "message": msg,
                    })
                else:
                    results.append({
                        "symbol": sym,
                        "buy_status": "already_active",
                        "trigger_id": record.get("trigger_id"),
                        "buy_price": buy_price,
                        "stoploss": stoploss,
                        "stoploss_status": "planned_after_buy",
                        "quantity": eval_res["quantity"],
                        "is_dummy": True,
                        "message": msg,
                    })

        return True, results, "Dummy GTT simulation processed successfully."
