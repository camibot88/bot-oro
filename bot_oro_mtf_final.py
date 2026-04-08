"""
Bot XAU/USD institucional — M5 + M15 + confirmación M1
Analiza al cierre de cada vela M5 y envía señales limpias a Telegram.

Estructura:
- M15 = filtro de tendencia HTF
- M5  = setup principal
- M1  = confirmación final de entrada

Mejoras:
- Secrets por variables de entorno
- Filtro HTF con EMA 50 / EMA 200 usando M15
- Filtro EMA local + pendiente en M5
- Confirmación final con M1
- Señales más limpias: BUY / SELL
- Cooldown anti-spam
- Dedupe por firma de señal
"""

import os
import time
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple

import requests

# ──────────────────────────────────────────────────────────────────────────────
# CONFIG
# ──────────────────────────────────────────────────────────────────────────────

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

SYMBOL = os.getenv("SYMBOL", "OANDA:XAUUSD")
PIP = float(os.getenv("PIP", "0.10"))

SL_MINIMO_PIPS = int(os.getenv("SL_MINIMO_PIPS", "15"))
SL_MAXIMO_PIPS = int(os.getenv("SL_MAXIMO_PIPS", "60"))
TP_RATIO = float(os.getenv("TP_RATIO", "2.0"))

LONDRES_INICIO = int(os.getenv("LONDRES_INICIO", "3"))
LONDRES_FIN = int(os.getenv("LONDRES_FIN", "7"))
NY_INICIO = int(os.getenv("NY_INICIO", "9"))
NY_FIN = int(os.getenv("NY_FIN", "14"))

M5_COOLDOWN_MIN = int(os.getenv("M5_COOLDOWN_MIN", "20"))

HTF_FAST = 50
HTF_SLOW = 200
LOCAL_EMA = 50
EMA_SLOPE_BARS = 5
STRUCT_LEN = 2
EXT_LIQ_LEN = 5
RETEST_WINDOW_BARS = 10
OB_LOOKBACK = 8
IMPULSE_FACTOR = 1.0

# Confirmación M1
M1_REQUIRE_BREAK = os.getenv("M1_REQUIRE_BREAK", "true").lower() == "true"

REQUEST_TIMEOUT = 15

# ──────────────────────────────────────────────────────────────────────────────
# TIEMPO / SESIONES
# ──────────────────────────────────────────────────────────────────────────────

def hora_colombia() -> datetime:
    return datetime.now(timezone.utc) + timedelta(hours=-5)

def mercado_abierto() -> Tuple[bool, str]:
    ahora = hora_colombia()
    dia = ahora.weekday()
    hora = ahora.hour
    minuto = ahora.minute

    if dia == 5:
        return False, "Mercado cerrado — Sábado"
    if dia == 6 and hora < 18:
        return False, f"Mercado cerrado — Abre domingo 6pm COL (faltan {18 - hora}h)"
    if dia == 4 and hora >= 17:
        return False, "Mercado cerrado — Fin de semana"
    if hora == 17:
        return False, f"Pausa diaria 5-6pm COL (reabre en {60 - minuto} min)"
    return True, "Mercado abierto"

def sesion_activa() -> Optional[str]:
    abierto, _ = mercado_abierto()
    if not abierto:
        return None
    hora = hora_colombia().hour
    if LONDRES_INICIO <= hora < LONDRES_FIN:
        return "Londres"
    if NY_INICIO <= hora < NY_FIN:
        return "Nueva York"
    return None

# ──────────────────────────────────────────────────────────────────────────────
# TELEGRAM
# ──────────────────────────────────────────────────────────────────────────────

def enviar_telegram(mensaje: str) -> None:
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("  ⚠️ Faltan TELEGRAM_TOKEN o TELEGRAM_CHAT_ID")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    datos = {"chat_id": TELEGRAM_CHAT_ID, "text": mensaje, "parse_mode": "HTML"}

    try:
        r = requests.post(url, data=datos, timeout=10)
        if r.status_code == 200:
            print("  ✅ Telegram enviado")
        else:
            print(f"  ⚠️ Error Telegram: {r.status_code} | {r.text[:200]}")
    except Exception as e:
        print(f"  ⚠️ Error Telegram: {e}")

