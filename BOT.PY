import os
import sys
import json
import requests
from playwright.sync_api import sync_playwright

# Jeder Account bekommt: X-Username, Name des GitHub-Secrets fuer den Webhook,
# und eine eigene State-Datei fuer die gesehenen Tweet-IDs.
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

    top_level_articles = []
    for article in articles:
        is_nested = article.evaluate(
            "el => el.parentElement.closest('article[data-tweet-id]') !== null"
        )
        if not is_nested:
            top_level_articles.append(article)

    for article in top_level_articles[:15]:
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
        print(f"[ERROR]
