import os
import sys
import json
import requests
from playwright.sync_api import sync_playwright

ACCOUNTS = [
    {"user": "TrendSpider", "webhook_env": "DISCORD_WEBHOOK_TRENDSPIDER", "state_file": "seen_ids_trendspider.json"},
    {"user": "earnings_guy", "webhook_env": "DISCORD_WEBHOOK_EARNINGS", "state_file": "seen_ids_earnings.json"},
    {"user": "watcherguru", "webhook_env": "DISCORD_WEBHOOK_WATCHERGURU", "state_file": "seen_ids_watcherguru.json"},
]

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


def load_seen_ids(state_file):
    if os.path.exists(state_file):
        with open(state_file, "r") as f:
            return set(json.load(f))
    return set()


def save_seen_ids(state_file, ids):
    trimmed = list(ids)[-200:]
    with open(state_file, "w") as f:
        json.dump(trimmed, f)


def fetch_latest_tweets(page, username):
    profile_url = f"https://x.com/{username}"
    page.goto(profile_url, timeout=30000, wait_until="domcontentloaded")
    page.wait_for_selector("article[data-tweet-id]", timeout=15000)

    tweets = []
    articles = page.query_selector_all("article[data-tweet-id]")

    for article in articles[:15]:
        try:
            tweet_id = article.get_attribute("data-tweet-id")
            if not tweet_id:
                continue

            text_el = article.query_selector('div[dir="auto"]')
            text = text_el.inner_text() if text_el else ""

            link = f"https://x.com/{username}/status/{tweet_id}"
            tweets.append({"id": tweet_id, "text": text, "link": link})
        except Exception:
            continue

    return tweets


def process_account(page, account):
    username = account["user"]
    webhook_url = os.environ.get(account["webhook_env"])

    if not webhook_url:
        print(f"[WARN] {username}: Secret {account['webhook_env']} fehlt, ueberspringe.")
        return

    try:
        tweets = fetch_latest_tweets(page, username)
    except Exception as e:
        print(f"[ERROR] {username}: Seite konnte nicht geladen werden: {e}")
        return

    if not tweets:
        print(f"[WARN] {username}: Keine Tweets gefunden.")
        return

    seen_ids = load_seen_ids(account["state_file"])
    first_run = len(seen_ids) == 0
    new_seen = set(seen_ids)
    posted = 0

    for tweet in reversed(tweets):
        new_seen.add(tweet["id"])
        if tweet["id"] in seen_ids:
            continue
        if first_run:
            continue

        message = f"{tweet['text']}\n\nLink: {tweet['link']}"
        resp = requests.post(webhook_url, json={"content": message}, timeout=10)
        if resp.status_code >= 300:
            print(f"[ERROR] {username}: Discord-Post fehlgeschlagen: {resp.status_code} {resp.text}")
        else:
            posted += 1
            print(f"[OK] {username}: An Discord gesendet: {tweet['text'][:40]}...")

    save_seen_ids(account["state_file"], new_seen)

    if first_run:
        print(f"[INFO] {username}: Erster Lauf, {len(new_seen)} Posts als bekannt markiert, nichts gepostet.")
    else:
        print(f"[INFO] {username}: Fertig, {posted} neue Posts gesendet.")


def main():
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

        any_error = False
        for account in ACCOUNTS:
            try:
                process_account(page, account)
            except Exception as e:
                any_error = True
                print(f"[FATAL] {account['user']}: {e}")

        browser.close()

    if any_error:
        sys.exit(1)


if __name__ == "__main__":
    main()