# ──────────────────────────────────────────────────────────────────────────────
# DATOS
# ──────────────────────────────────────────────────────────────────────────────

def obtener_velas(intervalo_min: int, cantidad: int = 250) -> Tuple[List[Dict], str]:
    try:
        tf_map = {1: "1", 5: "5", 15: "15"}
        tf = tf_map.get(intervalo_min, "15")
        ahora = int(datetime.now(timezone.utc).timestamp())
        desde = ahora - (intervalo_min * 60 * cantidad)

        url = "https://history.tradingview.com/history"
        params = {
            "symbol": SYMBOL,
            "resolution": tf,
            "from": desde,
            "to": ahora,
        }
        headers = {
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://www.tradingview.com",
            "Origin": "https://www.tradingview.com",
        }

        r = requests.get(url, params=params, headers=headers, timeout=REQUEST_TIMEOUT)
        datos = r.json()

        if datos.get("s") == "ok" and len(datos.get("t", [])) > 50:
            velas = []
            for i in range(len(datos["t"])):
                try:
                    velas.append({
                        "tiempo": datetime.fromtimestamp(datos["t"][i], tz=timezone.utc),
                        "open": round(float(datos["o"][i]), 2),
                        "high": round(float(datos["h"][i]), 2),
                        "low": round(float(datos["l"][i]), 2),
                        "close": round(float(datos["c"][i]), 2),
                    })
                except Exception:
                    continue
            if len(velas) > 50:
                return velas, "TradingView"
    except Exception:
        pass

    try:
        iv_map = {1: "1m", 5: "5m", 15: "15m"}
        iv = iv_map.get(intervalo_min, "15m")
        url = "https://query1.finance.yahoo.com/v8/finance/chart/GC=F"
        params = {"interval": iv, "range": "7d"}
        r = requests.get(url, params=params, headers={"User-Agent": "Mozilla/5.0"}, timeout=REQUEST_TIMEOUT)
        datos = r.json()
        chart = datos["chart"]["result"][0]
        ts = chart["timestamp"]
        px = chart["indicators"]["quote"][0]
        velas = []

        for i in range(len(ts)):
            try:
                o = px["open"][i]
                h = px["high"][i]
                l = px["low"][i]
                c = px["close"][i]
                if None in (o, h, l, c):
                    continue
                velas.append({
                    "tiempo": datetime.fromtimestamp(ts[i], tz=timezone.utc),
                    "open": round(o, 2),
                    "high": round(h, 2),
                    "low": round(l, 2),
                    "close": round(c, 2),
                })
            except Exception:
                continue
        if len(velas) > 50:
            return velas, "Yahoo Finance"
    except Exception:
        pass

    return [], "Sin datos"

# ──────────────────────────────────────────────────────────────────────────────
# UTILIDADES
# ──────────────────────────────────────────────────────────────────────────────

def ema(values: List[float], length: int) -> List[float]:
    if not values:
        return []
    k = 2 / (length + 1)
    out = [values[0]]
    for v in values[1:]:
        out.append(v * k + out[-1] * (1 - k))
    return out

def pivot_high(velas: List[Dict], left: int, right: int) -> List[Optional[float]]:
    out: List[Optional[float]] = [None] * len(velas)
    for i in range(left, len(velas) - right):
        h = velas[i]["high"]
        ok = True
        for j in range(i - left, i + right + 1):
            if j == i:
                continue
            if velas[j]["high"] >= h:
                ok = False
                break
        if ok:
            out[i] = h
    return out

