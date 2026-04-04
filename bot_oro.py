"""
Bot de Oro (XAU/USD) — Entradas Sniper
SL calculado por zona con límites: mínimo 15 pips / máximo 60 pips
TP siempre el doble del SL (ratio 1:2)
Temporalidades: M15 + H1 | Sesiones Colombia (UTC-5)
"""

import requests
import time
from datetime import datetime, timezone, timedelta

# ─── CONFIGURACIÓN ────────────────────────────────────────────────────────────

TELEGRAM_TOKEN   = "8601021313:AAFPKqFegDStA2CaTTHYHInCUERkQR7QgQM"
TELEGRAM_CHAT_ID = "926481853"

# En el Oro: 1 pip = $0.10
PIP            = 0.10
SL_MINIMO_PIPS = 15
SL_MAXIMO_PIPS = 60

# Sesiones Colombia (UTC-5)
SESIONES = [
    {"nombre": "Londres 🇬🇧",    "inicio": 3,  "fin": 7},
    {"nombre": "Nueva York 🇺🇸", "inicio": 9,  "fin": 14},
]

# ─── TELEGRAM ─────────────────────────────────────────────────────────────────

def enviar_telegram(mensaje):
    url   = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    datos = {"chat_id": TELEGRAM_CHAT_ID, "text": mensaje, "parse_mode": "HTML"}
    try:
        r = requests.post(url, data=datos, timeout=10)
        if r.status_code == 200:
            print("  ✅ Telegram enviado")
        else:
            print(f"  ⚠️  Error: {r.text}")
    except Exception as e:
        print(f"  ⚠️  Error Telegram: {e}")

# ─── SESIONES ─────────────────────────────────────────────────────────────────

def hora_colombia():
    return datetime.now(timezone.utc) + timedelta(hours=-5)

def sesion_activa():
    hora = hora_colombia().hour
    for s in SESIONES:
        if s["inicio"] <= hora < s["fin"]:
            return s["nombre"]
    return None

def proxima_sesion():
    hora = hora_colombia().hour
    if hora < 3:
        return f"Londres a las 3:00am (faltan {3-hora}h)"
    elif hora < 9:
        return f"Nueva York a las 9:00am (faltan {9-hora}h)"
    else:
        return f"Londres mañana a las 3:00am"

# ─── PIPS ─────────────────────────────────────────────────────────────────────

def dolares_a_pips(dolares):
    """Convierte dólares a pips. En el Oro 1 pip = $0.10"""
    return round(dolares / PIP)

def pips_a_dolares(pips):
    return round(pips * PIP, 2)

def calcular_sl_tp(entrada, direccion, sl_zona_dolares):
    """
    Calcula SL y TP respetando los límites de pips.
    Si el SL de la zona está fuera del rango 15-60 pips,
    lo ajusta al límite más cercano.
    Retorna None si la señal debe descartarse.
    """
    sl_pips_zona = dolares_a_pips(abs(sl_zona_dolares))

    # Ajustar dentro del rango permitido
    if sl_pips_zona < SL_MINIMO_PIPS:
        sl_pips = SL_MINIMO_PIPS
    elif sl_pips_zona > SL_MAXIMO_PIPS:
        sl_pips = SL_MAXIMO_PIPS
    else:
        sl_pips = sl_pips_zona

    tp_pips = sl_pips * 2  # ratio 1:2 siempre

    sl_dolares = pips_a_dolares(sl_pips)
    tp_dolares = pips_a_dolares(tp_pips)

    if direccion == "alcista":
        stop_loss   = round(entrada - sl_dolares, 2)
        take_profit = round(entrada + tp_dolares, 2)
    else:
        stop_loss   = round(entrada + sl_dolares, 2)
        take_profit = round(entrada - tp_dolares, 2)

    return {
        "stop_loss":   stop_loss,
        "take_profit": take_profit,
        "sl_pips":     sl_pips,
        "tp_pips":     tp_pips,
        "sl_original_pips": sl_pips_zona,
        "ajustado":    sl_pips != sl_pips_zona
    }

