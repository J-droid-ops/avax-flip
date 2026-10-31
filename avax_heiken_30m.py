#!/usr/bin/env python3
"""
AVAXUSDT.P 30m — Heiken Ashi color-change watcher.

Signals when a Heiken Ashi candle closes with a DIFFERENT color than the
previous closed candle (green -> red or red -> green). This is the
classic Heiken Ashi reversal signal.

Only acts on closed 30m candles. State tracks last notified bar so each
change is announced exactly once. Empty stdout = nothing new.
"""
import json
import os
import sys
import urllib.request
import datetime as dt

# ---------------------------------------------------------------- config
SYMBOL = "AVAXUSDT"
INTERVAL = "30m"
STATE = "state/avax_heiken_30m.json"
FAPI = "https://data-api.binance.vision/api/v3"
BARS = 50  # enough for HA convergence
U = dt.timezone.utc


# ---------------------------------------------------------------- data
def fetch_klines(limit=500):
    url = f"{FAPI}/klines?symbol={SYMBOL}&interval={INTERVAL}&limit={limit}"
    with urllib.request.urlopen(url, timeout=25) as r:
        return json.load(r)


def heiken_ashi(opens, highs, lows, closes):
    """Return list of (ha_open, ha_close, ha_high, ha_low) and color per bar.
    color: 'green' if ha_close > ha_open else 'red'
    """
    n = len(closes)
    ha_open = [0.0] * n
    ha_close = [0.0] * n
    ha_high = [0.0] * n
    ha_low = [0.0] * n
    colors = [""] * n

    # first bar: seed with original open/close
    ha_close[0] = (opens[0] + highs[0] + lows[0] + closes[0]) / 4.0
    ha_open[0] = (opens[0] + closes[0]) / 2.0
    ha_high[0] = highs[0]
    ha_low[0] = lows[0]
    colors[0] = "green" if ha_close[0] > ha_open[0] else "red"

    for i in range(1, n):
        ha_close[i] = (opens[i] + highs[i] + lows[i] + closes[i]) / 4.0
        ha_open[i] = (ha_open[i - 1] + ha_close[i - 1]) / 2.0
        ha_high[i] = max(highs[i], ha_open[i], ha_close[i])
        ha_low[i] = min(lows[i], ha_open[i], ha_close[i])
        colors[i] = "green" if ha_close[i] > ha_open[i] else "red"

    return ha_open, ha_close, ha_high, ha_low, colors


# ---------------------------------------------------------------- state
def load_state():
    try:
        with open(STATE) as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(s):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    with open(STATE, "w") as f:
        json.dump(s, f, indent=2)


# ---------------------------------------------------------------- main
def main():
    try:
        kl = fetch_klines()
    except Exception as e:
        print("", end="")
        return 0

    if len(kl) < 5:
        print("", end="")
        return 0

    ts_ms = [k[0] for k in kl]
    opens = [float(k[1]) for k in kl]
    highs = [float(k[2]) for k in kl]
    lows = [float(k[3]) for k in kl]
    closes = [float(k[4]) for k in kl]

    _, _, _, _, colors = heiken_ashi(opens, highs, lows, closes)

    # last CLOSED candle = last element whose close time has passed
    now_ms = int(dt.datetime.now(tz=U).timestamp() * 1000)
    closed = [i for i in range(len(kl)) if int(kl[i][6]) <= now_ms]
    if not closed:
        print("", end="")
        return 0
    last_closed = closed[-1]

    state = load_state()
    last_seen = state.get("last_notified_bar")
    cur_bar = ts_ms[last_closed]

    # FIRST RUN: prime baseline, stay silent
    if last_seen is None:
        state["last_notified_bar"] = cur_bar - 1800000  # 30 min back
        state["last_checked_utc"] = dt.datetime.now(tz=U).isoformat(timespec="seconds")
        state["last_close"] = closes[last_closed]
        state["last_color"] = colors[last_closed]
        state["primed_utc"] = dt.datetime.now(tz=U).isoformat(timespec="seconds")
        save_state(state)
        print("", end="")
        return 0

    # nothing new
    if last_seen == cur_bar:
        print("", end="")
        return 0

    # detect color changes on closed bars newer than last_seen
    fresh = []
    for i in closed:
        if ts_ms[i] <= last_seen:
            continue
        if i < 1:
            continue
        if colors[i] != colors[i - 1]:
            fresh.append(i)

    state["last_notified_bar"] = cur_bar
    state["last_checked_utc"] = dt.datetime.now(tz=U).isoformat(timespec="seconds")
    state["last_close"] = closes[last_closed]
    state["last_color"] = colors[last_closed]

    if not fresh:
        save_state(state)
        print("", end="")
        return 0

    # announce newest color change only (count backlog if multiple)
    newest = fresh[-1]
    bar_close = dt.datetime.fromtimestamp(int(kl[newest][6]) / 1000, U)
    px = closes[newest]
    new_color = colors[newest]
    prev_color = colors[newest - 1]

    if new_color == "green":
        arrow = "🟢 GREEN"
        meaning = "bullish reversal (HA shifted to uptrend)"
    else:
        arrow = "🔴 RED"
        meaning = "bearish reversal (HA shifted to downtrend)"

    out = []
    out.append(f"{arrow} Heiken Ashi flip — {SYMBOL}.P  30m")
    out.append(f"Bar close: {bar_close.strftime('%Y-%m-%d %H:%M')} UTC")
    out.append(f"Price: {px:.4f}   {prev_color} -> {new_color}")
    out.append(f"Meaning: {meaning}")
    if len(fresh) > 1:
        out.append(f"(+{len(fresh)-1} earlier flip(s) missed while offline)")

    state["last_notified_signal"] = {
        "bar_close_utc": bar_close.isoformat(timespec="minutes"),
        "price": round(px, 4),
        "from_color": prev_color,
        "to_color": new_color,
    }
    save_state(state)

    print("\n".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
