"""
Trading Screener – getrennt nach Command
Commands: nasdaq | sp500 | pbd
"""

import io
import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import pandas as pd
import requests
import yfinance as yf

# PbD-Modul (bleibt wie bisher)
try:
    from pbd_addon import screen_pbd_setups, format_pbd_section
except ImportError:
    screen_pbd_setups = None
    format_pbd_section = None

# --- Konfiguration ---
VOLUME_MULTIPLIER = 1.3
MIN_PCT_MOVE = 1.5
LOOKBACK_DAYS = 60
GEMINI_MODEL = "gemini-3.6-flash"

DISCORD_WEBHOOK_SCREENER = os.environ["DISCORD_WEBHOOK_SCREENER"]
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

# Welcher Command wurde getriggert? (kommt vom Worker)
COMMAND = os.environ.get("SCREENER_COMMAND", "nasdaq").lower()

# -------------------- Ticker Listen --------------------
NASDAQ100_TICKERS = [
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

SP500_CORE = [
    "AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "BRK-B", "LLY", "AVGO", "JPM",
    "TSLA", "UNH", "XOM", "V", "MA", "PG", "JNJ", "HD", "COST", "ABBV",
    "CRM", "BAC", "MRK", "CVX", "WMT", "KO", "PEP", "TMO", "CSCO", "ACN",
    "MCD", "ABT", "DHR", "LIN", "ADBE", "WFC", "TXN", "PM", "NEE", "ORCL",
    "AMD", "DIS", "INTU", "AMGN", "IBM", "CAT", "GE", "QCOM", "SPGI", "NOW",
    "ISRG", "AXP", "BKNG", "T", "LOW", "UBER", "PFE", "AMAT"
]


def get_nasdaq100_tickers() -> list[str]:
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
    return NASDAQ100_TICKERS


def calculate_indicators(df: pd.DataFrame) -> dict:
    close = df["Close"]
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.rolling(14).mean()
    avg_loss = loss.rolling(14).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))

    ema20 = close.ewm(span=20, adjust=False).mean()
    ema50 = close.ewm(span=50, adjust=False).mean()

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


def screen_market(tickers: list[str]) -> tuple[list[dict], bool]:
    all_results = []
    print(f"Starte Screening von {len(tickers)} Titeln...")

    for i, ticker in enumerate(tickers):
        res = analyze_ticker(ticker)
        if res:
            all_results.append(res)
        time.sleep(0.10)
        if (i + 1) % 20 == 0:
            print(f"... {i + 1}/{len(tickers)} geprüft")

    hits = [r for r in all_results if r["is_hit"]]

    if hits:
        return hits, False

    print("Keine Ausreißer → Fallback Top 3 Gewinner/Verlierer")
    sorted_by_move = sorted(all_results, key=lambda x: x["pct_move"], reverse=True)
    top_gainers = sorted_by_move[:3]
    top_losers = sorted_by_move[-3:][::-1]
    return top_gainers + top_losers, True


def format_plain(items: list[dict], is_fallback: bool, label: str) -> str:
    date_str = datetime.now().strftime("%d.%m.%Y")

    if is_fallback:
        lines = [
            f"📊 **{label} Tages-Update ({date_str})**",
            "_Keine extremen Volumen-Ausreißer. Stärkste Bewegungen:_\n",
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

    lines = [f"📊 **{label} Screener – {date_str}**\n"]
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


def summarize_with_gemini(items: list[dict], is_fallback: bool, label: str) -> str:
    if not GEMINI_API_KEY or not items:
        return format_plain(items, is_fallback, label)

    try:
        from google import genai
        client = genai.Client(api_key=GEMINI_API_KEY)

        if is_fallback:
            prompt = (
                f"Es gab heute keine extremen Volumen-Ausreißer im {label}. "
                "Fasse kurz in 2-3 prägnanten Sätzen auf Deutsch zusammen, welche "
                "Aktien die Top 3 Gewinner und Verlierer waren. Keine Anlageberatung.\n\n"
                f"{items}"
            )
        else:
            prompt = (
                f"Fasse diese {label}-Screener-Treffer in maximal 4 kurzen, "
                "prägnanten Sätzen auf Deutsch zusammen. Hebe Aktien mit 'is_top_setup': True "
                "oder 'macd_crossover': True besonders hervor. Keine Anlageberatung.\n\n"
                f"{items}"
            )

        response = client.models.generate_content(model=GEMINI_MODEL, contents=prompt)
        return response.text
    except Exception as e:
        print(f"Gemini-Fallback: {e}")
        return format_plain(items, is_fallback, label)


def post_to_discord(message: str) -> None:
    for i in range(0, len(message), 1900):
        chunk = message[i:i + 1900]
        resp = requests.post(DISCORD_WEBHOOK_SCREENER, json={"content": chunk})
        resp.raise_for_status()


# -------------------- Hauptlogik --------------------
if __name__ == "__main__":
    print(f"Starte Screener für Command: {COMMAND}")

    if COMMAND == "nasdaq":
        tickers = get_nasdaq100_tickers()
        items, is_fallback = screen_market(tickers)
        nachricht = summarize_with_gemini(items, is_fallback, "Nasdaq-100")

    elif COMMAND == "sp500":
        items, is_fallback = screen_market(SP500_CORE)
        nachricht = summarize_with_gemini(items, is_fallback, "S&P-500")

    elif COMMAND == "pbd":
        if screen_pbd_setups is None:
            nachricht = "❌ PbD-Modul (pbd_addon) nicht gefunden."
        else:
            tickers = get_nasdaq100_tickers()  # oder SP500_CORE – je nach Wunsch
            pbd_setups = screen_pbd_setups(tickers)
            nachricht = "📐 **PbD-Setups (Volumenprofil):**\n"
            nachricht += format_pbd_section(pbd_setups) if format_pbd_section else str(pbd_setups)

    else:
        nachricht = f"❌ Unbekannter Command: {COMMAND}"

    post_to_discord(nachricht)
    print("Fertig! Nachricht gepostet.")
