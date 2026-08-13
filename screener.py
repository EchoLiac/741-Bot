"""
Nasdaq-100 Screener & Tages-Update
------------------------------------
- Filtert nach Volumen-Ausreißern (>= 1.3x) & Kursbewegung (>= 1.5%)
- Prüft EMA 20/50 Trend & MACD-Kaufsignale (Top-Setup)
- Fallback: Schickt automatisch Top 3 Gewinner & Verlierer, falls keine Ausreißer da sind
"""

import io
import os
import time
from datetime import datetime

import pandas as pd
import requests
import yfinance as yf

# --- Konfiguration ---
VOLUME_MULTIPLIER = 1.3   # Volumen heute >= 1.3x (30 % über Schnitt)
MIN_PCT_MOVE = 1.5        # Mindest-Tagesbewegung >= 1.5 %
LOOKBACK_DAYS = 60
GEMINI_MODEL = "gemini-3.6-flash"

DISCORD_WEBHOOK_SCREENER = os.environ["DISCORD_WEBHOOK_SCREENER"]
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

FULL_NASDAQ100_TICKERS = [
    "AAPL", "ABNB", "ADBE", "ADI", "ADP", "ADSK", "AEP", "AMAT", "AMD", "AMGN",
    "AMZN", "ANSS", "ASML", "AVGO", "AZN", "BKR", "BKNG", "BIIB", "CDNS", "CEG",
    "CHTR", "CPRT", "CSGP", "CSX", "CTAS", "CTSH", "CCEP", "COST", "CRWD", "CSCO",
    "DXCM", "DDOG", "DLTR", "DASH", "EA", "EXC", "FAST", "FTNT", "GEHC", "GILD",
    "GOOG", "GOOGL", "HON", "IDXX", "ILMN", "INTC", "INTU", "ISRG", "KDP",
    "KLAC", "KHC", "LRCX", "LIN", "LYV", "LULU", "MAR", "MRVL", "MELI", "META",
    "MDLZ", "MDB", "MNST", "MSFT", "MU", "NFLX", "NVDA", "NXPI", "ORLY",
    "ODFL", "ON", "PCAR", "PANW", "PAYX", "PYPL", "PDD", "PEP", "QCOM", "REGN",
    "ROST", "SBUX", "SNPS", "TEAM", "TMUS", "TSLA", "TXN", "TTD", "VRSK", "VRTX",
    "WBA", "WBD", "WDAY", "XEL", "ZS"
]


def get_nasdaq100_tickers() -> list[str]:
    """Holt die Nasdaq-100 Ticker von Wikipedia oder nutzt die Vollback-Liste."""
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        url = "https://en.wikipedia.org/wiki/Nasdaq-100"
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        tables = pd.read_html(io.StringIO(response.text))
        for t in tables:
            col = "Ticker" if "Ticker" in t.columns else ("Symbol" if "Symbol" in t.columns else None)
            if col:
                return t[col].str.replace(".", "-", regex=False).tolist()
    except Exception as e:
        print(f"Wikipedia-Fetch fehlgeschlagen ({e}), nutze Fallback-Liste.")
    return FULL_NASDAQ100_TICKERS


def calculate_indicators(df: pd.DataFrame) -> dict:
    """Berechnet RSI, EMA 20/50 und MACD."""
    close = df["Close"]

    # RSI (14)
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.rolling(14).mean()
    avg_loss = loss.rolling(14).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))

    # EMAs
    ema20 = close.ewm(span=20, adjust=False).mean()
    ema50 = close.ewm(span=50, adjust=False).mean()

    # MACD (12, 26, 9)
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()

    c_close = close.iloc[-1]
    c_ema20 = ema20.iloc[-1]
    c_ema50 = ema50.iloc[-1]
    c_macd = macd_line.iloc[-1]
    c_signal = signal_line.iloc[-1]
    p_macd = macd_line.iloc[-2]
    p_signal = signal_line.iloc[-2]

    trend_bullish = (c_close > c_ema20) and (c_ema20 > c_ema50)
    macd_crossover = (p_macd <= p_signal) and (c_macd > c_signal)
    macd_bullish = c_macd > c_signal

    return {
        "rsi": round(float(rsi.iloc[-1]), 1) if pd.notna(rsi.iloc[-1]) else "N/A",
        "trend_bullish": trend_bullish,
        "macd_crossover": macd_crossover,
        "macd_bullish": macd_bullish
    }


def analyze_ticker(ticker: str) -> dict | None:
    """Berechnet Werte für einen einzelnen Ticker."""
    try:
        data = yf.Ticker(ticker).history(period=f"{LOOKBACK_DAYS}d", interval="1d")
        if data.empty or len(data) < 35:
            return None

        ind = calculate_indicators(data)
        avg_volume = data["Volume"].iloc[-21:-1].mean()
        today_close = data["Close"].iloc[-1]
        today_volume = data["Volume"].iloc[-1]
        prev_close = data["Close"].iloc[-2]

        pct_move = (today_close - prev_close) / prev_close * 100
        volume_ratio = today_volume / avg_volume if avg_volume else 0

        is_hit = (volume_ratio >= VOLUME_MULTIPLIER) and (abs(pct_move) >= MIN_PCT_MOVE)
        is_top_setup = is_hit and ind["trend_bullish"] and ind["macd_bullish"]

        return {
            "ticker": ticker,
            "pct_move": round(float(pct_move), 2),
            "volume_ratio": round(float(volume_ratio), 2),
            "close": round(float(today_close), 2),
            "rsi": ind["rsi"],
            "trend_bullish": ind["trend_bullish"],
            "macd_crossover": ind["macd_crossover"],
            "is_top_setup": is_top_setup,
            "is_hit": is_hit
        }
    except Exception as e:
        print(f"Fehler bei {ticker}: {e}")
    return None


