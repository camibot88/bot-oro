"""
Bot de Oro (XAU/USD) - Con alertas automáticas a Telegram
Detecta: Order Blocks, Zonas de Demanda, Zonas Institucionales
Envía señales de COMPRA y VENTA con Entrada, Stop Loss y Take Profit
"""

import requests
import time
from datetime import datetime

# ─── TU CONFIGURACIÓN DE TELEGRAM ────────────────────────────────────────────

TELEGRAM_TOKEN  = "8601021313:AAFPKqFegDStA2CaTTHYHInCUERkQR7QgQM"
TELEGRAM_CHAT_ID = "926481853"

# ─── ENVIAR MENSAJE A TELEGRAM ────────────────────────────────────────────────

def enviar_telegram(mensaje):
    """Envía un mensaje a tu Telegram"""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    datos = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": mensaje,
        "parse_mode": "HTML"
    }
    try:
        respuesta = requests.post(url, data=datos, timeout=10)
        if respuesta.status_code == 200:
            print("  ✅ Mensaje enviado a Telegram")
        else:
            print(f"  ⚠️  Error Telegram: {respuesta.text}")
    except Exception as e:
        print(f"  ⚠️  No se pudo enviar a Telegram: {e}")

def probar_telegram():
    """Prueba que Telegram funciona al iniciar el bot"""
    mensaje = (
        "🥇 <b>BOT XAU/USD INICIADO</b>\n\n"
        "✅ Conexión exitosa\n"
        "📊 Monitoreando el Oro cada 5 minutos\n"
        "🔔 Te avisaré cuando haya señales de COMPRA o VENTA"
    )
    enviar_telegram(mensaje)

# ─── OBTENER DATOS DEL ORO ────────────────────────────────────────────────────

def obtener_velas():
    url = "https://query1.finance.yahoo.com/v8/finance/chart/GC=F"
    parametros = {"interval": "1h", "range": "7d"}
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        respuesta = requests.get(url, params=parametros, headers=headers, timeout=10)
        datos = respuesta.json()
        chart = datos["chart"]["result"][0]
        tiempos = chart["timestamp"]
        precios = chart["indicators"]["quote"][0]
        velas = []
        for i in range(len(tiempos)):
            try:
                vela = {
                    "tiempo": datetime.fromtimestamp(tiempos[i]).strftime("%Y-%m-%d %H:%M"),
                    "open":   round(precios["open"][i], 2),
                    "high":   round(precios["high"][i], 2),
                    "low":    round(precios["low"][i], 2),
                    "close":  round(precios["close"][i], 2),
                    "volume": precios["volume"][i] or 0
                }
                if None not in vela.values():
                    velas.append(vela)
            except:
                continue
        return velas
    except Exception as e:
        print(f"  Error al obtener datos: {e}")
        return []

# ─── DETECTAR ZONAS ───────────────────────────────────────────────────────────

def detectar_order_blocks(velas):
    resultados = []
    lookback = 5
    for i in range(lookback, len(velas) - 3):
        vela = velas[i]
        cuerpo = abs(vela["close"] - vela["open"])
        promedio = sum(abs(v["close"] - v["open"]) for v in velas[i-lookback:i]) / lookback
        if promedio == 0 or cuerpo < promedio * 1.2:
            continue
        es_alcista = vela["close"] > vela["open"]
        siguientes = velas[i+1:i+4]
        movimiento_fuerte = any(
            (v["close"] > vela["high"] if es_alcista else v["close"] < vela["low"])
            for v in siguientes
        )
        if movimiento_fuerte:
            resultados.append({
                "tipo": "ORDER BLOCK",
                "direccion": "alcista" if es_alcista else "bajista",
                "zona_superior": round(max(vela["open"], vela["close"]), 2),
                "zona_inferior": round(min(vela["open"], vela["close"]), 2),
                "fuerza": round(cuerpo / promedio, 1),
                "tiempo": vela["tiempo"]
            })
    return resultados[-4:]