def pivot_low(velas: List[Dict], left: int, right: int) -> List[Optional[float]]:
    out: List[Optional[float]] = [None] * len(velas)
    for i in range(left, len(velas) - right):
        l = velas[i]["low"]
        ok = True
        for j in range(i - left, i + right + 1):
            if j == i:
                continue
            if velas[j]["low"] <= l:
                ok = False
                break
        if ok:
            out[i] = l
    return out

def ajustar_sl(pips: int) -> Tuple[int, bool]:
    if pips < SL_MINIMO_PIPS:
        return SL_MINIMO_PIPS, True
    if pips > SL_MAXIMO_PIPS:
        return SL_MAXIMO_PIPS, True
    return pips, False

def calcular_niveles(entrada: float, direccion: str, sl_precio: float) -> Dict:
    sl_pips, ajustado = ajustar_sl(round(abs(sl_precio) / PIP))
    tp_pips = round(sl_pips * TP_RATIO)

    if direccion == "alcista":
        return {
            "sl": round(entrada - sl_pips * PIP, 2),
            "tp": round(entrada + tp_pips * PIP, 2),
            "sl_pips": sl_pips,
            "tp_pips": tp_pips,
            "ajustado": ajustado,
        }
    return {
        "sl": round(entrada + sl_pips * PIP, 2),
        "tp": round(entrada - tp_pips * PIP, 2),
        "sl_pips": sl_pips,
        "tp_pips": tp_pips,
        "ajustado": ajustado,
    }

def confirmacion_m1(velas_m1: List[Dict], direccion: str) -> bool:
    if len(velas_m1) < 3:
        return False

    ultima = velas_m1[-1]
    anterior = velas_m1[-2]

    if direccion == "alcista":
        if M1_REQUIRE_BREAK:
            return ultima["close"] > ultima["open"] and ultima["close"] > anterior["high"]
        return ultima["close"] > ultima["open"]

    if direccion == "bajista":
        if M1_REQUIRE_BREAK:
            return ultima["close"] < ultima["open"] and ultima["close"] < anterior["low"]
        return ultima["close"] < ultima["open"]

    return False

# ──────────────────────────────────────────────────────────────────────────────
# LÓGICA DE SEÑALES
# ──────────────────────────────────────────────────────────────────────────────

