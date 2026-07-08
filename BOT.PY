import os
import sys
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
import email.utils

WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")
TWITTER_USER = "TrendSpider"

# Mehrere Instanzen als Fallback, da einzelne oeffentliche Nitter-Instanzen
# haeufig down sind oder kein sauberes RSS mehr liefern.
RSS_CANDIDATES = [
    f"https://nitter.privacydev.net/{TWITTER_USER}/rss",
    f"https://nitter.poast.org/{TWITTER_USER}/rss",
    f"https://xcancel.com/{TWITTER_USER}/rss",
    f"https://nitter.tiekoetter.com/{TWITTER_USER}/rss",
]

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; TrendSpiderBot/1.0)"}


def fetch_rss():
    last_error = None
    for url in RSS_CANDIDATES:
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            content_type = resp.headers.get("content-type", "")

            if resp.status_code != 200:
                last_error = f"{url} -> Status {resp.status_code}"
                print(f"[WARN] {last_error}")
                continue

            if "xml" not in content_type.lower():
                last_error = f"{url} -> kein XML zurueckgegeben (Content-Type: {content_type})"
                print(f"[WARN] {last_error}")
                continue

            root = ET.fromstring(resp.content)
            print(f"[OK] Feed erfolgreich geladen von: {url}")
            return root

        except ET.ParseError as e:
            last_error = f"{url} -> XML-Parse-Fehler: {e}"
            print(f"[WARN] {last_error}")
        except requests.RequestException as e:
            last_error = f"{url} -> Verbindungsfehler: {e}"
            print(f"[WARN] {last_error}")

    raise RuntimeError(f"Alle RSS-Quellen fehlgeschlagen. Letzter Fehler: {last_error}")


def fetch_and_post():
    if not WEBHOOK_URL:
        raise RuntimeError("DISCORD_WEBHOOK_URL fehlt in den Secrets!")

    root = fetch_rss()
    now = datetime.now(timezone.utc)
    time_threshold = now - timedelta(minutes=20)

    posted = 0
    for item in root.findall(".//item"):
        title = item.find("title").text if item.find("title") is not None else ""
        link = item.find("link").text if item.find("link") is not None else ""
        pub_date_str = item.find("pubDate").text if item.find("pubDate") is not None else ""

        if not pub_date_str:
            continue

        pub_date_tuple = email.utils.parsedate_tz(pub_date_str)
        if not pub_date_tuple:
            continue

        pub_date = datetime.fromtimestamp(email.utils.mktime_tz(pub_date_tuple), timezone.utc)
        if pub_date <= time_threshold:
            continue

        message = f"Neuer TrendSpider-Post!\n\n{title}\n\nLink: {link}"
        resp = requests.post(WEBHOOK_URL, json={"content": message}, timeout=10)
        if resp.status_code >= 300:
            print(f"[ERROR] Discord-Post fehlgeschlagen: {resp.status_code} {resp.text}")
        else:
            posted += 1
            print(f"[OK] An Discord gesendet: {title[:40]}...")

    print(f"Fertig. {posted} neue Posts gesendet.")


if __name__ == "__main__":
    try:
        fetch_and_post()
    except Exception as e:
        print(f"[FATAL] {e}")
        sys.exit(1)
