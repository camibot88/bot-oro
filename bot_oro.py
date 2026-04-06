"""
Bot de Oro (XAU/USD) — M5 + M15
Analiza al cierre de cada vela
Fuente: TradingView (OANDA:XAUUSD)
SL: 15-60 pips | TP: ratio 1:2
Sesiones Colombia: Londres 3-7am | Nueva York 9-2pm
"""

import requests
import time
from datetime import datetime, timezone, timedelta

# ─── CONFIGURACIÓN ────────────────────────────────────────────────────────────

TELEGRAM_TOKEN   = "8601021313:AAFPKqFegDStA2CaTTHYHInCUERkQR7QgQM"
TELEGRAM_CHAT_ID = "926481853"

PIP            = 0.10
SL_MINIMO_PIPS = 15
SL_MAXIMO_PIPS = 60

LONDRES_INICIO = 3
LONDRES_FIN    = 7
NY_INICIO      = 9
NY_FIN         = 14

# ─── HORARIO Y SESIONES ───────────────────────────────────────────────────────

def hora_colombia():
    return datetime.now(timezone.utc) + timedelta(hours=-5)

def mercado_abierto():
    ahora  = hora_colombia()
    dia    = ahora.weekday()
    hora   = ahora.hour
    minuto = ahora.minute
    if dia == 5:
        return False, "Mercado cerrado — Sabado"
    if dia == 6 and hora < 18:
        return False, f"Mercado cerrado — Abre domingo 6pm COL (faltan {18-hora}h)"
    if dia == 4 and hora >= 17:
        return False, "Mercado cerrado — Fin de semana"
    if hora == 17:
        return False, f"Pausa diaria 5-6pm COL (reabre en {60-minuto} min)"
    return True, "Mercado abierto"

def sesion_activa():
    abierto, _ = mercado_abierto()
    if not abierto:
        return None
    hora = hora_colombia().hour
    if LONDRES_INICIO <= hora < LONDRES_FIN:
        return "Londres 🇬🇧"
    if NY_INICIO <= hora < NY_FIN:
        return "Nueva York 🇺🇸"
    return None

def segundos_para_cierre_vela(intervalo_min):
    """Calcula cuántos segundos faltan para el cierre de la vela actual"""
    ahora   = datetime.now(timezone.utc)
    segundo = ahora.minute * 60 + ahora.second
    periodo = intervalo_min * 60
    resto   = periodo - (segundo % periodo)
    return resto

# ─── TELEGRAM ─────────────────────────────────────────────────────────────────

def enviar_telegram(mensaje):
    url   = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    datos = {"chat_id": TELEGRAM_CHAT_ID, "text": mensaje, "parse_mode": "HTML"}
    try:
        r = requests.post(url, data=datos, timeout=10)
        if r.status_code == 200:
            print("  ✅ Telegram enviado")
        else:
            print(f"  ⚠️  Error Telegram: {r.status_code}")
    except Exception as e:
        print(f"  ⚠️  Error: {e}")

# ─── OBTENER VELAS ────────────────────────────────────────────────────────────