def detectar_senales_limpias(
    velas_m5: List[Dict],
    velas_m15: List[Dict],
    velas_m1: List[Dict],
    sesion: Optional[str],
) -> List[Dict]:
    if len(velas_m5) < 80 or len(velas_m15) < 210 or len(velas_m1) < 5:
        return []

    closes_m5 = [v["close"] for v in velas_m5]
    highs_m5 = [v["high"] for v in velas_m5]
    lows_m5 = [v["low"] for v in velas_m5]

    closes_m15 = [v["close"] for v in velas_m15]

    ema_local = ema(closes_m5, LOCAL_EMA)
    ema_fast_htf = ema(closes_m15, HTF_FAST)
    ema_slow_htf = ema(closes_m15, HTF_SLOW)

    bull_trend_htf = ema_fast_htf[-1] > ema_slow_htf[-1]
    bear_trend_htf = ema_fast_htf[-1] < ema_slow_htf[-1]

    ph = pivot_high(velas_m5, STRUCT_LEN, STRUCT_LEN)
    pl = pivot_low(velas_m5, STRUCT_LEN, STRUCT_LEN)
    ph_ext = pivot_high(velas_m5, EXT_LIQ_LEN, EXT_LIQ_LEN)
    pl_ext = pivot_low(velas_m5, EXT_LIQ_LEN, EXT_LIQ_LEN)

    structure_high = None
    structure_low = None
    ext_high = None
    ext_low = None
    market_bias = 0

    bull_ob = None
    bear_ob = None
    bull_ob_bar = None
    bear_ob_bar = None

    resultados: List[Dict] = []
    last_signal_time: Dict[str, datetime] = {
        "BUY": datetime.min.replace(tzinfo=timezone.utc),
        "SELL": datetime.min.replace(tzinfo=timezone.utc),
    }

    for i in range(20, len(velas_m5)):
        if ph[i]:
            structure_high = ph[i]
        if pl[i]:
            structure_low = pl[i]
        if ph_ext[i]:
            ext_high = ph_ext[i]
        if pl_ext[i]:
            ext_low = pl_ext[i]

        close = closes_m5[i]
        open_ = velas_m5[i]["open"]
        high = highs_m5[i]
        low = lows_m5[i]

        avg_range = sum((highs_m5[j] - lows_m5[j]) for j in range(max(0, i - 7), i + 1)) / min(8, i + 1)
        impulse = (high - low) > avg_range * IMPULSE_FACTOR
        bull_impulse = close > open_ and impulse
        bear_impulse = close < open_ and impulse

        bull_bos = structure_high is not None and close > structure_high
        bear_bos = structure_low is not None and close < structure_low

        bull_choch = market_bias == -1 and bull_bos
        bear_choch = market_bias == 1 and bear_bos

        if bull_bos:
            market_bias = 1
        if bear_bos:
            market_bias = -1

        bull_sweep = ext_low is not None and low < ext_low and close > ext_low
        bear_sweep = ext_high is not None and high > ext_high and close < ext_high

        # Crear bullish OB en M5
        if bull_trend_htf and (bull_sweep or bull_bos or bull_choch) and bull_impulse:
            for k in range(1, OB_LOOKBACK + 1):
                idx = i - k
                if idx >= 0 and velas_m5[idx]["close"] < velas_m5[idx]["open"]:
                    bull_ob = {
                        "high": velas_m5[idx]["open"],
                        "low": velas_m5[idx]["low"],
                    }
                    bull_ob_bar = i
                    break

        # Crear bearish OB en M5
        if bear_trend_htf and (bear_sweep or bear_bos or bear_choch) and bear_impulse:
            for k in range(1, OB_LOOKBACK + 1):
                idx = i - k
                if idx >= 0 and velas_m5[idx]["close"] > velas_m5[idx]["open"]:
                    bear_ob = {
                        "high": velas_m5[idx]["high"],
                        "low": velas_m5[idx]["open"],
                    }
                    bear_ob_bar = i
                    break

        ema_ok_buy = i >= EMA_SLOPE_BARS and close > ema_local[i] and (ema_local[i] - ema_local[i - EMA_SLOPE_BARS]) > 0
        ema_ok_sell = i >= EMA_SLOPE_BARS and close < ema_local[i] and (ema_local[i] - ema_local[i - EMA_SLOPE_BARS]) < 0

        bull_touch = False
        if bull_ob and bull_ob_bar is not None and (i - bull_ob_bar) <= RETEST_WINDOW_BARS:
            bull_touch = low <= bull_ob["high"] and high >= bull_ob["low"]

        bear_touch = False
        if bear_ob and bear_ob_bar is not None and (i - bear_ob_bar) <= RETEST_WINDOW_BARS:
            bear_touch = high >= bear_ob["low"] and low <= bear_ob["high"]

        bull_confirm_m5 = close > open_
        bear_confirm_m5 = close < open_

        now_t = velas_m5[i]["tiempo"]

        if bull_touch and bull_confirm_m5 and bull_trend_htf and ema_ok_buy and sesion:
            if confirmacion_m1(velas_m1, "alcista"):
                minutos_desde = (now_t - last_signal_time["BUY"]).total_seconds() / 60.0
                if minutos_desde >= M5_COOLDOWN_MIN:
                    entrada = round(bull_ob["high"], 2)
                    sl_raw = abs(entrada - (bull_ob["low"] - (bull_ob["high"] - bull_ob["low"]) * 0.5))
                    niveles = calcular_niveles(entrada, "alcista", sl_raw)
                    calidad = "🎯 SNIPER" if (bull_sweep or bull_choch) else "⭐ BUENA"
                    resultados.append({
                        "tf": "M5",
                        "accion": "BUY",
                        "direccion": "alcista",
                        "calidad": calidad,
                        "entrada": entrada,
                        "precio": round(close, 2),
                        "sl": niveles["sl"],
                        "tp": niveles["tp"],
                        "sl_pips": niveles["sl_pips"],
                        "tp_pips": niveles["tp_pips"],
                        "ajustado": niveles["ajustado"],
                        "sesion": sesion,
                        "timestamp": now_t,
                        "estructura": "CHoCH/BOS alcista" if (bull_choch or bull_bos) else "Retesteo alcista",
                        "liquidez": "Barrido alcista" if bull_sweep else "Sin barrido confirmado",
                        "confirmacion": "M1 alcista confirmada",
                    })
                    last_signal_time["BUY"] = now_t

        if bear_touch and bear_confirm_m5 and bear_trend_htf and ema_ok_sell and sesion:
            if confirmacion_m1(velas_m1, "bajista"):
                minutos_desde = (now_t - last_signal_time["SELL"]).total_seconds() / 60.0
                if minutos_desde >= M5_COOLDOWN_MIN:
                    entrada = round(bear_ob["low"], 2)
                    sl_raw = abs((bear_ob["high"] + (bear_ob["high"] - bear_ob["low"]) * 0.5) - entrada)
                    niveles = calcular_niveles(entrada, "bajista", sl_raw)
                    calidad = "🎯 SNIPER" if (bear_sweep or bear_choch) else "⭐ BUENA"
                    resultados.append({
                        "tf": "M5",
                        "accion": "SELL",
                        "direccion": "bajista",
                        "calidad": calidad,
                        "entrada": entrada,
                        "precio": round(close, 2),
                        "sl": niveles["sl"],
                        "tp": niveles["tp"],
                        "sl_pips": niveles["sl_pips"],
                        "tp_pips": niveles["tp_pips"],
                        "ajustado": niveles["ajustado"],
                        "sesion": sesion,
                        "timestamp": now_t,
                        "estructura": "CHoCH/BOS bajista" if (bear_choch or bear_bos) else "Retesteo bajista",
                        "liquidez": "Barrido bajista" if bear_sweep else "Sin barrido confirmado",
                        "confirmacion": "M1 bajista confirmada",
                    })
                    last_signal_time["SELL"] = now_t

    # Solo la señal más reciente por dirección
    limpias: Dict[str, Dict] = {}
    for s in resultados:
        k = s["accion"]
        if k not in limpias or s["timestamp"] > limpias[k]["timestamp"]:
            limpias[k] = s

    return list(limpias.values())

