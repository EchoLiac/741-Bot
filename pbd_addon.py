"""
PbD-Volumenprofil-Scanner (Tom Vorwald / Trade The Traders Methode)
Optimiert + VWAP-Filter + strengere Kriterien
"""

import time
import numpy as np
import pandas as pd
import yfinance as yf


def get_intraday_data(ticker: str) -> pd.DataFrame | None:
    """Holt 5-Minuten-Daten des aktuellen Tages."""
    try:
        data = yf.Ticker(ticker).history(period="1d", interval="5m")
        if data.empty or len(data) < 8:
            return None
        return data
    except Exception as e:
        print(f"Datenfehler bei {ticker}: {e}")
        return None


def calculate_vwap(data: pd.DataFrame) -> float:
    """Berechnet den Session-VWAP."""
    typical_price = (data["High"] + data["Low"] + data["Close"]) / 3
    vwap = (typical_price * data["Volume"]).sum() / data["Volume"].sum()
    return float(vwap)


def get_volume_profile(data: pd.DataFrame, num_bins: int = 24) -> tuple[np.ndarray, np.ndarray] | None:
    """
    Baut ein robusteres Volumenprofil.
    Gibt (bin_centers, volumes) zurück, sortiert von niedrig nach hoch.
    """
    try:
        low = data["Low"].min()
        high = data["High"].max()
        if high <= low:
            return None

        typical = (data["High"] + data["Low"] + data["Close"]) / 3
        bins = np.linspace(low, high, num_bins + 1)
        digitized = np.digitize(typical, bins) - 1
        digitized = np.clip(digitized, 0, num_bins - 1)

        volumes = np.zeros(num_bins)
        for i, vol in enumerate(data["Volume"].values):
            volumes[digitized[i]] += vol

        centers = (bins[:-1] + bins[1:]) / 2
        return centers, volumes
    except Exception as e:
        print(f"Profil-Fehler: {e}")
        return None


def classify_pbd_shape(ticker: str) -> dict | None:
    """
    Klassifiziert P / b / D und filtert zusätzlich mit VWAP.
    Strengere Kriterien als zuvor.
    """
    data = get_intraday_data(ticker)
    if data is None:
        return None

    profile = get_volume_profile(data)
    if profile is None:
        return None

    centers, volumes = profile
    total_vol = volumes.sum()
    n = len(volumes)

    if n < 9 or total_vol == 0:
        return None

    # Optional: sehr dünne Tage aussortieren
    if total_vol < 30000:
        return None

    poc_idx = int(volumes.argmax())
    third = max(1, n // 3)

    lower_vol = volumes[:third].sum()
    upper_vol = volumes[-third:].sum()
    middle_vol = total_vol - upper_vol - lower_vol

    # Strengere Tail-Definition
    thin_tail_bottom = (lower_vol / total_vol) < 0.08
    thin_tail_top = (upper_vol / total_vol) < 0.08

    poc_in_upper = poc_idx >= (n - third)
    poc_in_lower = poc_idx < third
    poc_centered = third <= poc_idx < (n - third)

    # Form bestimmen (strenger)
    shape = None
    if poc_in_upper and thin_tail_bottom and upper_vol >= middle_vol * 1.1:
        shape = "P"
    elif poc_in_lower and thin_tail_top and lower_vol >= middle_vol * 1.1:
        shape = "b"
    elif poc_centered and (middle_vol / total_vol) > 0.40:
        shape = "D"

    if shape is None:
        return None

    # --- VWAP-Filter ---
    vwap = calculate_vwap(data)
    last_close = float(data["Close"].iloc[-1])

    # P nur behalten wenn Preis über VWAP
    if shape == "P" and last_close < vwap:
        return None

    # b nur behalten wenn Preis unter VWAP
    if shape == "b" and last_close > vwap:
        return None

    return {
        "ticker": ticker,
        "shape": shape,
        "poc_position": round(poc_idx / n, 2),
        "upper_vol_pct": round(upper_vol / total_vol * 100, 1),
        "lower_vol_pct": round(lower_vol / total_vol * 100, 1),
        "vwap": round(vwap, 2),
        "close": round(last_close, 2),
        "above_vwap": last_close > vwap
    }


def screen_pbd_setups(tickers: list[str]) -> list[dict]:
    """Scanned auf klare P- und b-Shapes (mit VWAP-Filter)."""
    setups = []
    for t in tickers:
        res = classify_pbd_shape(t)
        if res and res["shape"] in ("P", "b"):
            setups.append(res)
        time.sleep(0.08)
    return setups


def format_pbd_section(setups: list[dict]) -> str:
    """Discord-Textblock für die PbD-Setups."""
    if not setups:
        return (
            "\n\n📐 **PbD-Setups (nur Intraday-Volumenprofil + VWAP):**\n"
            "Keine klaren P-/b-Formen heute."
        )

    lines = ["\n\n📐 **PbD-Setups (nur Intraday-Volumenprofil + VWAP):**"]
    for s in setups:
        icon = "🟢 P-Shape (bullisch)" if s["shape"] == "P" else "🔴 b-Shape (bärisch)"
        vwap_info = f" | VWAP {s['vwap']} | Close {s['close']}"
        lines.append(
            f"• **{s['ticker']}**: {icon} | "
            f"Vol oben: {s['upper_vol_pct']}% | Vol unten: {s['lower_vol_pct']}% | "
            f"POC @ {s['poc_position']}{vwap_info}"
        )

    lines.append(
        "\n_Hinweis: Nur der heutige Handelstag wird bewertet. "
        "Höhere Timeframes bitte manuell prüfen._"
    )
    return "\n".join(lines)
