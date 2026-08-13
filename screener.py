"""
Nasdaq-100 Screener
--------------------
Zieht täglich Kursdaten für die Nasdaq-100-Werte, filtert nach
Volumen-Ausreißern + großer Kursbewegung und postet die Treffer
in Discord. Optional formuliert Gemini daraus eine kurze Zusammenfassung.
"""

import io
import os
import time
from datetime import datetime

import pandas as pd
import requests
import yfinance as yf

# --- Konfiguration: hier Schwellenwerte anpassen ---
VOLUME_MULTIPLIER = 1.8   # Volumen heute >= X * 20-Tage-Schnitt (z. B. 1.8x)
MIN_PCT_MOVE = 3.0        # Mindest-Tagesbewegung in Prozent (absolut, z. B. 3%)
LOOKBACK_DAYS = 30        # Historie für Durchschnittsberechnung
GEMINI_MODEL = "gemini-3.6-flash"

DISCORD_WEBHOOK_SCREENER = os.environ["DISCORD_WEBHOOK_SCREENER"]
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

# Vollständige Liste der Nasdaq-100 Ticker als Garantiefallback
FULL_NASDAQ100_TICKERS = [
    "AAPL", "ABNB", "ADBE", "ADI", "ADP", "ADSK", "AEP", "AMAT", "AMD", "AMGN",
    "AMZN", "ANSS", "ASML", "AVGO", "AZN", "BKR", "BKNG", "BIIB", "CDNS", "CEG",
    "CHTR", "CPRT", "CSGP", "CSX", "CTAS", "CTSH", "CCEP", "COST", "CRWD", "CSCO",
    "DXCM", "DDOG", "DLTR", "DASH", "EA", "EXC", "FAST", "FTNT", "GEHC", "GILD",
    "GOOG", "GOOGL", "HON", "IDXX", "ILMN", "INKT", "INTC", "INTU", "ISRG", "KDP",
    "KLAC", "KHC", "LRCX", "LIN", "LYV", "LULU", "MAR", "MRVL", "MELI", "META",
    "MDLZ", "MDB", "MNST", "MSFT", "MU", "NFLX", "NVX", "NVDA", "NXPI", "ORLY",
    "ODFL", "ON", "PCAR", "PANW", "PAYX", "PYPL", "PDD", "PEP", "QCOM", "REGN",
    "ROST", "SBUX", "SNPS", "TEAM", "TMUS", "TSLA", "TXN", "TTD", "VRSK", "VRTX",
    "WBA", "WBD", "WDAY", "XEL", "ZS"
]


def get_nasdaq100_tickers() -> list[str]:
    """Holt die aktuelle Nasdaq-100-Liste von Wikipedia (mit io.StringIO) oder nutzt das Vollback."""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
        }
        url = "https://en.wikipedia.org/wiki/Nasdaq-100"
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()

        # io.StringIO verhindert, dass pandas den HTML-String als Dateipfad interpretiert
        tables = pd.read_html(io.StringIO(response.text))
        for t in tables:
            col = "Ticker" if "Ticker" in t.columns else ("Symbol" if "Symbol" in t.columns else None)
            if col:
                return t[col].str.replace(".", "-", regex=False).tolist()
    except Exception as e:
        print(f"Wikipedia-Fetch fehlgeschlagen ({e}), nutze vollständige Fallback-Liste.")

    return FULL_NASDAQ100_TICKERS


def calculate_rsi(series: pd.Series, period: int = 14) -> float | None:
    """Berechnet den Relative Strength Index (RSI)."""
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi.iloc[-1] if not rsi.empty else None


def analyze_ticker(ticker: str) -> dict | None:
    """Prüft einen einzelnen Ticker auf Volumen & Bewegung."""
    try:
        data = yf.Ticker(ticker).history(period=f"{LOOKBACK_DAYS}d", interval="1d")
        if data.empty or len(data) < 21:
            return None

        rsi_value = calculate_rsi(data["Close"])
        avg_volume = data["Volume"].iloc[-21:-1].mean()
        today_close = data["Close"].iloc[-1]
        today_volume = data["Volume"].iloc[-1]
        prev_close = data["Close"].iloc[-2]

        pct_move = (today_close - prev_close) / prev_close * 100
        volume_ratio = today_volume / avg_volume if avg_volume else 0

        if volume_ratio >= VOLUME_MULTIPLIER and abs(pct_move) >= MIN_PCT_MOVE:
            return {
                "ticker": ticker,
                "pct_move": round(float(pct_move), 2),
                "volume_ratio": round(float(volume_ratio), 2),
                "rsi": round(float(rsi_value), 1) if pd.notna(rsi_value) else "N/A",
                "close": round(float(today_close), 2),
            }
    except Exception as e:
        print(f"Fehler bei {ticker}: {e}")
    return None


def screen_market() -> list[dict]:
    hits = []
    tickers = get_nasdaq100_tickers()
    print(f"Starte Screening für {len(tickers)} Ticker...")
    for i, ticker in enumerate(tickers):
        result = analyze_ticker(ticker)
        if result:
            hits.append(result)
        time.sleep(0.2)  # Kurze Pause gegen Rate-Limiting
        if (i + 1) % 20 == 0:
            print(f"... {i + 1}/{len(tickers)} geprüft")
    return hits


def format_plain(hits: list[dict]) -> str:
    if not hits:
        return "Heute keine Treffer im Nasdaq-100-Screener (keine Werte mit entsprechenden Volumen- & Bewegungs-Ausreißern)."
    lines = [f"📊 **Nasdaq-100 Screener - {datetime.now():%d.%m.%Y}**\n"]
    for h in hits:
        direction = "🟢" if h['pct_move'] > 0 else "🔴"
        lines.append(
            f"{direction} **{h['ticker']}**: {h['pct_move']:+} % | "
            f"Volumen: **{h['volume_ratio']}x** Schnitt | "
            f"Kurs: ${h['close']} | RSI: {h['rsi']}"
        )
    return "\n".join(lines)


def summarize_with_gemini(hits: list[dict]) -> str:
    if not GEMINI_API_KEY or not hits:
        return format_plain(hits)

    try:
        from google import genai

        client = genai.Client(api_key=GEMINI_API_KEY)
        prompt = (
            "Fasse diese Nasdaq-100-Screener-Treffer in maximal 4 kurzen, "
            "prägnanten Sätzen auf Deutsch zusammen. Hebe hervor, welche Aktien "
            "besonders stark ausgebrochen sind. Keine Anlageberatung.\n\n"
            f"{hits}"
        )
        response = client.models.generate_content(
            model=GEMINI_MODEL, contents=prompt
        )
        return response.text
    except Exception as e:
        print(f"Gemini-Fehler, nutze Standard-Ausgabe: {e}")
        return format_plain(hits)


def post_to_discord(message: str) -> None:
    resp = requests.post(DISCORD_WEBHOOK_SCREENER, json={"content": message[:2000]})
    resp.raise_for_status()


if __name__ == "__main__":
    treffer = screen_market()
    nachricht = summarize_with_gemini(treffer)
    post_to_discord(nachricht)
    print("Fertig! Nachricht gepostet.")