# ─── OBTENER VELAS ────────────────────────────────────────────────────────────

def obtener_velas(intervalo, rango):
    url        = "https://query1.finance.yahoo.com/v8/finance/chart/GC=F"
    parametros = {"interval": intervalo, "range": rango}
    headers    = {"User-Agent": "Mozilla/5.0"}
    try:
        r     = requests.get(url, params=parametros, headers=headers, timeout=10)
        datos = r.json()
        chart   = datos["chart"]["result"][0]
        tiempos = chart["timestamp"]
        precios = chart["indicators"]["quote"][0]
        velas   = []
        for i in range(len(tiempos)):
            try:
                v = {
                    "tiempo": datetime.fromtimestamp(tiempos[i]).strftime("%Y-%m-%d %H:%M"),
                    "open":   round(precios["open"][i],  2),
                    "high":   round(precios["high"][i],  2),
                    "low":    round(precios["low"][i],   2),
                    "close":  round(precios["close"][i], 2),
                    "volume": precios["volume"][i] or 0
                }
                if None not in v.values():
                    velas.append(v)
            except:
                continue
        return velas
    except Exception as e:
        print(f"  Error {intervalo}: {e}")
        return []

# ─── DETECTAR ZONAS ───────────────────────────────────────────────────────────

def detectar_order_blocks(velas):
    resultados = []
    lookback   = 5
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
            resultados.append({
                "tipo":          "ORDER BLOCK",
                "direccion":     "alcista" if alcista else "bajista",
                "zona_superior": round(max(v["open"], v["close"]), 2),
                "zona_inferior": round(min(v["open"], v["close"]), 2),
                "fuerza":        round(cuerpo / prom, 1),
                "tiempo":        v["tiempo"]
            })
    return resultados[-4:]

def detectar_zonas_demanda(velas):
    resultados = []
    lookback   = 8
    for i in range(lookback, len(velas) - 4):
        v         = velas[i]
        prev      = velas[i-lookback:i]
        min_local = min(x["low"]  for x in prev)
        max_local = max(x["high"] for x in prev)
        rango     = max_local - min_local
        if rango == 0:
            continue
        if v["low"] <= min_local * 1.005 and v["close"] > v["open"]:
            cuerpo = abs(v["close"] - v["open"])
            rebote = any(
                nc["close"] > v["high"] and abs(nc["close"] - nc["open"]) > cuerpo * 0.8
                for nc in velas[i+1:i+5]
            )
            if rebote:
                margen = rango * 0.008
                resultados.append({
                    "tipo":          "ZONA DE DEMANDA",
                    "direccion":     "alcista",
                    "zona_superior": round(v["low"] + margen,       2),
                    "zona_inferior": round(v["low"] - margen * 0.3, 2),
                    "fuerza":        round((v["high"] - v["low"]) / rango, 2),
                    "tiempo":        v["tiempo"]
                })
    return resultados[-3:]

def detectar_zonas_oferta(velas):
    resultados = []
    lookback   = 8
    for i in range(lookback, len(velas) - 4):
        v         = velas[i]
        prev      = velas[i-lookback:i]
        max_local = max(x["high"] for x in prev)
        min_local = min(x["low"]  for x in prev)
        rango     = max_local - min_local
        if rango == 0:
            continue
        if v["high"] >= max_local * 0.995 and v["close"] < v["open"]:
            cuerpo = abs(v["close"] - v["open"])
            caida  = any(
                nc["close"] < v["low"] and abs(nc["close"] - nc["open"]) > cuerpo * 0.8
                for nc in velas[i+1:i+5]
            )
            if caida:
                margen = rango * 0.008
                resultados.append({
                    "tipo":          "ZONA DE OFERTA",
                    "direccion":     "bajista",
                    "zona_superior": round(v["high"] + margen * 0.3, 2),
                    "zona_inferior": round(v["high"] - margen,       2),
                    "fuerza":        round((v["high"] - v["low"]) / rango, 2),
                    "tiempo":        v["tiempo"]
                })
    return resultados[-3:]

