import os
import sys
import json
import requests
from playwright.sync_api import sync_playwright

ACCOUNTS = [
    {
        "user": "TrendSpider",
        "webhook_env": "DISCORD_WEBHOOK_TRENDSPIDER",
        "state_file": "seen_ids_trendspider.json",
    },
    {
        "user": "earnings_guy",
        "webhook_env": "DISCORD_WEBHOOK_EARNINGS",
        "state_file": "seen_ids_earnings.json",
    },
    {
        "user": "watcherguru",
        "webhook_env": "DISCORD_WEBHOOK_WATCHERGURU",
        "state_file": "seen_ids_watcherguru.json",
    },
    {
        "user": "ewhispers",
        "webhook_env": "DISCORD_WEBHOOK_EWHISPERS",
        "state_file": "seen_ids_ewhispers.json",
    },
]

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


def load_seen_ids(state_file):
    if os.path.exists(state_file):
        try:
            with open(state_file, "r") as f:
                content = f.read().strip()
                if not content:
                    return set()
                return set(json.loads(content))
        except (json.JSONDecodeError, ValueError):
            return set()
    return set()


def save_seen_ids(state_file, ids):
    trimmed = list(ids)[-200:]
    with open(state_file, "w") as f:
        json.dump(trimmed, f)


def fetch_latest_tweets(page, username):
    profile_url = f"https://x.com/{username}"
    page.goto(profile_url, timeout=30000, wait_until="domcontentloaded")
    
    # Warte, bis die Tweets geladen sind
    page.wait_for_selector("article[data-tweet-id]", timeout=15000)
    
    # Winziges Scrollen simuliert menschliche Interaktion
    page.evaluate("window.scrollTo(0, 400)")
    page.wait_for_timeout(2000)

    tweets = []
    articles = page.query_selector_all("article[data-tweet-id]")

    top_level_articles = []
    for article in articles:
        # Pruefen, ob es ein verschachtelter Tweet (z. B. in einem Thread) ist
        is_nested = article.evaluate(
            "el => el.parentElement.closest('article[data-tweet-id]') !== null"
        )
        if not is_nested:
            top_level_articles.append(article)

    for article in top_level_articles[:15]:
        try:
            # 1. PRUEFUNG AUF GEPINNTE TWEETS
            is_pinned = article.query_selector('[data-testid="socialContext"]')
            if is_pinned and "Pinned" in (is_pinned.inner_text() or ""):
                print(f"[INFO] {username}: Gepinnten Tweet uebersprungen.")
                continue

            # 2. PRUEFUNG AUF WERBUNG (PROMOTED TWEETS)
            # Twitter markiert Werbe-Tweets im HTML-Baum strukturell anders.
            # Wenn der Tweet ein "Ad"-Label enthaelt, sortieren wir ihn sofort aus.
            is_promoted = article.evaluate(
                """el => {
                    const text = el.innerText || "";
                    return text.includes("Promoted") || text.includes("Gesponsert") || text.includes("Anzeige");
                }"""
            )
            if is_promoted:
                print(f"[INFO] {username}: Werbe-Tweet (Promoted) im HTML erkannt und blockiert.")
                continue

            tweet_id = article.get_attribute("data-tweet-id")
            if not tweet_id:
                continue

            # Text-Selektor
            text_el = article.query_selector('[data-testid="tweetText"]')
            text = text_el.inner_text() if text_el else ""

            # Ausweichloesung, falls kein Text vorhanden ist (nur Medien)
            if not text:
                text_el_alt = article.query_selector('div[dir="auto"]')
                text = text_el_alt.inner_text() if text_el_alt else "[Nur Bild/Medium]"

            link = f"https://x.com/{username}/status/{tweet_id}"
            tweets.append({"id": tweet_id, "text": text, "link": link})
        except Exception as e:
            print(f"[DEBUG] Fehler beim Parsen eines Tweets von {username}: {e}")
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
