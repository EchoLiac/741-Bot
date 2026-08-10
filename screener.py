"""
Nasdaq-100 Screener
--------------------
Zieht taeglich Kursdaten fuer die Nasdaq-100-Werte, filtert nach
Volumen-Ausreissern + grosser Kursbewegung und postet die Treffer
in Discord. Optional formuliert Gemini (Free-Tier) daraus eine
kurze Zusammenfassung.

Benoetigte Umgebungsvariablen (als GitHub Secrets gesetzt):
  DISCORD_WEBHOOK_URL   -> Pflicht
  GEMINI_API_KEY        -> optional (ohne Key: reine Listen-Ausgabe)
"""

import os
import time
from datetime import datetime

import pandas as pd
import pandas_ta as ta
import requests
import yfinance as yf

# --- Konfiguration: hier Schwellenwerte anpassen ---
VOLUME_MULTIPLIER = 2.0   # Volumen heute >= X * 20-Tage-Schnitt
MIN_PCT_MOVE = 5.0        # Mindest-Tagesbewegung in Prozent (absolut)
LOOKBACK_DAYS = 30        # Historie fuer Durchschnittsberechnung
GEMINI_MODEL = "gemini-3.6-flash"  # aktualisiert - 2.5er-Reihe wird Okt. 2026 abgeschaltet

DISCORD_WEBHOOK_URL = os.environ["DISCORD_WEBHOOK_URL"]
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

FALLBACK_TICKERS = [
    "AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "GOOG", "TSLA",
    "AVGO", "COST", "NFLX", "AMD", "PEP", "ADBE", "CSCO", "INTC",
]


def get_nasdaq100_tickers() -> list[str]:
    """Holt die aktuelle Nasdaq-100-Liste von Wikipedia, mit Fallback."""
    try:
        tables = pd.read_html("https://en.wikipedia.org/wiki/Nasdaq-100")
        for t in tables:
            if "Ticker" in t.columns:
                return t["Ticker"].str.replace(".", "-", regex=False).tolist()
    except Exception as e:
        print(f"Wikipedia-Fetch fehlgeschlagen, nutze Fallback-Liste: {e}")
    return FALLBACK_TICKERS


def analyze_ticker(ticker: str) -> dict | None:
    """Prueft einen einzelnen Ticker gegen die Filterkriterien."""
    try:
        data = yf.download(
            ticker, period=f"{LOOKBACK_DAYS}d", interval="1d",
            progress=False, auto_adjust=True,
        )
        if data.empty or len(data) < 21:
            return None

        data["RSI"] = ta.rsi(data["Close"], length=14)

        avg_volume = data["Volume"].iloc[-21:-1].mean()
        today = data.iloc[-1]
        prev_close = data["Close"].iloc[-2]
        pct_move = (today["Close"] - prev_close) / prev_close * 100
        volume_ratio = today["Volume"] / avg_volume if avg_volume else 0

        if volume_ratio >= VOLUME_MULTIPLIER and abs(pct_move) >= MIN_PCT_MOVE:
            rsi_value = today["RSI"]
            return {
                "ticker": ticker,
                "pct_move": round(float(pct_move), 2),
                "volume_ratio": round(float(volume_ratio), 2),
                "rsi": round(float(rsi_value), 1) if pd.notna(rsi_value) else None,
                "close": round(float(today["Close"]), 2),
            }
    except Exception as e:
        print(f"Fehler bei {ticker}: {e}")
    return None


def screen_market() -> list[dict]:
    hits = []
    tickers = get_nasdaq100_tickers()
    for i, ticker in enumerate(tickers):
        result = analyze_ticker(ticker)
        if result:
            hits.append(result)
        time.sleep(0.3)  # Pause gegen Yahoo-Rate-Limiting bei ~100 Tickern
        if (i + 1) % 20 == 0:
            print(f"...{i + 1}/{len(tickers)} geprueft")
    return hits


def format_plain(hits: list[dict]) -> str:
    if not hits:
        return "Heute keine Treffer im Nasdaq-100-Screener."
    lines = [f"**Nasdaq-100 Screener - {datetime.now():%d.%m.%Y}**"]
    for h in hits:
        lines.append(
            f"- **{h['ticker']}**: {h['pct_move']}% | "
            f"Volumen {h['volume_ratio']}x Schnitt | "
            f"Kurs {h['close']} | RSI {h['rsi']}"
        )
    return "\n".join(lines)


def summarize_with_gemini(hits: list[dict]) -> str:
    """Formuliert optional eine kurze Zusammenfassung ueber Gemini.
    Faellt ohne API-Key oder bei Fehlern auf die reine Liste zurueck."""
    if not GEMINI_API_KEY or not hits:
        return format_plain(hits)

    try:
        from google import genai

        client = genai.Client(api_key=GEMINI_API_KEY)
        prompt = (
            "Fasse diese Nasdaq-100-Screener-Treffer in maximal 5 kurzen "
            "Saetzen auf Deutsch zusammen. Nenne Ticker, Bewegung und "
            "Volumen-Auffaelligkeit. Keine Anlageberatung, nur Beobachtung.\n\n"
            f"{hits}"
        )
        response = client.models.generate_content(
            model=GEMINI_MODEL, contents=prompt,
        )
        return response.text
    except Exception as e:
        print(f"Gemini-Fehler, nutze Plain-Text-Fallback: {e}")
        return format_plain(hits)


def post_to_discord(message: str) -> None:
    resp = requests.post(DISCORD_WEBHOOK_URL, json={"content": message[:2000]})
    resp.raise_for_status()


if __name__ == "__main__":
    treffer = screen_market()
    nachricht = summarize_with_gemini(treffer)
    post_to_discord(nachricht)
    print(nachricht)