def detectar_institucionales(velas):
    resultados = []
    maximo = max(v["high"] for v in velas)
    minimo = min(v["low"]  for v in velas)
    rango  = maximo - minimo
    if rango == 0:
        return resultados
    for fib in [0.236, 0.382, 0.5, 0.618, 0.786]:
        precio_fib     = minimo + rango * fib
        precio_redondo = round(precio_fib / 50) * 50
        if abs(precio_fib - precio_redondo) / rango < 0.03:
            toques = sum(
                1 for v in velas
                if abs(v["low"]  - precio_redondo) < rango * 0.015
                or abs(v["high"] - precio_redondo) < rango * 0.015
            )
            if toques >= 2:
                resultados.append({
                    "tipo":          "ZONA INSTITUCIONAL",
                    "precio":        precio_redondo,
                    "zona_superior": round(precio_redondo + rango * 0.006, 2),
                    "zona_inferior": round(precio_redondo - rango * 0.006, 2),
                    "fibonacci":     f"{fib*100:.1f}%",
                    "toques":        toques
                })
    return resultados[-3:]

# ─── BOS / CHoCH ──────────────────────────────────────────────────────────────

def detectar_bos_choch(velas):
    if len(velas) < 10:
        return None
    ultimas    = velas[-10:]
    max_previo = max(v["high"] for v in ultimas[:-2])
    min_previo = min(v["low"]  for v in ultimas[:-2])
    ultima     = velas[-1]
    penultima  = velas[-2]
    tend_alc   = penultima["close"] > velas[-5]["close"]
    tend_baj   = penultima["close"] < velas[-5]["close"]

    if tend_alc and ultima["close"] < min_previo:
        return {"tipo": "CHoCH", "direccion": "bajista",
                "descripcion": "⚠️ CHoCH BAJISTA — posible reversión a la baja"}
    if tend_baj and ultima["close"] > max_previo:
        return {"tipo": "CHoCH", "direccion": "alcista",
                "descripcion": "✅ CHoCH ALCISTA — posible reversión al alza"}
    if tend_alc and ultima["close"] > max_previo:
        return {"tipo": "BOS", "direccion": "alcista",
                "descripcion": "📈 BOS ALCISTA — tendencia sigue arriba"}
    if tend_baj and ultima["close"] < min_previo:
        return {"tipo": "BOS", "direccion": "bajista",
                "descripcion": "📉 BOS BAJISTA — tendencia sigue abajo"}
    return None

# ─── BARRIDO DE LIQUIDEZ ──────────────────────────────────────────────────────

def detectar_barrido(velas):
    if len(velas) < 6:
        return None
    recientes  = velas[-10:]
    ultima     = velas[-1]
    penultima  = velas[-2]
    min_local  = min(v["low"]  for v in recientes[:-2])
    max_local  = max(v["high"] for v in recientes[:-2])

    if (penultima["low"] < min_local and
        penultima["close"] > min_local and
        ultima["close"] > penultima["close"]):
        return {"tipo": "BARRIDO", "direccion": "alcista",
                "descripcion": "💧 Barrido ALCISTA — stops cazados, institucionales comprando"}

    if (penultima["high"] > max_local and
        penultima["close"] < max_local and
        ultima["close"] < penultima["close"]):
        return {"tipo": "BARRIDO", "direccion": "bajista",
                "descripcion": "💧 Barrido BAJISTA — stops cazados, institucionales vendiendo"}
    return None

# ─── SEÑALES SNIPER ───────────────────────────────────────────────────────────

