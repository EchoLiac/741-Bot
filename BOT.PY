import os
import sys
import json
import requests
from playwright.sync_api import sync_playwright

WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")
TWITTER_USER = "TrendSpider"
PROFILE_URL = f"https://x.com/{TWITTER_USER}"
STATE_FILE = "seen_ids.json"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


def load_seen_ids():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            return set(json.load(f))
    return set()


def save_seen_ids(ids):
    # nur die letzten 200 IDs behalten, damit die Datei nicht endlos waechst
    trimmed = list(ids)[-200:]
    with open(STATE_FILE, "w") as f:
        json.dump(trimmed, f)


def fetch_latest_tweets():
    tweets = []

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = browser.new_context(
            user_agent=USER_AGENT,
            viewport={"width": 1280, "height": 1000},
        )
        context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        page = context.new_page()

        try:
            page.goto(PROFILE_URL, timeout=30000, wait_until="domcontentloaded")
            page.wait_for_selector("article[data-tweet-id]", timeout=15000)
        except Exception as e:
            page.screenshot(path="debug_screenshot.png", full_page=True)
            with open("debug_page.html", "w", encoding="utf-8") as f:
                f.write(page.content())
            browser.close()
            raise RuntimeError(f"Seite konnte nicht geladen werden: {e}")

        articles = page.query_selector_all("article[data-tweet-id]")

        for article in articles[:15]:
            try:
                tweet_id = article.get_attribute("data-tweet-id")
                if not tweet_id:
                    continue

                text_el = article.query_selector('div[dir="auto"]')
                text = text_el.inner_text() if text_el else ""

                link = f"https://x.com/{TWITTER_USER}/status/{tweet_id}"

                tweets.append({"id": tweet_id, "text": text, "link": link})
            except Exception:
                continue

        browser.close()

    return tweets


def fetch_and_post():
    if not WEBHOOK_URL:
        raise RuntimeError("DISCORD_WEBHOOK_URL fehlt in den Secrets!")

    tweets = fetch_latest_tweets()
    if not tweets:
        raise RuntimeError("Keine Tweets auf der Seite gefunden.")

    seen_ids = load_seen_ids()
    first_run = len(seen_ids) == 0

    posted = 0
    new_seen = set(seen_ids)

    # von alt nach neu durchgehen, damit die Reihenfolge in Discord stimmt
    for tweet in reversed(tweets):
        new_seen.add(tweet["id"])
        if tweet["id"] in seen_ids:
            continue

        if first_run:
            # beim allerersten Lauf nur merken, nicht die ganze Historie posten
            continue

        message = f"Neuer TrendSpider-Post!\n\n{tweet['text']}\n\nLink: {tweet['link']}"
        resp = requests.post(WEBHOOK_URL, json={"content": message}, timeout=10)
        if resp.status_code >= 300:
            print(f"[ERROR] Discord-Post fehlgeschlagen: {resp.status_code} {resp.text}")
        else:
            posted += 1
            print(f"[OK] An Discord gesendet: {tweet['text'][:40]}...")

    save_seen_ids(new_seen)

    if first_run:
        print(f"Erster Lauf: {len(new_seen)} bestehende Posts als bekannt markiert, nichts gepostet.")
    else:
        print(f"Fertig. {posted} neue Posts gesendet.")


if __name__ == "__main__":
    try:
        fetch_and_post()
    except Exception as e:
        print(f"[FATAL] {e}")
        sys.exit(1)