def detectar_zonas_demanda(velas):
    resultados = []
    lookback = 8
    for i in range(lookback, len(velas) - 4):
        vela = velas[i]
        anteriores = velas[i-lookback:i]
        minimo_local = min(v["low"] for v in anteriores)
        maximo_local = max(v["high"] for v in anteriores)
        rango = maximo_local - minimo_local
        if rango == 0:
            continue
        if vela["low"] <= minimo_local * 1.005 and vela["close"] > vela["open"]:
            cuerpo = abs(vela["close"] - vela["open"])
            rebote = any(
                v["close"] > vela["high"] and abs(v["close"] - v["open"]) > cuerpo * 0.8
                for v in velas[i+1:i+5]
            )
            if rebote:
                margen = rango * 0.008
                resultados.append({
                    "tipo": "ZONA DE DEMANDA",
                    "direccion": "alcista",
                    "zona_superior": round(vela["low"] + margen, 2),
                    "zona_inferior": round(vela["low"] - margen * 0.3, 2),
                    "fuerza": round((vela["high"] - vela["low"]) / rango, 2),
                    "tiempo": vela["tiempo"]
                })
    return resultados[-3:]

def detectar_zonas_oferta(velas):
    resultados = []
    lookback = 8
    for i in range(lookback, len(velas) - 4):
        vela = velas[i]
        anteriores = velas[i-lookback:i]
        maximo_local = max(v["high"] for v in anteriores)
        minimo_local = min(v["low"] for v in anteriores)
        rango = maximo_local - minimo_local
        if rango == 0:
            continue
        if vela["high"] >= maximo_local * 0.995 and vela["close"] < vela["open"]:
            cuerpo = abs(vela["close"] - vela["open"])
            caida = any(
                v["close"] < vela["low"] and abs(v["close"] - v["open"]) > cuerpo * 0.8
                for v in velas[i+1:i+5]
            )
            if caida:
                margen = rango * 0.008
                resultados.append({
                    "tipo": "ZONA DE OFERTA",
                    "direccion": "bajista",
                    "zona_superior": round(vela["high"] + margen * 0.3, 2),
                    "zona_inferior": round(vela["high"] - margen, 2),
                    "fuerza": round((vela["high"] - vela["low"]) / rango, 2),
                    "tiempo": vela["tiempo"]
                })
    return resultados[-3:]

def detectar_zonas_institucionales(velas):
    resultados = []
    maximo = max(v["high"] for v in velas)
    minimo = min(v["low"] for v in velas)
    rango = maximo - minimo
    if rango == 0:
        return resultados
    for fib in [0.236, 0.382, 0.5, 0.618, 0.786]:
        precio_fib = minimo + rango * fib
        precio_redondo = round(precio_fib / 50) * 50
        if abs(precio_fib - precio_redondo) / rango < 0.03:
            toques = sum(
                1 for v in velas
                if abs(v["low"] - precio_redondo) < rango * 0.015
                or abs(v["high"] - precio_redondo) < rango * 0.015
            )
            if toques >= 2:
                resultados.append({
                    "tipo": "ZONA INSTITUCIONAL",
                    "precio": precio_redondo,
                    "zona_superior": round(precio_redondo + rango * 0.006, 2),
                    "zona_inferior": round(precio_redondo - rango * 0.006, 2),
                    "fibonacci": f"{fib*100:.1f}%",
                    "toques": toques
                })
    return resultados[-3:]

# ─── CALCULAR SEÑALES ─────────────────────────────────────────────────────────