def calcular_senales(velas, obs, dzs, zos, izs, bos_choch, barrido, sesion):
    if not velas:
        return []

    precio_actual     = velas[-1]["close"]
    senales           = []
    izs_cerca         = [z for z in izs if z["zona_inferior"] <= precio_actual <= z["zona_superior"]]
    punto_sesion      = 1 if sesion      else 0
    punto_inst        = 1 if izs_cerca   else 0
    punto_barrido     = 1 if barrido     else 0
    punto_bos         = 1 if bos_choch   else 0

    # COMPRAS
    for zona in [z for z in obs if z["direccion"] == "alcista"] + dzs:
        en_zona    = zona["zona_inferior"] <= precio_actual <= zona["zona_superior"]
        cerca_zona = precio_actual <= zona["zona_superior"] * 1.003
        if not (en_zona or cerca_zona):
            continue

        bos_ok     = bos_choch and bos_choch["direccion"] == "alcista"
        barrido_ok = barrido   and barrido["direccion"]   == "alcista"
        confluencia = 1 + punto_sesion + punto_inst + (1 if bos_ok else 0) + (1 if barrido_ok else 0)

        # Calcular SL desde la zona
        entrada          = zona["zona_superior"]
        sl_zona_dolares  = entrada - (zona["zona_inferior"] - (zona["zona_superior"] - zona["zona_inferior"]) * 0.5)
        niveles          = calcular_sl_tp(entrada, "alcista", sl_zona_dolares)

        if confluencia >= 4:   calidad = "🎯 SNIPER"
        elif confluencia == 3: calidad = "⭐ BUENA"
        else:                  calidad = "⚠️ DÉBIL"

        senales.append({
            "accion":       "🟢 COMPRA",
            "calidad":      calidad,
            "confluencia":  confluencia,
            "estado":       "EN ZONA ✅" if en_zona else "CERCA ⚠️",
            "precio_actual": precio_actual,
            "entrada":      round(entrada, 2),
            "stop_loss":    niveles["stop_loss"],
            "take_profit":  niveles["take_profit"],
            "sl_pips":      niveles["sl_pips"],
            "tp_pips":      niveles["tp_pips"],
            "sl_ajustado":  niveles["ajustado"],
            "riesgo":       pips_a_dolares(niveles["sl_pips"]),
            "ganancia":     pips_a_dolares(niveles["tp_pips"]),
            "zona_origen":  zona["tipo"],
            "bos_choch":    bos_choch["descripcion"] if bos_ok     else "No confirmado",
            "barrido":      barrido["descripcion"]   if barrido_ok else "No detectado",
            "sesion":       sesion or "Fuera de sesión",
        })

    # VENTAS
    for zona in [z for z in obs if z["direccion"] == "bajista"] + zos:
        en_zona    = zona["zona_inferior"] <= precio_actual <= zona["zona_superior"]
        cerca_zona = precio_actual >= zona["zona_inferior"] * 0.997
        if not (en_zona or cerca_zona):
            continue

        bos_ok     = bos_choch and bos_choch["direccion"] == "bajista"
        barrido_ok = barrido   and barrido["direccion"]   == "bajista"
        confluencia = 1 + punto_sesion + punto_inst + (1 if bos_ok else 0) + (1 if barrido_ok else 0)

        entrada         = zona["zona_inferior"]
        sl_zona_dolares = (zona["zona_superior"] + (zona["zona_superior"] - zona["zona_inferior"]) * 0.5) - entrada
        niveles         = calcular_sl_tp(entrada, "bajista", sl_zona_dolares)

        if confluencia >= 4:   calidad = "🎯 SNIPER"
        elif confluencia == 3: calidad = "⭐ BUENA"
        else:                  calidad = "⚠️ DÉBIL"

        senales.append({
            "accion":       "🔴 VENTA",
            "calidad":      calidad,
            "confluencia":  confluencia,
            "estado":       "EN ZONA ✅" if en_zona else "CERCA ⚠️",
            "precio_actual": precio_actual,
            "entrada":      round(entrada, 2),
            "stop_loss":    niveles["stop_loss"],
            "take_profit":  niveles["take_profit"],
            "sl_pips":      niveles["sl_pips"],
            "tp_pips":      niveles["tp_pips"],
            "sl_ajustado":  niveles["ajustado"],
            "riesgo":       pips_a_dolares(niveles["sl_pips"]),
            "ganancia":     pips_a_dolares(niveles["tp_pips"]),
            "zona_origen":  zona["tipo"],
            "bos_choch":    bos_choch["descripcion"] if bos_ok     else "No confirmado",
            "barrido":      barrido["descripcion"]   if barrido_ok else "No detectado",
            "sesion":       sesion or "Fuera de sesión",
        })

    orden = {"🎯 SNIPER": 0, "⭐ BUENA": 1, "⚠️ DÉBIL": 2}
    senales.sort(key=lambda s: orden.get(s["calidad"], 3))
    return senales

