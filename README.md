# AERO-LITORAL 26: ADS-B Deep Decoder Testbench 📡✈️

![GNU Radio](https://img.shields.io/badge/GNU%20Radio-3.10.12-blue.svg)
![Python](https://img.shields.io/badge/Python-3.x-blue?logo=python&logoColor=white)
![pyModeS](https://img.shields.io/badge/pyModeS-v3-green.svg)
![License](https://img.shields.io/badge/License-MIT-yellow.svg)

Plataforma terrestre de recepción, correlación y decodificación profunda de señales **ADS-B / Mode-S (1090 MHz)** desarrollada para el ecosistema del proyecto espacial **CubeSat 1U (AERO-LITORAL 26)**.

Este proyecto reemplaza herramientas de caja negra (como `dump1090`) por una arquitectura modular de radio definida por software (SDR) 100% auditable, basada en GNU Radio y ZeroMQ, con un decodificador terminal escrito en Python puro.

---

## 🏛️ Arquitectura del Sistema

El sistema se divide en dos grandes bloques desacoplados que se comunican de forma asíncrona mediante un socket TCP ZeroMQ (PUB/SUB):

1. **Receptor SDR (`adsb_rx_completo.py`)**
   Adquisición de RF mediante hardware RTL-SDR y procesamiento de señal (DSP) en GNU Radio. 
   `Antena ➔ SoapySDR ➔ Módulo al Cuadrado (Potencia) ➔ Framer Parcheado ➔ Demodulador PPM ➔ ZeroMQ PUB`

2. **Decodificador Profundo (`adsb_decoder.py`)**
   Consumidor ZMQ que procesa y desempaqueta los Vectores PMT usando la librería `pyModeS`, obteniendo Altitud, Velocidad, Coordenadas CPR Globales y estatus de las aeronaves en tiempo real.

---

## 🚀 Características y Optimizaciones Únicas

Este repositorio contiene parches y mejoras críticas implementadas sobre la librería estándar `gr-adsb` de GNU Radio en Windows:

* **Corrección del Bug PMT/NumPy:** Se incluye un `custom_framer.py` que soluciona un crasheo fatal de la librería original `gnuradio.adsb` en el que las envolturas SWIG fallaban al intentar convertir valores de Relación Señal/Ruido (SNR) de `numpy.float32` a etiquetas PMT.
* **Mitigación de SDR Overruns (`OsO`):** Aumento masivo de la tolerancia del buffer de memoria hardware de SoapySDR (hasta `1048576` muestras) para absorber latencias del *Garbage Collector* de Python, impidiendo la pérdida de tramas de radio a 2 MSPS.
* **Módulo `rf_monitor`:** Un osciloscopio y recolector estadístico en memoria inyectado nativamente que perfila ráfagas y calcula los percentiles (P90-P100) del espectro de ruido sin sobrecargar la CPU, logrando una sintonización quirúrgica del *Threshold* del framer.
* **Filtro Anti-Fantasmas (Confidence Filter):** Algoritmo lógico en la capa decodificadora que discrimina direcciones ICAO reales de alucinaciones matemáticas (falsos positivos provocados por ruido en los formatos AP Mode-S), requiriendo redundancia de paquetes estocásticos para validación en pantalla.
* **Auto-Arranque Sincronizado:** Uso de directivas de máxima prioridad (`/HIGH`) a nivel de sistema operativo para el proceso DSP y *delays* preventivos para evitar la pérdida de los primeros paquetes ZMQ.

---

## ⚙️ Requisitos y Dependencias

* Sistema Operativo: Windows (Probado en Windows 10/11)
* Hardware: Receptor RTL-SDR (ej. R820T2) + Antena de 1090 MHz.
* Entorno Base: **Radioconda** (incluye GNU Radio 3.10.x).
* Librerías Python: `numpy`, `pyzmq`, `pyModeS`, `psutil`.

---

## 💻 Uso e Instalación

1. Clona este repositorio en tu equipo.
2. Asegúrate de tener tu hardware RTL-SDR conectado y los drivers USB (Zadig) instalados correctamente.
3. Ejecuta el archivo principal por lotes:
   ```cmd
   iniciar_radar.bat
   ```
4. El script iniciará el entorno Radioconda, asignará prioridad máxima a la decodificación de radio, levantará el servidor ZMQ y finalmente lanzará la terminal del radar en pantalla.

## 🏆 Hitos del Proyecto

* **Primera Intercepción Exitosa (17/06/2026):** El sistema logró purificar el ruido ambiental y capturó con total precisión la telemetría del vuelo comercial **LAN542** (LATAM Airlines) a 36,000 pies de altitud y 410 nudos de velocidad sobrevolando las cercanías de Paraná (Entre Ríos), confirmando la viabilidad técnica de la cadena de radio de bloque a bloque, desde RTL-SDR hasta la decodificación CPR final.

---

## 👨‍💻 Autor y Afiliación institucional

**Moreira Gerónimo Facundo**  
Universidad Tecnológica Nacional, Facultad Regional Paraná (UTN-FRP)  
*Proyecto AERO-LITORAL 26*

---
*Hecho con dedicación para el avance de la tecnología satelital y el monitoreo del espacio aéreo abierto.*