def calcular_senales(velas, obs, dzs, zos, izs):
    if not velas:
        return []
    precio_actual = velas[-1]["close"]
    senales = []
    zonas_inst_cerca = [
        z for z in izs
        if z["zona_inferior"] <= precio_actual <= z["zona_superior"]
    ]

    # COMPRAS
    for zona in [z for z in obs if z["direccion"] == "alcista"] + dzs:
        en_zona    = zona["zona_inferior"] <= precio_actual <= zona["zona_superior"]
        cerca_zona = precio_actual <= zona["zona_superior"] * 1.003
        if en_zona or cerca_zona:
            entrada     = zona["zona_superior"]
            stop_loss   = round(zona["zona_inferior"] - (zona["zona_superior"] - zona["zona_inferior"]) * 0.5, 2)
            riesgo      = entrada - stop_loss
            take_profit = round(entrada + riesgo * 2, 2)
            senales.append({
                "accion":        "🟢 COMPRA",
                "estado":        "EN ZONA ✅" if en_zona else "CERCA ⚠️",
                "precio_actual": precio_actual,
                "entrada":       round(entrada, 2),
                "stop_loss":     stop_loss,
                "take_profit":   take_profit,
                "riesgo":        round(riesgo, 2),
                "ganancia":      round(take_profit - entrada, 2),
                "confluencia":   1 + len(zonas_inst_cerca),
                "zona_origen":   zona["tipo"],
                "tiempo_zona":   zona["tiempo"]
            })

    # VENTAS
    for zona in [z for z in obs if z["direccion"] == "bajista"] + zos:
        en_zona    = zona["zona_inferior"] <= precio_actual <= zona["zona_superior"]
        cerca_zona = precio_actual >= zona["zona_inferior"] * 0.997
        if en_zona or cerca_zona:
            entrada     = zona["zona_inferior"]
            stop_loss   = round(zona["zona_superior"] + (zona["zona_superior"] - zona["zona_inferior"]) * 0.5, 2)
            riesgo      = stop_loss - entrada
            take_profit = round(entrada - riesgo * 2, 2)
            senales.append({
                "accion":        "🔴 VENTA",
                "estado":        "EN ZONA ✅" if en_zona else "CERCA ⚠️",
                "precio_actual": precio_actual,
                "entrada":       round(entrada, 2),
                "stop_loss":     stop_loss,
                "take_profit":   take_profit,
                "riesgo":        round(riesgo, 2),
                "ganancia":      round(abs(take_profit - entrada), 2),
                "confluencia":   1 + len(zonas_inst_cerca),
                "zona_origen":   zona["tipo"],
                "tiempo_zona":   zona["tiempo"]
            })

    return senales

# ─── FORMATEAR MENSAJE TELEGRAM ───────────────────────────────────────────────

def formato_telegram(senales, velas):
    precio = velas[-1]["close"] if velas else 0
    hora   = datetime.now().strftime("%H:%M:%S")

    if not senales:
        return (
            f"🥇 <b>XAU/USD — Sin señales</b>\n"
            f"💰 Precio: <b>${precio:,.2f}</b>\n"
            f"🕐 {hora}\n\n"
            f"⏳ El precio no está en ninguna zona importante ahora."
        )

    texto = f"🚨 <b>SEÑAL XAU/USD — {hora}</b>\n"
    texto += f"💰 Precio actual: <b>${precio:,.2f}</b>\n\n"

    for i, s in enumerate(senales, 1):
        texto += f"━━━━━━━━━━━━━━━━━━━━\n"
        texto += f"<b>SEÑAL #{i}  {s['accion']}</b>\n"
        texto += f"Estado: {s['estado']}\n\n"
        texto += f"🎯 Entra en:         <b>${s['entrada']:,.2f}</b>\n"
        texto += f"🛑 Stop Loss:        <b>${s['stop_loss']:,.2f}</b>\n"
        texto += f"💵 Take Profit:      <b>${s['take_profit']:,.2f}</b>\n\n"
        texto += f"📉 Riesgo:           ${s['riesgo']:,.2f}\n"
        texto += f"📈 Ganancia posible: ${s['ganancia']:,.2f}\n"
        texto += f"⚡ Confluencia:      {s['confluencia']} zona(s)\n"
        texto += f"📌 Zona:             {s['zona_origen']}\n"

    texto += f"\n━━━━━━━━━━━━━━━━━━━━\n"
    texto += f"⚠️ <i>Practica en cuenta demo primero.</i>"
    return texto