# ─── FORMATO TELEGRAM ─────────────────────────────────────────────────────────

def formato_mensaje(temporalidad, senales, precio, bos_choch, barrido, sesion, obs, dzs, zos, izs):
    emoji_tf = "⚡" if temporalidad == "M15" else "📊"
    hora_col = hora_colombia().strftime("%H:%M")

    texto  = f"{emoji_tf} <b>XAU/USD — {temporalidad}</b>\n"
    texto += f"💰 Precio: <b>${precio:,.2f}</b>  |  🕐 {hora_col} COL\n"
    texto += f"━━━━━━━━━━━━━━━━━━━━━━\n"
    texto += f"{'🟢 Sesión: ' + sesion if sesion else '🔴 Fuera de sesión | ' + proxima_sesion()}\n"
    if bos_choch: texto += f"📐 {bos_choch['descripcion']}\n"
    if barrido:   texto += f"💧 {barrido['descripcion']}\n"
    texto += f"▣ OB:{len(obs)}  ◈ DZ:{len(dzs)}  ◇ ZO:{len(zos)}  ◆ IZ:{len(izs)}\n"
    texto += f"━━━━━━━━━━━━━━━━━━━━━━\n"

    if not senales:
        texto += f"\n⏳ <i>Sin señales activas en {temporalidad}</i>"
    else:
        mejores = [s for s in senales if s["calidad"] in ["🎯 SNIPER", "⭐ BUENA"]]
        debiles = [s for s in senales if s["calidad"] == "⚠️ DÉBIL"]

        if mejores:
            texto += f"\n🚨 <b>{len(mejores)} SEÑAL(ES) CALIFICADA(S)</b>\n"
            for i, s in enumerate(mejores, 1):
                ajuste = " (ajustado)" if s["sl_ajustado"] else ""
                texto += f"\n<b>#{i} {s['accion']}  {s['calidad']}</b>\n"
                texto += f"Estado: {s['estado']}\n"
                texto += f"🎯 Entrada:      <b>${s['entrada']:,.2f}</b>\n"
                texto += f"🛑 Stop Loss:    <b>${s['stop_loss']:,.2f}</b>  ({s['sl_pips']} pips{ajuste})\n"
                texto += f"💵 Take Profit:  <b>${s['take_profit']:,.2f}</b>  ({s['tp_pips']} pips)\n"
                texto += f"📐 Ratio:        1:2\n"
                texto += f"📉 Riesgo:       ${s['riesgo']:,.2f}\n"
                texto += f"📈 Ganancia:     ${s['ganancia']:,.2f}\n"
                texto += f"⚡ Confluencia:  {s['confluencia']}/5 puntos\n"
                texto += f"📌 Zona:         {s['zona_origen']}\n"
                texto += f"📐 Estructura:   {s['bos_choch']}\n"
                texto += f"💧 Liquidez:     {s['barrido']}\n"
                texto += f"🕐 Sesión:       {s['sesion']}\n"

        if debiles:
            texto += f"\n<i>⚠️ {len(debiles)} señal(es) débil(es) ignorada(s)</i>\n"

    texto += f"\n━━━━━━━━━━━━━━━━━━━━━━\n"
    texto += f"<i>⚠️ Practica en cuenta demo primero</i>"
    return texto

# ─── ANALIZAR ─────────────────────────────────────────────────────────────────

