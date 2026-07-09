import os
import sys
import requests
from datetime import datetime, timedelta, timezone
from playwright.sync_api import sync_playwright

WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")
TWITTER_USER = "TrendSpider"
PROFILE_URL = f"https://x.com/{TWITTER_USER}"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


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
            page.wait_for_selector('article[data-testid="tweet"]', timeout=15000)
        except Exception as e:
            page.screenshot(path="debug_screenshot.png", full_page=True)
            with open("debug_page.html", "w", encoding="utf-8") as f:
                f.write(page.content())
            browser.close()
            raise RuntimeError(f"Seite konnte nicht geladen werden: {e}")

        articles = page.query_selector_all('article[data-testid="tweet"]')

        for article in articles[:10]:
            try:
                text_el = article.query_selector('div[data-testid="tweetText"]')
                text = text_el.inner_text() if text_el else ""

                time_el = article.query_selector("time")
                datetime_attr = time_el.get_attribute("datetime") if time_el else None

                link_el = time_el.evaluate_handle("el => el.closest('a')") if time_el else None
                link = None
                if link_el:
                    href = link_el.get_property("href")
                    if href:
                        link = href.json_value()

                if datetime_attr:
                    tweets.append({
                        "text": text,
                        "datetime": datetime_attr,
                        "link": link or PROFILE_URL,
                    })
            except Exception:
                continue

        browser.close()

    return tweets


def fetch_and_post():
    if not WEBHOOK_URL:
        raise RuntimeError("DISCORD_WEBHOOK_URL fehlt in den Secrets!")

    tweets = fetch_latest_tweets()
    if not tweets:
        raise RuntimeError("Keine Tweets auf der Seite gefunden (evtl. Layout geaendert oder Login-Wand).")

    now = datetime.now(timezone.utc)
    time_threshold = now - timedelta(minutes=20)

    posted = 0
    for tweet in tweets:
        pub_date = datetime.fromisoformat(tweet["datetime"].replace("Z", "+00:00"))
        if pub_date <= time_threshold:
            continue

        message = f"Neuer TrendSpider-Post!\n\n{tweet['text']}\n\nLink: {tweet['link']}"
        resp = requests.post(WEBHOOK_URL, json={"content": message}, timeout=10)
        if resp.status_code >= 300:
            print(f"[ERROR] Discord-Post fehlgeschlagen: {resp.status_code} {resp.text}")
        else:
            posted += 1
            print(f"[OK] An Discord gesendet: {tweet['text'][:40]}...")

    print(f"Fertig. {posted} neue Posts gesendet. ({len(tweets)} Tweets insgesamt geladen)")


if __name__ == "__main__":
    try:
        fetch_and_post()
    except Exception as e:
        print(f"[FATAL] {e}")
        sys.exit(1)
