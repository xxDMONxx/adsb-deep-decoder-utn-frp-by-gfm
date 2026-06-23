"""
LITORAL-RADAR-FRP - Simulador de Telemetría CubeSat
===================================================================
Este script simula el enlace de bajada (downlink) de un CubeSat enviando paquetes JSON a través 
de UDP (puerto 5556). Su objetivo principal es emular el comportamiento del segmento espacial 
para probar y validar la respuesta del Backend (adsb_decoder.py) sin necesidad de tener el hardware real.

Genera de manera aleatoria fluctuaciones en:
- El voltaje de batería (VBAT).
- Temperatura (TEMP) y parámetros de actitud (Pitch, Roll, Yaw).
- Emite un conjunto estático de tramas crudas ADS-B simuladas para evaluar la capacidad 
  de decodificación del backend y su integración en el Frontend Web.
"""
import socket
import json
import time
import random

UDP_IP = "127.0.0.1"
UDP_PORT = 5556

print(f"📡 Simulador de Telemetría CubeSat Iniciado")
print(f"Enviando paquetes a {UDP_IP}:{UDP_PORT}...")

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

# Mock data
icaos = ["E01234", "A3F21C", "C0FFEE"]
raw_frames = [
    "8D40621D58C382D690C8AC2863A7",
    "8D40621D994409940838175B1B85",
    "8D40621D58C386435CC412692AD6"
]

vbat = 4.1

while True:
    try:
        # Simulamos que la batería baja muy lento
        vbat -= 0.001
        if vbat < 3.2: vbat = 4.2
        
        # Generar telemetría
        payload = {
            "timestamp": time.time(),
            "icao": random.choice(icaos),
            "raw_frame": random.choice(raw_frames),
            "health": {
                "status": "NOMINAL",
                "vbat": round(vbat, 2),
                "temp": round(random.uniform(15.0, 25.0), 1)
            },
            "attitude": {
                "pitch": round(random.uniform(-5.0, 5.0), 1),
                "roll": round(random.uniform(-5.0, 5.0), 1),
                "yaw": round(random.uniform(0.0, 360.0), 1)
            }
        }
        
        # Enviar JSON por UDP
        msg = json.dumps(payload).encode('utf-8')
        sock.sendto(msg, (UDP_IP, UDP_PORT))
        
        print(f"[{time.strftime('%H:%M:%S')}] TM Enviada -> ICAO: {payload['icao']} | Vbat: {payload['health']['vbat']}V")
        
        # Enviar un paquete cada 1 o 2 segundos
        time.sleep(random.uniform(1.0, 2.0))
        
    except KeyboardInterrupt:
        print("\nSimulador detenido.")
        break