def obtener_velas(intervalo_min, cantidad=150):
    """
    Intenta TradingView primero.
    Si falla usa Yahoo Finance como respaldo.
    """
    # Intento 1: TradingView
    try:
        tf_map = {5: "5", 15: "15"}
        tf     = tf_map.get(intervalo_min, "15")
        ahora  = int(datetime.now(timezone.utc).timestamp())
        desde  = ahora - (intervalo_min * 60 * cantidad)
        url    = "https://history.tradingview.com/history"
        params = {
            "symbol":     "OANDA:XAUUSD",
            "resolution": tf,
            "from":       desde,
            "to":         ahora,
        }
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Referer":    "https://www.tradingview.com",
            "Origin":     "https://www.tradingview.com",
        }
        r     = requests.get(url, params=params, headers=headers, timeout=15)
        datos = r.json()

        if datos.get("s") == "ok" and len(datos.get("t", [])) > 20:
            velas = []
            for i in range(len(datos["t"])):
                try:
                    velas.append({
                        "tiempo": datetime.fromtimestamp(datos["t"][i]).strftime("%Y-%m-%d %H:%M"),
                        "open":   round(float(datos["o"][i]), 2),
                        "high":   round(float(datos["h"][i]), 2),
                        "low":    round(float(datos["l"][i]), 2),
                        "close":  round(float(datos["c"][i]), 2),
                    })
                except:
                    continue
            if len(velas) > 20:
                return velas, "TradingView"
    except:
        pass

    # Intento 2: Yahoo Finance (respaldo)
    try:
        iv_map = {5: "5m", 15: "15m"}
        iv     = iv_map.get(intervalo_min, "15m")
        url    = "https://query1.finance.yahoo.com/v8/finance/chart/GC=F"
        params = {"interval": iv, "range": "5d"}
        r      = requests.get(url, params=params, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        datos  = r.json()
        chart  = datos["chart"]["result"][0]
        ts     = chart["timestamp"]
        px     = chart["indicators"]["quote"][0]
        velas  = []
        for i in range(len(ts)):
            try:
                velas.append({
                    "tiempo": datetime.fromtimestamp(ts[i]).strftime("%Y-%m-%d %H:%M"),
                    "open":   round(px["open"][i],  2),
                    "high":   round(px["high"][i],  2),
                    "low":    round(px["low"][i],   2),
                    "close":  round(px["close"][i], 2),
                })
            except:
                continue
        if len(velas) > 20:
            return velas, "Yahoo Finance"
    except:
        pass

    return [], "Sin datos"

# ─── PIPS ─────────────────────────────────────────────────────────────────────

def ajustar_sl(pips):
    if pips < SL_MINIMO_PIPS: return SL_MINIMO_PIPS, True
    if pips > SL_MAXIMO_PIPS: return SL_MAXIMO_PIPS, True
    return pips, False

def calcular_niveles(entrada, direccion, sl_dolares):
    sl_pips, ajustado = ajustar_sl(round(abs(sl_dolares) / PIP))
    tp_pips = sl_pips * 2
    if direccion == "alcista":
        return {
            "sl":       round(entrada - sl_pips * PIP, 2),
            "tp":       round(entrada + tp_pips * PIP, 2),
            "sl_pips":  sl_pips,
            "tp_pips":  tp_pips,
            "ajustado": ajustado,
        }
    else:
        return {
            "sl":       round(entrada + sl_pips * PIP, 2),
            "tp":       round(entrada - tp_pips * PIP, 2),
            "sl_pips":  sl_pips,
            "tp_pips":  tp_pips,
            "ajustado": ajustado,
        }

# ─── DETECTAR ZONAS ───────────────────────────────────────────────────────────

def detectar_order_blocks(velas):
    resultado = []
    lookback  = 5
    for i in range(lookback, len(velas) - 3):
        v      = velas[i]
        cuerpo = abs(v["close"] - v["open"])
        prom   = sum(abs(x["close"] - x["open"]) for x in velas[i-lookback:i]) / lookback
        if prom == 0 or cuerpo < prom * 1.2:
            continue
        alcista = v["close"] > v["open"]
        fuerte  = any(
            (nc["close"] > v["high"] if alcista else nc["close"] < v["low"])
            for nc in velas[i+1:i+4]
        )
        if fuerte:
            resultado.append({
                "tipo":      "ORDER BLOCK",
                "direccion": "alcista" if alcista else "bajista",
                "superior":  round(max(v["open"], v["close"]), 2),
                "inferior":  round(min(v["open"], v["close"]), 2),
            })
    return resultado[-5:]

def detectar_demanda(velas):
    resultado = []
    lookback  = 8
    for i in range(lookback, len(velas) - 4):
        v         = velas[i]
        prev      = velas[i-lookback:i]
        min_local = min(x["low"]  for x in prev)
        max_local = max(x["high"] for x in prev)
        rango     = max_local - min_local
        if rango == 0 or v["low"] > min_local * 1.005 or v["close"] <= v["open"]:
            continue
        cuerpo = abs(v["close"] - v["open"])
        rebote = any(
            nc["close"] > v["high"] and abs(nc["close"] - nc["open"]) > cuerpo * 0.8
            for nc in velas[i+1:i+5]
        )
        if rebote:
            m = rango * 0.008
            resultado.append({
                "tipo":      "ZONA DE DEMANDA",
                "direccion": "alcista",
                "superior":  round(v["low"] + m,       2),
                "inferior":  round(v["low"] - m * 0.3, 2),
            })
    return resultado[-4:]

def detectar_oferta(velas):
    resultado = []
    lookback  = 8
    for i in range(lookback, len(velas) - 4):
        v         = velas[i]
        prev      = velas[i-lookback:i]
        max_local = max(x["high"] for x in prev)
        min_local = min(x["low"]  for x in prev)
        rango     = max_local - min_local
        if rango == 0 or v["high"] < max_local * 0.995 or v["close"] >= v["open"]:
            continue
        cuerpo = abs(v["close"] - v["open"])
        caida  = any(
            nc["close"] < v["low"] and abs(nc["close"] - nc["open"]) > cuerpo * 0.8
            for nc in velas[i+1:i+5]
        )
        if caida:
            m = rango * 0.008
            resultado.append({
                "tipo":      "ZONA DE OFERTA",
                "direccion": "bajista",
                "superior":  round(v["high"] + m * 0.3, 2),
                "inferior":  round(v["high"] - m,       2),
            })
    return resultado[-4:]

def detectar_institucionales(velas):
    resultado = []
    maximo    = max(v["high"] for v in velas)
    minimo    = min(v["low"]  for v in velas)
    rango     = maximo - minimo
    if rango == 0:
        return resultado
    for fib in [0.236, 0.382, 0.5, 0.618, 0.786]:
        pf = minimo + rango * fib
        pr = round(pf / 50) * 50
        if abs(pf - pr) / rango < 0.03:
            toques = sum(
                1 for v in velas
                if abs(v["low"]  - pr) < rango * 0.015
                or abs(v["high"] - pr) < rango * 0.015
            )
            if toques >= 2:
                resultado.append({
                    "superior": round(pr + rango * 0.006, 2),
                    "inferior": round(pr - rango * 0.006, 2),
                    "precio":   pr,
                    "fib":      f"{fib*100:.1f}%",
                })
    return resultado

def detectar_bos_choch(velas):
    if len(velas) < 10:
        return None
    s        = velas[-10:]
    max_prev = max(v["high"] for v in s[:-2])
    min_prev = min(v["low"]  for v in s[:-2])
    u        = velas[-1]
    p        = velas[-2]
    ref      = velas[-6] if len(velas) >= 6 else velas[0]
    tend_alc = p["close"] > ref["close"]
    tend_baj = p["close"] < ref["close"]
    if tend_alc and u["close"] < min_prev:
        return {"dir": "bajista", "tipo": "CHoCH", "desc": "⚠️ CHoCH BAJISTA — posible reversión"}
    if tend_baj and u["close"] > max_prev:
        return {"dir": "alcista", "tipo": "CHoCH", "desc": "✅ CHoCH ALCISTA — posible reversión al alza"}
    if tend_alc and u["close"] > max_prev:
        return {"dir": "alcista", "tipo": "BOS",   "desc": "📈 BOS ALCISTA — tendencia sigue arriba"}
    if tend_baj and u["close"] < min_prev:
        return {"dir": "bajista", "tipo": "BOS",   "desc": "📉 BOS BAJISTA — tendencia sigue abajo"}
    return None

def detectar_barrido(velas):
    if len(velas) < 6:
        return None
    s  = velas[-10:]
    u  = velas[-1]
    p  = velas[-2]
    mn = min(v["low"]  for v in s[:-2])
    mx = max(v["high"] for v in s[:-2])
    if p["low"] < mn and p["close"] > mn and u["close"] > p["close"]:
        return {"dir": "alcista", "desc": "💧 Barrido ALCISTA — stops cazados, institucionales comprando"}
    if p["high"] > mx and p["close"] < mx and u["close"] < p["close"]:
        return {"dir": "bajista", "desc": "💧 Barrido BAJISTA — stops cazados, institucionales vendiendo"}
    return None

# ─── CALCULAR SEÑALES ─────────────────────────────────────────────────────────

def calcular_senales(velas, sesion):
    if not velas:
        return []

    precio    = velas[-1]["close"]
    obs       = detectar_order_blocks(velas)
    dzs       = detectar_demanda(velas)
    zos       = detectar_oferta(velas)
    izs       = detectar_institucionales(velas)
    bos       = detectar_bos_choch(velas)
    barrido   = detectar_barrido(velas)
    izs_cerca = [z for z in izs if z["inferior"] <= precio <= z["superior"]]
    senales   = []

    p_sesion  = 1 if sesion   else 0
    p_inst    = 1 if izs_cerca else 0

    # COMPRAS
    for zona in [z for z in obs if z["direccion"] == "alcista"] + dzs:
        en_zona    = zona["inferior"] <= precio <= zona["superior"]
        cerca_zona = precio <= zona["superior"] * 1.003
        if not (en_zona or cerca_zona):
            continue
        bos_ok  = bos     and bos["dir"]     == "alcista"
        barr_ok = barrido and barrido["dir"] == "alcista"
        conf    = 1 + p_sesion + p_inst + (1 if bos_ok else 0) + (1 if barr_ok else 0)
        entrada = zona["superior"]
        sl_raw  = abs(entrada - (zona["inferior"] - (zona["superior"] - zona["inferior"]) * 0.5))
        niv     = calcular_niveles(entrada, "alcista", sl_raw)
        calidad = "🎯 SNIPER" if conf >= 4 else ("⭐ BUENA" if conf == 3 else "⚠️ DEBIL")
        if calidad == "⚠️ DEBIL":
            continue
        senales.append({
            "accion":   "🟢 COMPRA",
            "calidad":  calidad,
            "conf":     conf,
            "estado":   "EN ZONA ✅" if en_zona else "CERCA ⚠️",
            "precio":   precio,
            "entrada":  round(entrada, 2),
            "sl":       niv["sl"],
            "tp":       niv["tp"],
            "sl_pips":  niv["sl_pips"],
            "tp_pips":  niv["tp_pips"],
            "ajustado": niv["ajustado"],
            "zona":     zona["tipo"],
            "bos":      bos["desc"]     if bos_ok  else "No confirmado",
            "barrido":  barrido["desc"] if barr_ok else "No detectado",
            "sesion":   sesion or "Fuera de sesion",
        })

    # VENTAS
    for zona in [z for z in obs if z["direccion"] == "bajista"] + zos:
        en_zona    = zona["inferior"] <= precio <= zona["superior"]
        cerca_zona = precio >= zona["inferior"] * 0.997
        if not (en_zona or cerca_zona):
            continue
        bos_ok  = bos     and bos["dir"]     == "bajista"
        barr_ok = barrido and barrido["dir"] == "bajista"
        conf    = 1 + p_sesion + p_inst + (1 if bos_ok else 0) + (1 if barr_ok else 0)
        entrada = zona["inferior"]
        sl_raw  = abs((zona["superior"] + (zona["superior"] - zona["inferior"]) * 0.5) - entrada)
        niv     = calcular_niveles(entrada, "bajista", sl_raw)
        calidad = "🎯 SNIPER" if conf >= 4 else ("⭐ BUENA" if conf == 3 else "⚠️ DEBIL")
        if calidad == "⚠️ DEBIL":
            continue
        senales.append({
            "accion":   "🔴 VENTA",
            "calidad":  calidad,
            "conf":     conf,
            "estado":   "EN ZONA ✅" if en_zona else "CERCA ⚠️",
            "precio":   precio,
            "entrada":  round(entrada, 2),
            "sl":       niv["sl"],
            "tp":       niv["tp"],
            "sl_pips":  niv["sl_pips"],
            "tp_pips":  niv["tp_pips"],
            "ajustado": niv["ajustado"],
            "zona":     zona["tipo"],
            "bos":      bos["desc"]     if bos_ok  else "No confirmado",
            "barrido":  barrido["desc"] if barr_ok else "No detectado",
            "sesion":   sesion or "Fuera de sesion",
        })

    # Ordenar por calidad
    orden = {"🎯 SNIPER": 0, "⭐ BUENA": 1}
    senales.sort(key=lambda s: orden.get(s["calidad"], 2))
    return senales, obs, dzs, zos, izs, bos, barrido

# ─── FORMATO TELEGRAM ─────────────────────────────────────────────────────────

def formato_mensaje(tf, senales, precio, obs, dzs, zos, izs, bos, barrido, sesion, fuente):
    emoji = "⚡" if tf == "M5" else "📊"
    hora  = hora_colombia().strftime("%H:%M")

    txt  = f"{emoji} <b>XAU/USD — {tf}</b>\n"
    txt += f"💰 Precio: <b>${precio:,.2f}</b>  |  🕐 {hora} COL\n"
    txt += f"📡 Fuente: {fuente}\n"
    txt += f"━━━━━━━━━━━━━━━━━━━━━━\n"
    txt += f"{'🟢 Sesion: ' + sesion if sesion else '🔴 Fuera de sesion'}\n"
    if bos:     txt += f"📐 {bos['desc']}\n"
    if barrido: txt += f"💧 {barrido['desc']}\n"
    txt += f"▣ OB:{len(obs)}  ◈ DZ:{len(dzs)}  ◇ ZO:{len(zos)}  ◆ IZ:{len(izs)}\n"
    txt += f"━━━━━━━━━━━━━━━━━━━━━━\n"

    if not senales:
        txt += f"\n⏳ Sin señales activas en {tf}"
    else:
        txt += f"\n🚨 <b>{len(senales)} SEÑAL(ES) — {tf}</b>\n"
        for i, s in enumerate(senales, 1):
            ajuste = " (ajustado)" if s["ajustado"] else ""
            txt += f"\n<b>#{i} {s['accion']}  {s['calidad']}</b>\n"
            txt += f"Estado:        {s['estado']}\n"
            txt += f"🎯 Entrada:    <b>${s['entrada']:,.2f}</b>\n"
            txt += f"🛑 Stop Loss:  <b>${s['sl']:,.2f}</b> ({s['sl_pips']} pips{ajuste})\n"
            txt += f"💵 Take Profit:<b>${s['tp']:,.2f}</b> ({s['tp_pips']} pips)\n"
            txt += f"📐 Ratio:      1:2\n"
            txt += f"⚡ Confluencia:{s['conf']}/5\n"
            txt += f"📌 Zona:       {s['zona']}\n"
            txt += f"📐 Estructura: {s['bos']}\n"
            txt += f"💧 Liquidez:   {s['barrido']}\n"

    txt += f"\n━━━━━━━━━━━━━━━━━━━━━━\n"
    txt += f"<i>⚠️ Practica en cuenta demo primero</i>"
    return txt

# ─── ANALIZAR TEMPORALIDAD ────────────────────────────────────────────────────

def analizar(tf, intervalo_min, estado_anterior, sesion):
    """
    Analiza al cierre de la vela.
    Solo envía Telegram si las señales son nuevas o cambiaron.
    """
    velas, fuente = obtener_velas(intervalo_min)
    if len(velas) < 20:
        return estado_anterior

    resultado = calcular_senales(velas, sesion)
    senales, obs, dzs, zos, izs, bos, barrido = resultado
    precio    = velas[-1]["close"]

    # Comparar con señales anteriores
    entradas_nuevas = [s["entrada"] for s in senales]
    entradas_viejas = estado_anterior.get("entradas", [])

    print(f"  {tf} ${precio:,.2f} | "
          f"OB:{len(obs)} DZ:{len(dzs)} ZO:{len(zos)} IZ:{len(izs)} | "
          f"Señales:{len(senales)} | Fuente:{fuente}")

    if entradas_nuevas and entradas_nuevas != entradas_viejas:
        msg = formato_mensaje(tf, senales, precio, obs, dzs, zos, izs, bos, barrido, sesion, fuente)
        enviar_telegram(msg)
    elif not entradas_nuevas and entradas_viejas:
        enviar_telegram(
            f"{'⚡' if tf=='M5' else '📊'} <b>XAU/USD {tf}</b>\n"
            f"💰 ${precio:,.2f}\n"
            f"⏳ Señales anteriores ya no activas."
        )

    return {"entradas": entradas_nuevas}

# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    print("\n" + "="*58)
    print("   🥇 BOT XAU/USD — M5 + M15")
    print("   Analiza al cierre de cada vela")
    print("   Señales separadas por temporalidad")
    print(f"   SL: {SL_MINIMO_PIPS}-{SL_MAXIMO_PIPS} pips | TP: ratio 1:2")
    print("   Sesiones Colombia: Londres 3-7am | NY 9-2pm")
    print("="*58)

    enviar_telegram(
        "🥇 <b>BOT XAU/USD INICIADO</b>\n\n"
        "⚡ M5  — analiza al cierre de cada vela de 5 min\n"
        "📊 M15 — analiza al cierre de cada vela de 15 min\n\n"
        f"✅ SL: {SL_MINIMO_PIPS}-{SL_MAXIMO_PIPS} pips | TP: ratio 1:2\n"
        "✅ Señales SNIPER y BUENAS solamente\n"
        "✅ Mensajes separados por temporalidad\n\n"
        "🇨🇴 Sesiones activas:\n"
        "🇬🇧 Londres:    3:00am - 7:00am\n"
        "🇺🇸 Nueva York: 9:00am - 2:00pm"
    )

    estado_m5  = {"entradas": []}
    estado_m15 = {"entradas": []}

    ultimo_cierre_m5  = 0
    ultimo_cierre_m15 = 0

    while True:
        abierto, estado_mercado = mercado_abierto()
        sesion = sesion_activa()
        ahora  = datetime.now(timezone.utc)
        hora_col = hora_colombia().strftime("%H:%M:%S")

        if not abierto:
            print(f"\n  😴 {hora_col} | {estado_mercado}")
            time.sleep(60)
            continue

        # Detectar cierre de vela M5
        minuto_actual = ahora.minute
        cierre_m5     = (minuto_actual // 5) * 5
        if cierre_m5 != ultimo_cierre_m5:
            print(f"\n  {'='*54}")
            print(f"  ⚡ {hora_col} | Cierre vela M5 | Sesion: {sesion or 'Fuera'}")
            estado_m5     = analizar("M5", 5, estado_m5, sesion)
            ultimo_cierre_m5 = cierre_m5

        # Detectar cierre de vela M15
        cierre_m15 = (minuto_actual // 15) * 15
        if cierre_m15 != ultimo_cierre_m15:
            print(f"\n  {'='*54}")
            print(f"  📊 {hora_col} | Cierre vela M15 | Sesion: {sesion or 'Fuera'}")
            estado_m15     = analizar("M15", 15, estado_m15, sesion)
            ultimo_cierre_m15 = cierre_m15

        time.sleep(10)  # revisa cada 10 segundos si cerró una vela

if __name__ == "__main__":
    main()
