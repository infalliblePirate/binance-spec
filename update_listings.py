#!/usr/bin/env python3
"""Download all Upbit KRW listing announcements into listings.js for index.html."""

import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

ANNOUNCEMENTS_URL = "https://api-manager.upbit.com/api/v1/announcements?os=web&page={page}&per_page=20&category=trade"
LISTING_MARKERS = ("디지털 자산 추가", "신규 거래지원")
REQUEST_DELAY_SECONDS = 1.0
RATE_LIMIT_DELAY_SECONDS = 30
OUTPUT = Path(__file__).with_name("listings.js")


def fetch(page: int) -> dict:
    request = urllib.request.Request(ANNOUNCEMENTS_URL.format(page=page), headers={"User-Agent": "Mozilla/5.0"})
    while True:
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                return json.loads(response.read())["data"]
        except urllib.error.HTTPError as error:
            if error.code != 429:
                raise
            print(f"page {page}: rate limited, waiting {RATE_LIMIT_DELAY_SECONDS}s")
            time.sleep(RATE_LIMIT_DELAY_SECONDS)


def main() -> None:
    first = fetch(1)
    notices = first["notices"]
    for page in range(2, first["total_pages"] + 1):
        time.sleep(REQUEST_DELAY_SECONDS)
        notices += fetch(page)["notices"]

    listings = []
    for notice in notices:
        title = notice["title"]
        if "KRW" not in title or not any(marker in title for marker in LISTING_MARKERS):
            continue
        for token in re.findall(r"\(([A-Z0-9]{2,15})\)", title):
            listings.append({"token": token, "listedAt": notice["listed_at"], "title": title})

    OUTPUT.write_text("window.UPBIT_LISTINGS = " + json.dumps(listings, ensure_ascii=False, indent=1) + ";\n", encoding="utf-8")
    print(f"{len(notices)} announcements, {len(listings)} listings written to {OUTPUT.name}")


if __name__ == "__main__":
    main()