def screen_market() -> tuple[list[dict], bool]:
    """Scanned den Markt. Gibt (Ergebnisse, ist_fallback) zurück."""
    tickers = get_nasdaq100_tickers()
    all_results = []

    print(f"Starte Screening (Volumen >= {VOLUME_MULTIPLIER}x, Move >= {MIN_PCT_MOVE}%)...")
    for i, ticker in enumerate(tickers):
        res = analyze_ticker(ticker)
        if res:
            all_results.append(res)
        time.sleep(0.12)
        if (i + 1) % 20 == 0:
            print(f"... {i + 1}/{len(tickers)} geprüft")

    hits = [r for r in all_results if r["is_hit"]]

    if hits:
        return hits, False

    # FALLBACK: Wenn keine harten Kriterien erfüllt sind -> Top 3 Gewinner & Verlierer
    print("Keine Ausreißer-Hits. Erstelle Top 3 Gewinner/Verlierer Fallback...")
    sorted_by_move = sorted(all_results, key=lambda x: x["pct_move"], reverse=True)
    top_gainers = sorted_by_move[:3]
    top_losers = sorted_by_move[-3:][::-1]

    return top_gainers + top_losers, True


def format_plain(items: list[dict], is_fallback: bool) -> str:
    date_str = datetime.now().strftime("%d.%m.%Y")

    if is_fallback:
        lines = [
            f"📊 **Nasdaq-100 Tages-Update ({date_str})**",
            "_Ruhiger Handelstag: Keine Werte mit extremem Ausbruchsvolumen. Hier sind die stärksten Bewegungen:_\n",
            "🟢 **Top 3 Gewinner:**"
        ]
        gainers = [x for x in items if x["pct_move"] >= 0]
        losers = [x for x in items if x["pct_move"] < 0]

        for g in gainers:
            lines.append(f"• **{g['ticker']}**: {g['pct_move']:+}% | Vol: {g['volume_ratio']}x | ${g['close']} | RSI: {g['rsi']}")

        lines.append("\n🔴 **Top 3 Verlierer:**")
        for l in losers:
            lines.append(f"• **{l['ticker']}**: {l['pct_move']:+}% | Vol: {l['volume_ratio']}x | ${l['close']} | RSI: {l['rsi']}")

        return "\n".join(lines)

    # Normale Treffer mit Ausreißern
    lines = [f"📊 **Nasdaq-100 Screener & Indikator-Check - {date_str}**\n"]
    for h in items:
        dir_icon = "🟢" if h['pct_move'] > 0 else "🔴"
        star_icon = "⭐ **[TOP-SETUP]** " if h['is_top_setup'] else ""
        macd_icon = " 🔥 (MACD-Cross!)" if h['macd_crossover'] else ""
        trend_str = "EMA-Trend 🟢" if h['trend_bullish'] else "EMA-Trend 🔴"

        lines.append(
            f"{star_icon}{dir_icon} **{h['ticker']}**: {h['pct_move']:+}% | "
            f"Vol: **{h['volume_ratio']}x** | Kurs: ${h['close']} | "
            f"RSI: {h['rsi']} | {trend_str}{macd_icon}"
        )
    return "\n".join(lines)


def summarize_with_gemini(items: list[dict], is_fallback: bool) -> str:
    if not GEMINI_API_KEY or not items:
        return format_plain(items, is_fallback)

    try:
        from google import genai
        client = genai.Client(api_key=GEMINI_API_KEY)

        if is_fallback:
            prompt = (
                "Es gab heute keine extremen Volumen-Ausreißer im Nasdaq-100. "
                "Fasse kurz in 2-3 prägnanten Sätzen auf Deutsch zusammen, welche "
                "Aktien die Top 3 Gewinner und Verlierer des Tages waren. Keine Anlageberatung.\n\n"
                f"{items}"
            )
        else:
            prompt = (
                "Fasse diese Nasdaq-100-Screener-Treffer in maximal 4 kurzen, "
                "prägnanten Sätzen auf Deutsch zusammen. Hebe Aktien mit 'is_top_setup': True "
                "oder 'macd_crossover': True besonders hervor. Keine Anlageberatung.\n\n"
                f"{items}"
            )

        response = client.models.generate_content(model=GEMINI_MODEL, contents=prompt)
        return response.text
    except Exception as e:
        print(f"Gemini-Fallback: {e}")
        return format_plain(items, is_fallback)


def post_to_discord(message: str) -> None:
    resp = requests.post(DISCORD_WEBHOOK_SCREENER, json={"content": message[:2000]})
    resp.raise_for_status()


if __name__ == "__main__":
    items, is_fallback = screen_market()
    nachricht = summarize_with_gemini(items, is_fallback)
    post_to_discord(nachricht)
    print("Fertig! Nachricht erfolgreich gepostet.")
