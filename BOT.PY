import os
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
import email.utils

# Holt die Webhook-URL aus deinen GitHub Secrets
WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")
TWITTER_USER = "TrendSpider"
# Nutzt eine öffentlich zugängliche RSS-Bridge für X/Twitter
rss_url = f"https://nitter.privacydev.net/{TWITTER_USER}/rss"


def fetch_and_post():
    if not WEBHOOK_URL:
        print("Fehler: DISCORD_WEBHOOK_URL fehlt in den Secrets!")
        return

    try:
        # HIER KORRIGIERT: rss_url statt FEED_URL
        response = requests.get(rss_url, timeout=15)
        if response.status_code != 200:
            print(f"Feed-Fehler: Status {response.status_code}")
            return
        
        root = ET.fromstring(response.content)
        now = datetime.now(timezone.utc)
        # Filtert nach Beiträgen der letzten 20 Minuten (passend zum 15-Minuten-Rhythmus)
        time_threshold = now - timedelta(minutes=20)

        for item in root.findall('.//item'):
            title = item.find('title').text if item.find('title') is not None else ""
            link = item.find('link').text if item.find('link') is not None else ""
            pub_date_str = item.find('pubDate').text if item.find('pubDate') is not None else ""
            
            if pub_date_str:
                pub_date_tuple = email.utils.parsedate_tz(pub_date_str)
                if pub_date_tuple:
                    pub_date = datetime.fromtimestamp(email.utils.mktime_tz(pub_date_tuple), timezone.utc)
                    
                    if pub_date > time_threshold:
                        # Schickes Discord-Format zusammenbauen
                        message = f"📢 **Neuer TrendSpider-Post!**\n\n{title}\n\n🔗 Link: {link}"
                        requests.post(WEBHOOK_URL, json={"content": message})
                        print(f"Erfolgreich an Discord gesendet: {title[:30]}...")
                        
    except Exception as e:
        print(f"Fehler beim Ausführen: {e}")

if __name__ == "__main__":
    fetch_and_post()
