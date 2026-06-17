# AERO-LITORAL 26 - Testbench Terrestre ADS-B
# Changelog (Registro de Cambios)

## [v2.1] - 2026-06-10

Versión enfocada en resolver el problema crítico de detección: el bloque `adsb.demod` de GNU Radio no detectaba tramas a pesar de que `dump1090` sí lo hacía con el mismo hardware. Se implementó una arquitectura dual y se corrigieron tres errores fundamentales en la cadena de señal de RF.

### 1. Arquitectura Dual (dump1090 + GNU Radio)
* **Modo dump1090 (RECOMENDADO):** El decodificador ahora puede conectarse directamente al puerto TCP 30002 de `dump1090`, leyendo mensajes hexadecimales crudos en formato AVR. `dump1090` tiene un demodulador de señal muy superior al bloque `adsb.demod` de GNU Radio (soporta corrección de fase, corrección de errores de bits, y detección adaptativa de umbral).
* **Modo GNU Radio (Experimental):** Se conserva la conexión ZMQ original como opción secundaria, accesible con el flag `--zmq`.
* **Selección por línea de comandos:** `python adsb_decoder.py` (dump1090) o `python adsb_decoder.py --zmq` (GNU Radio). También acepta `--host` y `--port` para conexiones remotas.
* **Reconexión automática:** En modo dump1090, si la conexión se pierde o dump1090 no está corriendo, el decodificador reintenta automáticamente cada 5 segundos.

### 2. Correcciones Críticas en la Cadena RF de GNU Radio
* **Complex to Mag (NO Mag Squared):** El bloque `adsb.demod` espera internamente la magnitud lineal de la señal (√(I²+Q²)), no la potencia (I²+Q²). Usar Mag Squared distorsionaba la relación de amplitudes y destruía la detección de preámbulos.
* **AGC Desactivado:** El AGC del RTL-SDR reacciona demasiado lento para los pulsos ADS-B de microsegundos. Se revirtió a ganancia manual fija a 49.6 dB.
* **Multiply Const a 1:** Con la magnitud lineal y la ganancia correcta, no se necesita amplificación artificial adicional.

### 3. Lanzador Mejorado
* **Menú interactivo en `iniciar_radar.bat`:** Al ejecutar el lanzador, ahora presenta un menú para elegir entre Modo dump1090 (opción 1, recomendada) o Modo GNU Radio (opción 2, experimental).

---
## [v2.0] - 2026-06-10

Esta versión es una reescritura masiva del decodificador (adsb_decoder.py) orientada a transformarlo en un motor de decodificación de grado profesional para uso extendido en el Testbench del CubeSat 1U.

### 1. El Motor Principal (Core)
* **Actualización a la arquitectura v3.x:** El código original intentaba usar funciones viejas (`pms.df()`, `pms.icao()`) que ya fueron eliminadas de la librería moderna, por lo que el script fallaba. Ahora usa la API de última generación (`pyModeS.decode()`).
* **Validación de Errores (Paridad CRC-24):** Implementamos validación CRC rigurosa. Si un mensaje llega corrupto o distorsionado desde la antena por culpa del ruido de RF, el decodificador lo descarta silenciosamente en lugar de crashear o mostrar datos falsos.

### 2. Procesamiento de Vuelo y Posición
* **Cálculo de Posición Global (CPR):** El código viejo solo extraía fragmentos crudos de la posición. La nueva versión implementa la clase `CPRState` que captura tramas "pares" e "impares", las empareja si llegaron en una ventana de 10 segundos, y ejecuta la matemática requerida para obtener Latitud y Longitud exacta.
* **Soporte de Formatos Extremo:** Se amplió el soporte más allá del básico DF17. Ahora procesa mensajes de casi todo el espectro comercial: DF0, DF4, DF5, DF11, DF16, DF17, DF18, DF20 y DF21. Intercepta Altitud, Velocidad (TAS/GS), Rumbo, Códigos Squawk de transpondedor y alertas de emergencia.
* **Manejo de estados de aeronave (Tracking):** Cada avión cuenta ahora con su propia memoria (`AircraftState`). El programa fusiona datos de distintas tramas para construir perfiles en vivo de las aeronaves a medida que se mueven.

### 3. Estabilidad y Uso Prolongado (Testbench)
* **Limpiador de Memoria Automático (Garbage Collector):** Para prevenir el agotamiento de memoria RAM en corridas de varios días, se agregó un recolector que purga automáticamente a los aviones que llevan más de 5 minutos sin emitir señal.
* **Reparación de Compatibilidad Windows:** En `adsb_rx_completo.py` se mitigó un bug de GNU Radio relacionado a `signal.SIGTERM` que provocaba cierres forzosos abruptos del script de radio nativamente en Windows.

### 4. Interfaz y Visualización
* **Tabla de Radar en Tiempo Real:** El sistema interrumpe el flujo cada 30 segundos para imprimir un resumen estadístico y una tabla estilo "radar", resumiendo aviones rastreados, velocidades, altitudes y posiciones actualizadas.
* **Desglose Bit a Bit (Field Mapping):** Al detectar un mensaje, se imprime la tira de código binario completa (112 bits) y se especifica la asignación de cada subgrupo de bits a su variable técnica correspondiente. Ideal para propósitos educativos y estudio profundo del protocolo en el marco del CubeSat.
* **Script de Pruebas Unitarias:** Se agregó `test_decoder.py` para poder someter a pruebas de esfuerzo la matemática del protocolo utilizando mensajes conocidos, sin necesidad de emplear hardware RTL-SDR real.

### 5. Automatización y Radiofrecuencia
* **Ejecución Headless (Sin GUI):** Se eliminó la dependencia gráfica de la ventana en blanco de PyQt5 generada por GNU Radio. El receptor ahora se ejecuta de forma 100% silenciosa en segundo plano por consola.
* **Control Automático de Ganancia (AGC):** Se activó el AGC en el RTL-SDR para evitar la saturación (clipping) cuando las aeronaves pasan directamente por encima de la antena, y se reajustó la constante matemática del demodulador a `50` para compensar la subida del piso de ruido.
* **Automatizador Batch:** Se creó el script `iniciar_radar.bat` que inyecta dinámicamente las variables de entorno de Radioconda, corrige rutas de Administrador en Windows, lanza las dos consolas requeridas y gestiona los tiempos de espera (10 segundos) de ZeroMQ automáticamente.

---
## [v1.0] - Versión Inicial (Heredada)
* Prueba de concepto inicial de captura mediante bloque ADS-B Demod en GNU Radio.
* Script básico de puente Python vía puerto ZMQ tcp://127.0.0.1:5555.