# ──────────────────────────────────────────────────────────────────────────────
# MENSAJES
# ──────────────────────────────────────────────────────────────────────────────

def firma_senal(s: Dict) -> str:
    return "|".join([
        s["tf"],
        s["accion"],
        f'{s["entrada"]:.2f}',
        f'{s["sl"]:.2f}',
        f'{s["tp"]:.2f}',
        s["sesion"],
        s["confirmacion"],
    ])

def formato_mensaje(signal: Dict, fuente_m5: str, fuente_m15: str, fuente_m1: str) -> str:
    emoji = "🟢" if signal["accion"] == "BUY" else "🔴"
    hora = hora_colombia().strftime("%H:%M")

    ajuste = " (ajustado)" if signal["ajustado"] else ""
    return (
        f"{emoji} <b>{signal['accion']} XAU/USD — M5</b>\n"
        f"💰 Precio actual: <b>${signal['precio']:,.2f}</b>\n"
        f"🎯 Entrada: <b>${signal['entrada']:,.2f}</b>\n"
        f"🛑 SL: <b>${signal['sl']:,.2f}</b> ({signal['sl_pips']} pips{ajuste})\n"
        f"💵 TP: <b>${signal['tp']:,.2f}</b> ({signal['tp_pips']} pips)\n"
        f"📐 Ratio: <b>1:{TP_RATIO:.1f}</b>\n"
        f"⭐ Calidad: <b>{signal['calidad']}</b>\n"
        f"📊 Estructura: {signal['estructura']}\n"
        f"💧 Liquidez: {signal['liquidez']}\n"
        f"⚡ Confirmación: {signal['confirmacion']}\n"
        f"🕐 Sesión: <b>{signal['sesion']}</b>\n"
        f"📡 Fuentes: M5={fuente_m5} | M15={fuente_m15} | M1={fuente_m1}\n"
        f"🇨🇴 Hora: {hora} COL\n\n"
        f"<i>Solo señal informativa. Verifica contexto antes de ejecutar.</i>"
    )

