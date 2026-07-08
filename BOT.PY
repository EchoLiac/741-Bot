import os
import sys
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
import email.utils

WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")
TWITTER_USER = "TrendSpider"

# Mehrere Instanzen als Fallback, da einzelne öffentliche Nitter-Instanzen
# haeufig down sind oder kein sauberes RSS mehr liefern.
RSS_CANDIDATES = [
    f"https://nitter.privacydev.net/{TWITTER_USER}/rss",
    f"https://nitter.poast.org/{TWITTER_USER}/rss",
    f"https://xcancel.com/{TWITTER_USER}/rss",
    f"https://nitter.tiekoetter.com/{TWITTER_USER}/rss",
]

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; TrendSpiderBot/1.0)"}


def fetch_rss():
    """Probiert mehrere Instanzen durch, bis eine valides RSS-XML liefert."""
    last_error = None
    for url in RSS_CANDIDATES:
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            content_type = resp.headers.get("content-type", "")

            if resp.status_code != 200:
                last_error = f"{url} -> Status {resp.status_code}"
                print(f"[WARN] {last_error}")
                continue

            if "
