"""
Quick test script – run this on Mini2 to verify MT5 is working.
Usage: python scripts/test_mt5_connection.py
"""

import sys
import os

# Add parent dir to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import MetaTrader5 as mt5
except ImportError:
    print("❌ MetaTrader5 package not installed.")
    print("   Run: pip install MetaTrader5")
    sys.exit(1)


def test_connection():
    print("=" * 50)
    print("  MT5 Connection Test")
    print("=" * 50)

    # Initialize
    print("\n[1] Initializing MT5 terminal...")
    if not mt5.initialize():
        print(f"    ❌ Failed: {mt5.last_error()}")
        print("    Make sure MT5 terminal is installed and the path is correct.")
        return False

    version = mt5.version()
    print(f"    ✅ Connected: MT5 v{version[0]} build {version[1]} ({version[2]})")

    # Terminal info
    info = mt5.terminal_info()
    if info:
        print(f"\n[2] Terminal info:")
        print(f"    Path: {info.path}")
        print(f"    Connected: {info.connected}")
        print(f"    Community account: {info.community_account}")

    # Account info (if already logged in)
    account = mt5.account_info()
    if account:
        print(f"\n[3] Account info:")
        print(f"    Name: {account.name}")
        print(f"    Server: {account.server}")
        print(f"    Login: {account.login}")
        print(f"    Balance: {account.balance} {account.currency}")
        print(f"    Trade mode: {'Demo' if account.trade_mode == 0 else 'Real'}")

        # Try listing symbols
        symbols = mt5.symbols_get()
        if symbols:
            print(f"\n[4] Available symbols: {len(symbols)} total")
            # Show some gold/forex symbols
            gold = [s.name for s in symbols if "XAU" in s.name]
            if gold:
                print(f"    Gold symbols: {', '.join(gold[:10])}")

            forex = [s.name for s in symbols if s.name.endswith("USD")][:10]
            if forex:
                print(f"    USD pairs: {', '.join(forex)}")

        # Quick tick test
        from datetime import datetime, timedelta, timezone
        utc_to = datetime.now(timezone.utc)
        utc_from = utc_to - timedelta(hours=1)

        test_symbol = "XAUUSD"
        print(f"\n[5] Test tick download ({test_symbol}, last 1 hour)...")
        ticks = mt5.copy_ticks_range(test_symbol, utc_from, utc_to, mt5.COPY_TICKS_ALL)
        if ticks is not None and len(ticks) > 0:
            print(f"    ✅ Received {len(ticks):,} ticks")
            print(f"    First: bid={ticks[0][3]:.2f} ask={ticks[0][4]:.2f}")
            print(f"    Last:  bid={ticks[-1][3]:.2f} ask={ticks[-1][4]:.2f}")
        else:
            print(f"    ⚠️  No ticks (market may be closed): {mt5.last_error()}")

        # Quick rates test
        print(f"\n[6] Test rate download ({test_symbol} M1, last 1 hour)...")
        rates = mt5.copy_rates_range(test_symbol, mt5.TIMEFRAME_M1, utc_from, utc_to)
        if rates is not None and len(rates) > 0:
            print(f"    ✅ Received {len(rates):,} M1 candles")
            print(f"    Last close: {rates[-1][4]:.2f}")
        else:
            print(f"    ⚠️  No rates (market may be closed): {mt5.last_error()}")

    else:
        print("\n[3] ⚠️  No account logged in.")
        print("    Log in to your broker in MT5 terminal first,")
        print("    or the API will handle login per-request.")

    mt5.shutdown()
    print("\n" + "=" * 50)
    print("  ✅ Test complete!")
    print("=" * 50)
    return True


if __name__ == "__main__":
    test_connection()
