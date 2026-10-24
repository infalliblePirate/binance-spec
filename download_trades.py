#!/usr/bin/env python3
"""Save Binance futures trades around every Upbit listing from listings.js into data/.

For each listing it downloads the daily aggTrades archive from data.binance.vision (or the
Binance API for the last two days), keeps only the window around the listing and deletes the rest.
"""

import io
import json
import time
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent
DATA = ROOT / "data"
LISTINGS = ROOT / "listings.js"
ARCHIVE_URL = "https://data.binance.vision/data/futures/um/daily/aggTrades/{symbol}/{symbol}-aggTrades-{day}.zip"
API_URL = "https://fapi.binance.com/fapi/v1/aggTrades"
BEFORE_MS = 5_000
AFTER_MS = 65_000
API_DAYS = 2


def read_listings() -> list[dict]:
    text = LISTINGS.read_text(encoding="utf-8")
    return json.loads(text[text.index("["): text.rindex("]") + 1])


def key_of(listing: dict) -> str:
    return f"{listing['token']}_{listed_ms(listing)}"


def listed_ms(listing: dict) -> int:
    return int(datetime.fromisoformat(listing["listedAt"]).timestamp() * 1000)


def get(url: str) -> bytes:
    for attempt in range(5):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "binance-specs"}), timeout=300) as response:
                return response.read()
        except urllib.error.HTTPError as error:
            if error.code == 404:
                raise
            if error.code in (418, 429):
                time.sleep(30)
                continue
            time.sleep(2)
        except OSError:
            time.sleep(2)
    raise RuntimeError(f"failed to download {url}")


def from_archive(symbol: str, day: str, start: int, end: int) -> list[list]:
    blob = get(ARCHIVE_URL.format(symbol=symbol, day=day))
    rows = []
    with zipfile.ZipFile(io.BytesIO(blob)) as archive, archive.open(archive.namelist()[0]) as csv:
        for line in io.TextIOWrapper(csv):
            parts = line.strip().split(",")
            if not parts[0].isdigit():
                continue
            ts = int(parts[5])
            ts = ts // 1000 if ts > 10**14 else ts
            if ts < start:
                continue
            if ts > end:
                break
            rows.append([ts, float(parts[1]), float(parts[2]), 1 if parts[6].strip().lower() == "true" else 0])
    return rows


def from_api(symbol: str, start: int, end: int) -> list[list]:
    rows = []
    page = json.loads(get(f"{API_URL}?symbol={symbol}&startTime={start}&endTime={end}&limit=1000"))
    while page:
        rows += [[t["T"], float(t["p"]), float(t["q"]), 1 if t["m"] else 0] for t in page if t["T"] <= end]
        if page[-1]["T"] >= end or len(page) < 1000:
            break
        time.sleep(0.5)
        page = json.loads(get(f"{API_URL}?symbol={symbol}&fromId={page[-1]['a'] + 1}&limit=1000"))
    return rows


def write_supply() -> int:
    """Circulating supply from CoinGecko, kept only when its price matches Binance (same coin, not a namesake)."""
    tokens = sorted({p.stem.split("_")[0] for p in DATA.glob("*_*.js")})
    binance = {t["symbol"]: float(t["price"]) for t in json.loads(get("https://fapi.binance.com/fapi/v1/ticker/price"))}
    supply = {}
    for i in range(0, len(tokens), 40):
        symbols = ",".join(t.lower() for t in tokens[i:i + 40])
        coins = json.loads(get(f"https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&per_page=250&symbols={symbols}"))
        for coin in sorted(coins, key=lambda c: -(c.get("market_cap") or 0)):
            token, binance_price = coin["symbol"].upper(), binance.get(coin["symbol"].upper() + "USDT")
            if token in supply or not coin.get("circulating_supply") or not coin.get("current_price") or not binance_price:
                continue
            if 0.5 < coin["current_price"] / binance_price < 2:
                supply[token] = coin["circulating_supply"]
        time.sleep(3)
    (DATA / "supply.js").write_text("window.SUPPLY = " + json.dumps(supply, indent=1) + ";\n")
    return len(supply)


def write_index() -> int:
    available = sorted(p.stem for p in DATA.glob("*_*.js"))
    (DATA / "index.js").write_text("window.TRADE_FILES = " + json.dumps(available) + ";\n")
    return len(available)


def main() -> None:
    DATA.mkdir(exist_ok=True)
    listings = read_listings()
    now_ms = int(time.time() * 1000)
    saved = skipped = 0

    for listing in listings:
        key = key_of(listing)
        path = DATA / f"{key}.js"
        if path.exists():
            continue

        symbol = f"{listing['token']}USDT"
        start, end = listed_ms(listing) - BEFORE_MS, listed_ms(listing) + AFTER_MS
        day = datetime.fromtimestamp(listed_ms(listing) / 1000, timezone.utc).strftime("%Y-%m-%d")
        try:
            if now_ms - end < API_DAYS * 86_400_000:
                rows = from_api(symbol, start, end)
            else:
                rows = from_archive(symbol, day, start, end)
        except urllib.error.HTTPError as error:
            print(f"{listing['listedAt'][:16]} {symbol:<14} no Binance futures data ({error.code})", flush=True)
            skipped += 1
            continue

        if not any(row[0] < listed_ms(listing) for row in rows):
            print(f"{listing['listedAt'][:16]} {symbol:<14} no trades before the listing, skipped", flush=True)
            skipped += 1
            continue

        path.write_text(f'window.TRADES = window.TRADES || {{}};\nwindow.TRADES["{key}"] = {json.dumps(rows, separators=(",", ":"))};\n')
        saved += 1
        write_index()
        print(f"{listing['listedAt'][:16]} {symbol:<14} {len(rows):>6} trades", flush=True)

    print(f"DONE: {saved} new, {skipped} without data, {write_index()} listings in data/", flush=True)
    print(f"supply known for {write_supply()} coins", flush=True)


if __name__ == "__main__":
    main()
