"""
PbD-Volumenprofil-Scanner (Tom Vorwald / Trade The Traders Methode)
--------------------------------------------------------------------
Ergänzung zu bot.py: läuft PARALLEL zum bestehenden screen_market()-Scan
und klassifiziert die heutige Tagesform jeder Aktie anhand des
Intraday-Volumenprofils.

Die drei Formen:
  P-Shape  -> schneller Impuls NACH OBEN, danach Balance OBEN,
              dünner "Single-Print"-Schwanz UNTEN  => bullische Fortsetzung
  b-Shape  -> schneller Impuls NACH UNTEN, danach Balance UNTEN,
              dünner Schwanz OBEN                   => bärische Fortsetzung
  D-Shape  -> symmetrische Glocke, fetter POC in der Mitte => Balance-Tag

Nur P und b gelten als "Setup" im Sinne des Screeners (D wird ignoriert,
da kein klarer Trend-Tag).

WICHTIG: yfinance liefert 5-Minuten-Intraday-Daten nur für den aktuellen/
laufenden Handelstag zuverlässig (period="1d"). Für ein sauberes Profil
sollte der Scan idealerweise erst ab ca. 1-2 Stunden nach US-Marktöffnung
laufen (sonst ist das Profil noch zu dünn).
"""

import time
import pandas as pd
import yfinance as yf


def get_intraday_volume_profile(ticker: str, num_bins: int = 30) -> pd.Series | None:
    """Holt die heutigen 5-Min-Bars und baut daraus ein Preis-Volumen-Profil."""
    try:
        data = yf.Ticker(ticker).history(period="1d", interval="5m")
        if data.empty or len(data) < 6:
            return None

        low, high = data["Low"].min(), data["High"].max()
        if high == low:
            return None

        # Jede Kerze wird ihrem mittleren Preis-Bin zugeordnet und mit
        # ihrem Volumen gewichtet -> vereinfachtes, aber robustes Profil
        mid_price = (data["Low"] + data["High"]) / 2
        bins = pd.cut(mid_price, bins=num_bins, include_lowest=True)
        profile = data.groupby(bins, observed=True)["Volume"].sum()
        return profile.sort_index()  # sortiert von niedrigstem zu höchstem Preis-Bin
    except Exception as e:
        print(f"Volumenprofil-Fehler bei {ticker}: {e}")
        return None


def classify_pbd_shape(ticker: str) -> dict | None:
    """Klassifiziert die heutige Volumenprofil-Form (P / b / D) für einen Ticker."""
    profile = get_intraday_volume_profile(ticker)
    if profile is None:
        return None

    volumes = profile.values
    n = len(volumes)
    total_vol = volumes.sum()
    if n < 9 or total_vol == 0:
        return None

    poc_idx = int(volumes.argmax())
    third = max(1, n // 3)

    lower_vol = volumes[:third].sum()          # unteres Preis-Drittel
    upper_vol = volumes[-third:].sum()          # oberes Preis-Drittel
    middle_vol = total_vol - upper_vol - lower_vol

    thin_tail_bottom = (lower_vol / total_vol) < 0.10   # "Single Prints" unten
    thin_tail_top = (upper_vol / total_vol) < 0.10       # "Single Prints" oben

    poc_in_upper_third = poc_idx >= (n - third)
    poc_in_lower_third = poc_idx < third
    poc_centered = third <= poc_idx < (n - third)

    if poc_in_upper_third and thin_tail_bottom and upper_vol >= middle_vol:
        shape = "P"
    elif poc_in_lower_third and thin_tail_top and lower_vol >= middle_vol:
        shape = "b"
    elif poc_centered and (middle_vol / total_vol) > 0.35:
        shape = "D"
    else:
        shape = None  # keine klare Form -> nicht relevant für den Scan

    if shape is None:
        return None

    return {
        "ticker": ticker,
        "shape": shape,
        "poc_position": round(poc_idx / n, 2),        # 0 = ganz unten, 1 = ganz oben
        "upper_vol_pct": round(upper_vol / total_vol * 100, 1),
        "lower_vol_pct": round(lower_vol / total_vol * 100, 1),
    }


def screen_pbd_setups(tickers: list[str]) -> list[dict]:
    """Scanned alle Ticker auf klare P- oder b-Shapes (D wird verworfen)."""
    setups = []
    for t in tickers:
        res = classify_pbd_shape(t)
        if res and res["shape"] in ("P", "b"):
            setups.append(res)
        time.sleep(0.1)
    return setups


def format_pbd_section(setups: list[dict]) -> str:
    """Discord-Textblock für die PbD-Setups (an format_plain()-Ausgabe anhängen)."""
    if not setups:
        return "\n\n📐 **PbD-Setups (Volumenprofil):** Keine klaren P-/b-Formen heute."

    lines = ["\n\n📐 **PbD-Setups (Volumenprofil):**"]
    for s in setups:
        icon = "🟢 P-Shape (bullisch)" if s["shape"] == "P" else "🔴 b-Shape (bärisch)"
        lines.append(
            f"• **{s['ticker']}**: {icon} | "
            f"Vol oben: {s['upper_vol_pct']}% | Vol unten: {s['lower_vol_pct']}% | "
            f"POC @ {s['poc_position']}"
        )
    return "\n".join(lines)


# --- Integration in bot.py -------------------------------------------------
#
# 1) Import oben in bot.py ergänzen:
#      from pbd_addon import screen_pbd_setups, format_pbd_section
#
# 2) Im /nasdaq-Command BEIDE Scans wirklich parallel laufen lassen:
#
#      tickers = get_nasdaq100_tickers()
#      (items, is_fallback), pbd_setups = await asyncio.gather(
#          asyncio.to_thread(screen_market),
#          asyncio.to_thread(screen_pbd_setups, tickers),
#      )
#      nachricht = await asyncio.to_thread(summarize_with_gemini, items, is_fallback)
#      nachricht += format_pbd_section(pbd_setups)
#
#    (asyncio.gather + to_thread lässt beide blockierenden Scans gleichzeitig
#     in Threads laufen, statt nacheinander -> spart ca. die Hälfte der Zeit)
