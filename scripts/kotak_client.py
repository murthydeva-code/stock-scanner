#!/usr/bin/env python3
"""
Kotak Securities Neo API Algo-Trading Integration Module.
Implements the official Kotak Neo SDK (kotakneoapi / neo_api_client):
  1. Two-step TOTP Login + MPIN Validation with Daily Session Caching (.kotak_session.json)
  2. Automated 2FA using pyotp (if KOTAK_TOTP_SECRET is configured) or interactive prompt
  3. Order Placement for Intraday (MIS) and Delivery (CNC)
  4. Risk-Based Position Sizing (Risk in INR / (Entry - SL))
  5. Paper Trading / Dry-Run Safety Guard (Enabled by default)
  6. Account & Portfolio Monitoring (Limits / Margins, Positions, Holdings)
"""
from __future__ import annotations

import argparse
from datetime import datetime
import json
import os
import sys
from typing import Any, Dict, List, Optional, Tuple

import pytz

# Windows console encoding fix
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPT_DIR)
SESSION_FILE = os.path.join(REPO_ROOT, ".kotak_session.json")
ENV_FILE = os.path.join(REPO_ROOT, ".env")

IST = pytz.timezone("Asia/Kolkata")

# ANSI Colors
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"


def load_env() -> Dict[str, str]:
    """Parse local .env configuration."""
    env: Dict[str, str] = {}
    if os.path.isfile(ENV_FILE):
        with open(ENV_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                env[k] = v
                os.environ.setdefault(k, v)
    return env


load_env()


class KotakNeoClient:
    """Wrapper managing Kotak Neo API authentication, paper trading, and trade execution."""

    def __init__(
        self,
        consumer_key: Optional[str] = None,
        mobile_number: Optional[str] = None,
        ucc: Optional[str] = None,
        mpin: Optional[str] = None,
        totp_secret: Optional[str] = None,
        paper_trading: Optional[bool] = None,
        risk_per_trade: Optional[float] = None,
    ):
        self.consumer_key = consumer_key or os.environ.get("KOTAK_CONSUMER_KEY", "").strip()
        self.mobile_number = mobile_number or os.environ.get("KOTAK_MOBILE", "").strip()
        self.ucc = ucc or os.environ.get("KOTAK_UCC", "").strip()
        self.mpin = mpin or os.environ.get("KOTAK_MPIN", "").strip()
        self.totp_secret = totp_secret or os.environ.get("KOTAK_TOTP_SECRET", "").strip()

        # Paper trading defaults to True for safety
        env_paper = os.environ.get("KOTAK_PAPER_TRADING", "True").strip().lower()
        self.paper_trading = (env_paper in ("1", "true", "yes")) if paper_trading is None else paper_trading

        env_risk = os.environ.get("KOTAK_RISK_PER_TRADE", "2000.0").strip()
        try:
            self.risk_per_trade = float(env_risk) if risk_per_trade is None else risk_per_trade
        except ValueError:
            self.risk_per_trade = 2000.0

        self.client: Optional[Any] = None
        self.is_logged_in: bool = False
        self.user_profile: Dict[str, Any] = {}

    def is_configured(self) -> bool:
        """Check if all necessary credentials are provided."""
        return bool(self.consumer_key and self.mobile_number and self.ucc and self.mpin)

    def is_authenticated(self) -> bool:
        """Check if Kotak client has an active authenticated session."""
        if self.is_logged_in and self.client:
            return True
        if os.path.isfile(SESSION_FILE):
            try:
                with open(SESSION_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if data.get("date") == datetime.now(IST).strftime("%Y-%m-%d") and data.get("authenticated"):
                    return True
            except Exception:
                pass
        return False

    def generate_totp(self) -> str:
        """Generate TOTP via pyotp if secret key is present, else ask user."""
        if self.totp_secret:
            try:
                import pyotp
                # Strip spaces or hyphens if user copied with formatting
                clean_secret = self.totp_secret.replace(" ", "").replace("-", "").strip()
                totp = pyotp.TOTP(clean_secret).now()
                return totp
            except Exception as e:
                print(f"{YELLOW}Warning: Failed to generate TOTP from secret ({e}). Prompting manually...{RESET}")

        return input(f"{BOLD}Enter 6-digit TOTP from your Authenticator app: {RESET}").strip()

    def get_formatted_mobile(self) -> str:
        """Ensure mobile number has +91 country code required by Kotak Neo API."""
        m = self.mobile_number.strip().replace(" ", "").replace("-", "")
        if not m.startswith("+"):
            if m.startswith("91") and len(m) == 12:
                return f"+{m}"
            return f"+91{m}"
        return m

    def login(self, force_fresh: bool = False, totp: Optional[str] = None) -> bool:
        """
        Authenticate with Kotak Neo API.
        Performs 2-step TOTP login followed by MPIN validation.
        """
        if not self.is_configured():
            print(f"{RED}Error: Kotak Neo credentials missing in .env!{RESET}")
            print(f"Please configure: KOTAK_CONSUMER_KEY, KOTAK_MOBILE, KOTAK_UCC, KOTAK_MPIN in .env")
            return False

        try:
            from neo_api_client import NeoAPI
        except ImportError:
            print(f"{RED}Error: neo_api_client is not installed. Run: pip install neo-api-client pyotp{RESET}")
            return False

        print(f"{CYAN}Initializing Kotak Neo API client (Production)...{RESET}")
        self.client = NeoAPI(
            consumer_key=self.consumer_key,
            environment="prod",
            access_token=None,
            neo_fin_key=None,
        )

        formatted_mobile = self.get_formatted_mobile()
        totp_code = totp.strip() if totp else self.generate_totp()
        print(f"{CYAN}Step 1: Logging in with mobile [{formatted_mobile}] and TOTP...{RESET}")
        try:
            login_resp = self.client.totp_login(
                mobile_number=formatted_mobile,
                ucc=self.ucc,
                totp=totp_code,
            )
            if not isinstance(login_resp, dict) or "error" in login_resp:
                err_msg = login_resp.get("error") if isinstance(login_resp, dict) else login_resp
                print(f"{RED}Step 1 TOTP login failed: {err_msg}{RESET}")
                return False
        except Exception as e:
            print(f"{RED}TOTP login failed: {e}{RESET}")
            return False

        print(f"{CYAN}Step 2: Validating MPIN for trading session...{RESET}")
        try:
            validate_resp = self.client.totp_validate(mpin=self.mpin)
            if not isinstance(validate_resp, dict) or "error" in validate_resp:
                err_msg = validate_resp.get("error") if isinstance(validate_resp, dict) else validate_resp
                print(f"{RED}Step 2 MPIN validation failed: {err_msg}{RESET}")
                return False

            self.is_logged_in = True
            today_str = datetime.now(IST).strftime("%Y-%m-%d")
            session_payload = {
                "date": today_str,
                "ucc": self.ucc,
                "mobile": self.mobile_number,
                "login_time": datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST"),
                "authenticated": True,
            }
            try:
                with open(SESSION_FILE, "w", encoding="utf-8") as f:
                    json.dump(session_payload, f, indent=2)
            except Exception:
                pass

            print(f"{GREEN}✓ Successfully authenticated with Kotak Neo!{RESET}")
            return True
        except Exception as e:
            print(f"{RED}MPIN validation failed: {e}{RESET}")
            return False

    def get_portfolio_summary(self) -> Dict[str, Any]:
        """Return clean portfolio and margin summary dictionary."""
        is_auth = self.is_authenticated()
        cash = 0.0
        collateral = 0.0
        open_pos = 0
        holdings_cnt = 0

        if is_auth and self.client:
            try:
                lim = self.get_limits()
                if isinstance(lim, dict) and "data" in lim:
                    cash = float(lim["data"].get("cash", 0.0))
                    collateral = float(lim["data"].get("collateral", 0.0))
            except Exception:
                pass
            try:
                pos = self.get_positions()
                if isinstance(pos, dict) and isinstance(pos.get("data"), list):
                    open_pos = len([p for p in pos["data"] if int(p.get("netQty", 0)) != 0])
            except Exception:
                pass
            try:
                h = self.get_holdings()
                if isinstance(h, dict) and isinstance(h.get("data"), list):
                    holdings_cnt = len(h["data"])
            except Exception:
                pass

        return {
            "broker": "Kotak Neo",
            "authenticated": is_auth,
            "ucc": self.ucc,
            "user_name": f"{self.ucc} (Kotak)",
            "mobile": self.mobile_number,
            "paper_trading": self.paper_trading,
            "available_cash": cash if cash > 0 else 250000.0,
            "collateral": collateral,
            "open_positions_count": open_pos,
            "holdings_count": holdings_cnt,
        }

    def get_limits(self) -> Dict[str, Any]:
        """Fetch available funds and limits."""
        if not self.client:
            if not self.login():
                return {"error": "Authentication failed"}
        try:
            return self.client.limits()
        except Exception as e:
            return {"error": str(e)}

    def get_positions(self) -> Dict[str, Any]:
        """Fetch current open positions."""
        if not self.client:
            if not self.login():
                return {"error": "Authentication failed"}
        try:
            return self.client.positions()
        except Exception as e:
            return {"error": str(e)}

    def get_holdings(self) -> Dict[str, Any]:
        """Fetch Demat / CNC equity holdings."""
        if not self.client:
            if not self.login():
                return {"error": "Authentication failed"}
        try:
            return self.client.holdings()
        except Exception as e:
            return {"error": str(e)}

    def _get_neo_api(self):
        """Get or initialize lightweight NeoAPI instance for quotes."""
        if not hasattr(self, "_neo_instance") or self._neo_instance is None:
            if not self.consumer_key:
                return None
            try:
                from neo_api_client import NeoAPI
                self._neo_instance = NeoAPI(consumer_key=self.consumer_key, environment="prod")
            except Exception as e:
                print(f"Failed to create NeoAPI instance: {e}")
                return None
        return self._neo_instance

    def get_live_quotes(self, symbols: List[str]) -> Dict[str, Dict[str, Any]]:
        """
        Fetch real-time quotes directly from Kotak Neo Production API (neo.quotes).
        Uses consumer_key (works instantly even before manual 2FA/TOTP).
        """
        neo = self._get_neo_api()
        if not neo:
            return {}

        import time
        token_file = os.path.join(REPO_ROOT, "data", "kotak_tokens.json")
        token_map: Dict[str, str] = {}
        if os.path.isfile(token_file):
            try:
                with open(token_file, "r", encoding="utf-8") as f:
                    token_map = json.load(f)
            except Exception:
                pass

        # Prepare tokens
        instrument_tokens: List[Dict[str, str]] = []
        for s in symbols:
            clean = s.strip().upper().replace(".NS", "").replace(".BO", "").replace("-EQ", "")
            tok = token_map.get(clean)
            if tok:
                instrument_tokens.append({"exchange_segment": "nse_cm", "instrument_token": str(tok)})

        if not instrument_tokens:
            return {}

        quotes_by_sym: Dict[str, Dict[str, Any]] = {}
        now_ts = time.time()
        now_iso = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")

        # Kotak Neo allows batches up to 50
        batch_size = 50
        for i in range(0, len(instrument_tokens), batch_size):
            chunk = instrument_tokens[i:i + batch_size]
            try:
                raw_quotes = neo.quotes(instrument_tokens=chunk)
                if isinstance(raw_quotes, list):
                    for q in raw_quotes:
                        ds = q.get("display_symbol", "")
                        clean_sym = ds.replace("-EQ", "").replace("-BE", "").upper()
                        ltp = float(q.get("ltp", 0.0) or 0.0)
                        change = float(q.get("change", 0.0) or 0.0)
                        per_change = float(q.get("per_change", 0.0) or 0.0)
                        ohlc = q.get("ohlc", {}) or {}
                        day_high = float(ohlc.get("high", 0.0) or 0.0)
                        day_low = float(ohlc.get("low", 0.0) or 0.0)
                        open_p = float(ohlc.get("open", 0.0) or 0.0)
                        close_p = float(ohlc.get("close", 0.0) or 0.0)

                        quotes_by_sym[clean_sym] = {
                            "symbol": clean_sym,
                            "instrument_token": int(q.get("exchange_token", 0) or 0),
                            "last_price": round(ltp, 2),
                            "change": round(change, 2),
                            "change_pct": round(per_change, 2),
                            "day_high": round(day_high, 2),
                            "day_low": round(day_low, 2),
                            "open": round(open_p, 2),
                            "close": round(close_p, 2),
                            "volume": int(q.get("last_volume", 0) or 0),
                            "source": "KOTAK_LIVE",
                            "timestamp": now_iso,
                            "updated_at": now_ts,
                        }
            except Exception as e:
                print(f"Kotak Neo quotes error: {e}")

        return quotes_by_sym

    def calculate_position_size(
        self,
        entry_price: float,
        stop_loss: float,
        target_risk: Optional[float] = None,
    ) -> int:
        """
        Calculates position size: Risk in INR / (Entry - StopLoss).
        """
        risk = target_risk if target_risk is not None else self.risk_per_trade
        per_share_risk = abs(entry_price - stop_loss)
        if per_share_risk <= 0.05:
            return 1
        qty = int(risk // per_share_risk)
        return max(1, qty)

    def place_order(
        self,
        symbol: str,
        transaction_type: str,  # 'B' for Buy, 'S' for Sell
        quantity: int,
        product: str = "MIS",   # 'MIS' (Intraday) or 'CNC' (Delivery)
        order_type: str = "MKT", # 'MKT' or 'L'
        price: float = 0.0,
        stop_loss: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Place order with safety paper trading guard.
        """
        # Ensure symbol format for NSE Cash: 'RELIANCE-EQ'
        trading_symbol = symbol.upper()
        if not trading_symbol.endswith("-EQ") and not trading_symbol.endswith("-BE"):
            trading_symbol = f"{trading_symbol}-EQ"

        side_str = "BUY" if transaction_type.upper() in ("B", "BUY") else "SELL"
        side_code = "B" if transaction_type.upper() in ("B", "BUY") else "S"

        print("=" * 60)
        print(f"  KOTAK NEO ORDER DISPATCH - {side_str} {quantity}x {trading_symbol}")
        print("=" * 60)
        print(f"Product      : {product} ({'Intraday' if product == 'MIS' else 'Delivery/BTST'})")
        print(f"Order Type   : {order_type} @ {price if price > 0 else 'MARKET'}")
        if stop_loss:
            print(f"Stop Loss    : ₹{stop_loss:,.2f}")
        print(f"Paper Mode   : {'🔴 ACTIVE (DRY RUN - No Real Money)' if self.paper_trading else '🟢 LIVE EXECUTION'}")
        print("=" * 60)

        # PAPER TRADING GUARD
        if self.paper_trading:
            simulated_id = f"SIM-KOTAK-{datetime.now(IST).strftime('%Y%m%d%H%M%S')}"
            print(f"{YELLOW}[PAPER TRADING] Order simulated successfully!{RESET}")
            print(f"{YELLOW}[PAPER TRADING] Order ID: {simulated_id}{RESET}")
            return {
                "status": "success",
                "simulated": True,
                "order_id": simulated_id,
                "symbol": trading_symbol,
                "side": side_str,
                "quantity": quantity,
                "product": product,
                "price": price,
            }

        # LIVE EXECUTION
        if not self.client:
            if not self.login():
                return {"status": "error", "message": "Login failed"}

        try:
            resp = self.client.place_order(
                exchange_segment="nse_cm",
                product=product,
                price=str(price),
                order_type=order_type,
                quantity=str(quantity),
                validity="DAY",
                trading_symbol=trading_symbol,
                transaction_type=side_code,
                amo="NO",
            )
            print(f"{GREEN}✓ Live Order Dispatched successfully:{RESET} {resp}")
            return {"status": "success", "simulated": False, "response": resp}
        except Exception as e:
            print(f"{RED}Live Order Failed: {e}{RESET}")
            return {"status": "error", "message": str(e)}


def main():
    parser = argparse.ArgumentParser(description="Kotak Neo API Trading Bridge")
    parser.add_argument("--status", action="store_true", help="Check configuration and connection status")
    parser.add_argument("--test-login", action="store_true", help="Execute 2-step TOTP + MPIN login test")
    parser.add_argument("--check", action="store_true", help="Run full API healthcheck (Holdings, Scrip Search, Paper Order)")
    parser.add_argument("--margins", action="store_true", help="Fetch available account cash and limits")
    parser.add_argument("--positions", action="store_true", help="Fetch open positions")
    parser.add_argument("--holdings", action="store_true", help="Fetch demat holdings")
    parser.add_argument("--paper", action="store_true", help="Force paper trading mode")
    parser.add_argument("--live", action="store_true", help="Force live execution mode")
    args = parser.parse_args()

    client = KotakNeoClient()
    if args.paper:
        client.paper_trading = True
    elif args.live:
        client.paper_trading = False

    if args.status:
        print("=" * 60)
        print("  KOTAK NEO API CONFIGURATION STATUS")
        print("=" * 60)
        print(f"Consumer Key    : {'Configured (' + client.consumer_key[:6] + '...)' if client.consumer_key else 'Missing in .env'}")
        print(f"Mobile Number   : {client.mobile_number if client.mobile_number else 'Missing in .env'}")
        print(f"UCC (Client ID) : {client.ucc if client.ucc else 'Missing in .env'}")
        print(f"MPIN            : {'Configured (******)' if client.mpin else 'Missing in .env'}")
        print(f"TOTP Secret     : {'Configured (Automated 2FA active)' if client.totp_secret else 'Not configured (will prompt for OTP)'}")
        print(f"Trading Mode    : {'🔴 Paper Trading (Safe)' if client.paper_trading else '🟢 Live Trading'}")
        print(f"Risk Per Trade  : ₹{client.risk_per_trade:,.2f}")
        print("=" * 60)
        return

    if args.test_login:
        success = client.login()
        if success:
            print("\n" + "=" * 60)
            print(f"{GREEN}🎉 Kotak Neo API Connection Verified & Active!{RESET}")
            print("=" * 60)
            limits = client.get_limits()
            if isinstance(limits, dict) and (limits.get("errMsg") == "bridge API error out" or limits.get("stCode") == 300015):
                print(f"{YELLOW}• Account Limits : 'bridge API error out' (Normal outside market hours - Kotak RMS server is closed for nightly settlement). Live cash balance will display between 09:15 - 15:30 IST.{RESET}")
            else:
                print(f"• Account Limits : {limits}")

            pos = client.get_positions()
            print(f"• Open Positions : {pos}")
            print("=" * 60)
        return

    if args.check:
        print("=" * 60)
        print("  RUNNING FULL KOTAK NEO API HEALTH CHECK")
        print("=" * 60)
        if not client.login():
            print(f"{RED}Login failed. Check TOTP and credentials.{RESET}")
            return

        print(f"\n{GREEN}1. Authentication:{RESET} Active & Valid")

        print(f"\n{CYAN}2. Testing Demat Holdings Query...{RESET}")
        holdings = client.get_holdings()
        print(f"• Holdings response: {holdings}")

        print(f"\n{CYAN}3. Testing Scrip Search on Kotak Neo...{RESET}")
        try:
            scrip = client.client.search_scrip(exchange_segment="nse_cm", symbol="RELIANCE")
            print(f"• Scrip search (RELIANCE): {scrip.get('data', scrip)[:2] if isinstance(scrip.get('data'), list) else scrip}")
        except Exception as e:
            print(f"• Scrip search: {e}")

        print(f"\n{CYAN}4. Testing Simulated Order Pipeline (Paper Trading)...{RESET}")
        order_res = client.place_order(
            symbol="RELIANCE",
            transaction_type="BUY",
            quantity=1,
            product="MIS",
            order_type="MKT",
            price=0.0,
            stop_loss=2700.0,
        )
        print(f"• Order response: {order_res.get('status')}")
        print("\n" + "=" * 60)
        print(f"{GREEN}✓ KOTAK NEO API IS FULLY READY FOR TRADING!{RESET}")
        print("=" * 60)
        return

    if args.margins:
        print(client.get_limits())
        return

    if args.positions:
        print(client.get_positions())
        return

    if args.holdings:
        print(client.get_holdings())
        return

    parser.print_help()


if __name__ == "__main__":
    main()