# ─── MOSTRAR EN PANTALLA ──────────────────────────────────────────────────────

def mostrar_pantalla(velas, obs, dzs, zos, izs, senales):
    print("\n" + "="*58)
    print("        🥇 BOT XAU/USD — ANÁLISIS")
    print("="*58)
    if velas:
        print(f"\n  💰 PRECIO ACTUAL:    ${velas[-1]['close']:,.2f}")
        print(f"  🕐 Hora:             {datetime.now().strftime('%H:%M:%S')}")
        print(f"  📊 Velas analizadas: {len(velas)}")
    print(f"\n  ▣  Order Blocks:          {len(obs)}")
    print(f"  ◈  Zonas de Demanda:      {len(dzs)}")
    print(f"  ◇  Zonas de Oferta:       {len(zos)}")
    print(f"  ◆  Zonas Institucionales: {len(izs)}")
    print("\n" + "-"*58)
    if not senales:
        print("\n  ⏳ Sin señales activas. Monitoreando...")
    else:
        print(f"\n  🚨 {len(senales)} SEÑAL(ES) DETECTADA(S) — enviando a Telegram...\n")
        for i, s in enumerate(senales, 1):
            print(f"  SEÑAL #{i}  {s['accion']}  {s['estado']}")
            print(f"  🎯 Entrada:    ${s['entrada']:,.2f}")
            print(f"  🛑 Stop Loss:  ${s['stop_loss']:,.2f}")
            print(f"  💵 Take Profit:${s['take_profit']:,.2f}")
            print()
    print("="*58)

# ─── INICIO ───────────────────────────────────────────────────────────────────

def main():
    print("\n" + "="*58)
    print("   🥇 BOT DE ORO (XAU/USD) CON TELEGRAM")
    print("   Señales automáticas cada 5 minutos")
    print("   Presiona Ctrl+C para detener")
    print("="*58)

    # Prueba Telegram al inicio
    print("\n  📱 Probando conexión con Telegram...")
    probar_telegram()

    senales_anteriores = []

    while True:
        print(f"\n  ⏳ Analizando... ({datetime.now().strftime('%H:%M:%S')})")

        velas = obtener_velas()

        if len(velas) < 20:
            print("  ⚠️  Pocos datos. Reintentando en 1 minuto...")
            time.sleep(60)
            continue

        obs     = detectar_order_blocks(velas)
        dzs     = detectar_zonas_demanda(velas)
        zos     = detectar_zonas_oferta(velas)
        izs     = detectar_zonas_institucionales(velas)
        senales = calcular_senales(velas, obs, dzs, zos, izs)

        mostrar_pantalla(velas, obs, dzs, zos, izs, senales)

        # Enviar a Telegram solo si hay señales nuevas
        entradas_nuevas = [s["entrada"] for s in senales]
        entradas_viejas = [s["entrada"] for s in senales_anteriores]

        if senales and entradas_nuevas != entradas_viejas:
            mensaje = formato_telegram(senales, velas)
            enviar_telegram(mensaje)
            senales_anteriores = senales
        elif not senales and senales_anteriores:
            # Avisar cuando las señales desaparecen
            enviar_telegram(
                f"🥇 <b>XAU/USD</b>\n"
                f"💰 Precio: ${velas[-1]['close']:,.2f}\n"
                f"⏳ Las señales anteriores ya no están activas.\n"
                f"Monitoreando..."
            )
            senales_anteriores = []

        print(f"\n  ⏰ Próxima actualización en 5 minutos...")
        time.sleep(300)

if __name__ == "__main__":
    main()