def analizar(temporalidad, intervalo, rango, senales_anteriores, sesion):
    print(f"\n  📊 Analizando {temporalidad}...")
    velas = obtener_velas(intervalo, rango)
    if len(velas) < 20:
        print(f"  ⚠️  Pocos datos en {temporalidad}")
        return senales_anteriores

    obs       = detectar_order_blocks(velas)
    dzs       = detectar_zonas_demanda(velas)
    zos       = detectar_zonas_oferta(velas)
    izs       = detectar_institucionales(velas)
    bos_choch = detectar_bos_choch(velas)
    barrido   = detectar_barrido(velas)
    precio    = velas[-1]["close"]
    senales   = calcular_senales(velas, obs, dzs, zos, izs, bos_choch, barrido, sesion)

    sniper = sum(1 for s in senales if s["calidad"] == "🎯 SNIPER")
    buenas = sum(1 for s in senales if s["calidad"] == "⭐ BUENA")
    print(f"  💰 {temporalidad} ${precio:,.2f} | Sniper:{sniper} Buenas:{buenas} | "
          f"BOS:{bos_choch['tipo'] if bos_choch else 'No'} | "
          f"Barrido:{'Sí' if barrido else 'No'} | Sesión:{sesion or 'No'}")

    entradas_nuevas = [s["entrada"] for s in senales if s["calidad"] in ["🎯 SNIPER", "⭐ BUENA"]]
    entradas_viejas = [s["entrada"] for s in senales_anteriores if s.get("calidad") in ["🎯 SNIPER", "⭐ BUENA"]]

    if entradas_nuevas and entradas_nuevas != entradas_viejas:
        enviar_telegram(formato_mensaje(temporalidad, senales, precio, bos_choch, barrido, sesion, obs, dzs, zos, izs))
    elif not entradas_nuevas and entradas_viejas:
        enviar_telegram(
            f"{'⚡' if temporalidad=='M15' else '📊'} <b>XAU/USD {temporalidad}</b>\n"
            f"💰 ${precio:,.2f}\n⏳ Señales anteriores ya no activas."
        )
    return senales

# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    print("\n" + "="*58)
    print("   🥇 BOT XAU/USD — ENTRADAS SNIPER")
    print(f"   SL: {SL_MINIMO_PIPS}-{SL_MAXIMO_PIPS} pips | TP: ratio 1:2 siempre")
    print("   M15 cada 15min | H1 cada hora")
    print("   Sesiones Colombia: Londres 3-7am | NY 9-2pm")
    print("="*58)

    enviar_telegram(
        "🥇 <b>BOT XAU/USD SNIPER INICIADO</b>\n\n"
        "✅ BOS / CHoCH activado\n"
        "✅ Barrido de liquidez activado\n"
        f"✅ SL: {SL_MINIMO_PIPS}-{SL_MAXIMO_PIPS} pips | TP: ratio 1:2\n"
        "✅ Filtro de sesión Colombia\n\n"
        "🇨🇴 Sesiones activas:\n"
        "🇬🇧 Londres:    3:00am - 7:00am\n"
        "🇺🇸 Nueva York: 9:00am - 2:00pm\n\n"
        "🎯 Solo recibirás señales SNIPER y BUENAS"
    )

    senales_m15 = []
    senales_h1  = []
    ciclo       = 0

    while True:
        hora_col = hora_colombia().strftime("%H:%M")
        sesion   = sesion_activa()
        print(f"\n{'='*58}")
        print(f"  🔄 Ciclo #{ciclo+1} | {hora_col} COL | Sesión: {sesion or 'Fuera'}")
        print(f"{'='*58}")

        senales_m15 = analizar("M15", "15m", "3d", senales_m15, sesion)
        if ciclo % 4 == 0:
            senales_h1 = analizar("H1", "1h", "7d", senales_h1, sesion)

        ciclo += 1
        print(f"\n  ⏰ Próximo análisis en 15 minutos...")
        time.sleep(900)

if __name__ == "__main__":
    main()
