import os
import json
import asyncio
from playwright.async_api import async_playwright
import urllib.request

# Konfiguration aus deinen GitHub Secrets / Environment Variables
COOKIES_JSON = os.getenv("TWITTER_COOKIES")

# Zuweisung der Accounts zu deinen Discord Webhooks
TARGETS = {
    "TrendSpider": {
        "url": "https://x.com/TrendSpider",
        "webhook": os.getenv("DISCORD_WEBHOOK_TRENDSPIDER"),
        "screenshot": "error_TrendSpider.png"
    },
    "earnings_guy": {
        "url": "https://x.com/earnings_guy",
        "webhook": os.getenv("DISCORD_WEBHOOK_EARNINGS"),
        "screenshot": "error_earnings_guy.png"
    },
    "watcherguru": {
        "url": "https://x.com/watcherguru",
        "webhook": os.getenv("DISCORD_WEBHOOK_WATCHERGURU"),
        "screenshot": "error_watcherguru.png"
    },
    "ewhispers": {
        "url": "https://x.com/ewhispers",
        "webhook": os.getenv("DISCORD_WEBHOOK_EWHISPERS"),
        "screenshot": "error_ewhispers.png"
    }
}

def send_to_discord(webhook_url, content, image_url=None):
    if not webhook_url:
        print("Webhook URL fehlt in den Umgebungsvariablen!")
        return
    
    payload = {"content": content}
    if image_url:
        payload["embeds"] = [{"image": {"url": image_url}}]
    
    headers = {"Content-Type": "application/json"}
    req = urllib.request.Request(
        webhook_url, 
        data=json.dumps(payload).encode("utf-8"), 
        headers=headers, 
        method="POST"
    )
    try:
        with urllib.request.urlopen(req) as response:
            pass
    except Exception as e:
        print(f"Fehler beim Senden an Discord: {e}")

async def run_bot():
    if not COOKIES_JSON:
        print("***ERROR*** TWITTER_COOKIES fehlen in den Umgebungsvariablen!")
        return

    async with async_playwright() as p:
        # Browser im Headless-Modus starten
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        
        # Cookies einspielen
        try:
            cookies = json.loads(COOKIES_JSON)
            await context.add_cookies(cookies)
            print("***INFO*** Twitter-Cookies erfolgreich geladen. Bot laeuft eingeloggt!")
        except Exception as e:
            print(f"***ERROR*** Cookies konnten nicht geladen werden: {e}")
            await browser.close()
            return
        
        page = await context.new_page()
        
        for name, target in TARGETS.items():
            print(f"Scrape Target: {name} ({target['url']})")
            try:
                await page.goto(target["url"])
                
                # REPARIERTER SELEKTOR: Wartet darauf, dass X das Tweet-Element rendert
                await page.wait_for_selector('article[data-testid="tweet"]', timeout=15000)
                
                # Text des ersten Beitrags auslesen
                tweet_text = await page.locator('article[data-testid="tweet"] div[data-testid="tweetText"]').first.inner_text()
                
                # Versuchen, das erste Bild aus dem Beitrag zu holen
                image_element = page.locator('article[data-testid="tweet"] div[data-testid="tweetPhoto"] img').first
                image_url = None
                if await image_element.count() > 0:
                    image_url = await image_element.get_attribute("src")
                
                # Nachricht zusammenbauen und abschicken
                msg = f"**{name}** hat gepostet:\n{tweet_text}"
                send_to_discord(target["webhook"], msg, image_url)
                print(f"***SUCCESS*** Update fuer {name} erfolgreich an Discord gesendet!")
                
            except Exception as e:
                # Macht exakt den Screenshot, den du im Log gesehen hast, falls das Laden fehlschlägt
                await page.screenshot(path=target["screenshot"])
                print(f"***DEBUG*** Fehler-Screenshot gespeichert als {target['screenshot']}. Aktuelle URL: {target['url']}")
                print(f"***ERROR*** {name}: Seite konnte nicht geladen werden: {e}")
                
        await browser.close()

if __name__ == "__main__":
    asyncio.run(run_bot())