# ──────────────────────────────────────────────────────────────────────────────
# LOOP
# ──────────────────────────────────────────────────────────────────────────────

def analizar(estado_anterior: Dict, sesion: Optional[str]) -> Dict:
    velas_m5, fuente_m5 = obtener_velas(5)
    velas_m15, fuente_m15 = obtener_velas(15)
    velas_m1, fuente_m1 = obtener_velas(1)

    if len(velas_m5) < 80 or len(velas_m15) < 210 or len(velas_m1) < 5:
        print("  ⚠️ Datos insuficientes")
        return estado_anterior

    senales = detectar_senales_limpias(velas_m5, velas_m15, velas_m1, sesion)
    precio = velas_m5[-1]["close"]

    print(
        f"  M5 ${precio:,.2f} | Señales:{len(senales)} | "
        f"Fuentes: M5={fuente_m5}, M15={fuente_m15}, M1={fuente_m1} | "
        f"Sesión:{sesion or 'Fuera'}"
    )

    firmas_nuevas = [firma_senal(s) for s in senales]
    firmas_viejas = estado_anterior.get("firmas", [])

    if firmas_nuevas != firmas_viejas:
        for s in senales:
            enviar_telegram(formato_mensaje(s, fuente_m5, fuente_m15, fuente_m1))

        if not senales and firmas_viejas:
            enviar_telegram(
                f"ℹ️ <b>XAU/USD M5</b>\n"
                f"💰 ${precio:,.2f}\n"
                f"⏳ Sin señales activas en este cierre."
            )

    return {"firmas": firmas_nuevas}

def main() -> None:
    print("\n" + "=" * 66)
    print("   🥇 BOT XAU/USD — M15 + M5 + M1")
    print("   M15 = tendencia | M5 = setup | M1 = confirmación")
    print("   Señales limpias con filtro institucional")
    print(f"   SL: {SL_MINIMO_PIPS}-{SL_MAXIMO_PIPS} pips | TP ratio: {TP_RATIO}")
    print("   Sesiones Colombia: Londres 3-7am | NY 9-2pm")
    print("=" * 66)

    enviar_telegram(
        "🥇 <b>BOT XAU/USD INICIADO</b>\n\n"
        "📊 M15 = filtro de tendencia\n"
        "⚡ M5 = setup principal\n"
        "⏱️ M1 = confirmación final\n"
        "✅ EMA HTF 50/200\n"
        "✅ EMA local + pendiente\n"
        "✅ Cooldown anti-spam\n"
        "✅ Solo sesión Londres / Nueva York"
    )

    estado = {"firmas": []}
    ultimo_cierre_m5 = None

    while True:
        abierto, estado_mercado = mercado_abierto()
        sesion = sesion_activa()
        ahora = datetime.now(timezone.utc)
        hora_col = hora_colombia().strftime("%H:%M:%S")

        if not abierto:
            print(f"\n  😴 {hora_col} | {estado_mercado}")
            time.sleep(60)
            continue

        minuto_actual = ahora.minute
        cierre_m5 = (minuto_actual // 5) * 5

        if cierre_m5 != ultimo_cierre_m5:
            print(f"\n  {'=' * 54}")
            print(f"  ⚡ {hora_col} | Cierre vela M5 | Sesión: {sesion or 'Fuera'}")
            estado = analizar(estado, sesion)
            ultimo_cierre_m5 = cierre_m5

        time.sleep(10)

if __name__ == "__main__":
    main()
