#!/usr/bin/env python3
"""
AERO-LITORAL 26 - ADS-B / Mode-S Deep Decoder v2.0
Testbench terrestre para receptor CubeSat 1U

LITORAL-RADAR-FRP - Módulo de Decodificación ADS-B (Backend Central)
===================================================================
Este script actúa como el "cerebro" del sistema de radar. Fue diseñado para:
1. Recibir tramas hexadecimales en bruto (raw frames) provenientes del SDR (GNU Radio) vía ZMQ en el puerto 5555.
2. Recibir telemetría simulada (o real) de un CubeSat vía UDP en el puerto 5556.
3. Procesar y decodificar estas tramas utilizando la librería `pyModeS` (pyModeS v3 API).
4. Mantener un estado persistente de cada aeronave detectada (AircraftState), calculando
   su posición exacta mediante el algoritmo CPR (Compact Position Reporting).
5. Exponer esta información a la Interfaz de Usuario (TUI y Web) para su visualización.

Componentes principales de la Arquitectura:
- `CPRState`: Clase auxiliar que maneja la lógica compleja de pares par/impar para deducir latitud y longitud.
- `AircraftState`: Representa a un avión individual en el espacio aéreo, guardando su último reporte.
- `ADSBDecoder`: La clase orquestadora. Gestiona diccionarios de aeronaves y coordina toda la decodificación.
- `zmq_listener_loop` / `udp_cubesat_listener`: Hilos independientes que actúan como escuchas asíncronos.

Características Técnicas:
    - Validación CRC de todos los mensajes
    - Soporte DF0, DF4, DF5, DF11, DF16, DF17, DF18, DF20, DF21
    - Decodificación completa de TC 1-4, 5-8, 9-18, 19, 20-22, 28, 29, 31
    - CPR global (par+impar) usando pyModeS.position.airborne_position_pair
    - Tracking por aeronave con estado acumulado
    - Estadísticas en tiempo real y Expiración automática de estados

Dependencias:
    pip install pyzmq pyModeS>=3.0

Autor: AERO-LITORAL 26 Flight Software Team UTN-FRP. Moreira Geronimo
Versión: 2.0 — Reescritura completa con análisis profundo (pyModeS v3)
"""

try:
    import zmq
    import pmt
except ImportError:
    zmq = None  # Available only in Radioconda environment
    pmt = None
import pyModeS
from pyModeS.position import airborne_position_pair
from pyModeS._bits import extract_unsigned

import sys
import argparse
import socket
import threading
from typing import Dict, Any, Optional, Tuple
from time import time, strftime, localtime, sleep
from collections import defaultdict
import os
import msvcrt

try:
    from tui import TUIDashboard
except ImportError:
    pass

# =============================================================================
# Colores ANSI para salida de consola
# =============================================================================
if sys.platform == 'win32':
    try:
        os.system('')  # Habilita secuencias ANSI en Windows 10+
    except Exception:
        pass


class C:
    """Códigos de color ANSI para salida formateada."""
    RESET   = '\033[0m'
    BOLD    = '\033[1m'
    DIM     = '\033[2m'
    RED     = '\033[91m'
    GREEN   = '\033[92m'
    YELLOW  = '\033[93m'
    BLUE    = '\033[94m'
    MAGENTA = '\033[95m'
    CYAN    = '\033[96m'
    WHITE   = '\033[97m'
    GRAY    = '\033[90m'


# =============================================================================
# Tablas de referencia del protocolo ADS-B / Mode-S
# =============================================================================

AIRCRAFT_CATEGORY = {
    1: {0: 'No category info'},
    2: {
        0: 'No category info',
        1: 'Surface Emergency Vehicle',
        2: 'Surface Service Vehicle',
        3: 'Ground Obstruction',
        4: 'Cluster Obstacle', 5: 'Line Obstacle',
        6: 'Reserved', 7: 'Reserved'
    },
    3: {
        0: 'No category info',
        1: 'Glider / Sailplane',
        2: 'Lighter-than-Air',
        3: 'Parachutist / Skydiver',
        4: 'Ultralight / Hang-glider / Paraglider',
        5: 'Reserved',
        6: 'UAV (Unmanned Aerial Vehicle)',
        7: 'Space / Trans-atmospheric Vehicle'
    },
    4: {
        0: 'No category info',
        1: 'Light (< 15500 lbs)',
        2: 'Medium 1 (15500-75000 lbs)',
        3: 'Medium 2 (75000-300000 lbs)',
        4: 'High Vortex Large',
        5: 'Heavy (> 300000 lbs)',
        6: 'High Performance (>5g accel, >400kt)',
        7: 'Rotorcraft'
    }
}

DF_DESCRIPTION = {
    0:  'Vigilancia Aire-Aire Corta (ACAS)',
    4:  'Respuesta de Altitud de Vigilancia',
    5:  'Respuesta de Identidad de Vigilancia',
    11: 'Respuesta All-Call',
    16: 'Vigilancia Aire-Aire Larga (ACAS)',
    17: 'ADS-B Extended Squitter',
    18: 'Extended Squitter (TIS-B / ADS-R)',
    19: 'Military Extended Squitter',
    20: 'Respuesta de Altitud Comm-B',
    21: 'Respuesta de Identidad Comm-B',
    24: 'Mensaje de Longitud Extendida Comm-D',
}

TC_DESCRIPTION = {
    (1, 4):   'Identificación de Aeronave',
    (5, 8):   'Posición en Superficie',
    (9, 18):  'Posición en Vuelo (Alt Baro)',
    (19, 19): 'Velocidad Aérea',
    (20, 22): 'Posición en Vuelo (Alt GNSS)',
    (23, 27): 'Reservado',
    (28, 28): 'Estatus de Aeronave',
    (29, 29): 'Estado y Estatus del Blanco',
    (31, 31): 'Estado Operacional de Aeronave',
}

EMERGENCY_STATES = {
    0: 'No emergency',
    1: 'General emergency',
    2: 'Lifeguard / Medical',
    3: 'Minimum fuel',
    4: 'No communications',
    5: 'Unlawful interference (hijack)',
    6: 'Downed aircraft',
    7: 'Reserved',
}

CAPABILITY = {
    0: 'Level 1 (Surveillance Only)',
    1: 'Level 2 (DF0, 4, 5, 11)',
    2: 'Level 3 (DF0, 4, 5, 11, 20, 21)',
    3: 'Level 4 (DF0, 4, 5, 11, 20, 21, 24)',
    4: 'Level 2+3 (DF0, 4, 5, 11, 20, 21) (on ground)',
    5: 'Level 2+3 (DF0, 4, 5, 11, 20, 21) (airborne)',
    6: 'Level 2+3 (DF0, 4, 5, 11, 20, 21)',
    7: 'Level 7 (DR!=0 or FS=2,3,4,5)',
}

SURVEILLANCE_STATUS = {
    0: 'No condition',
    1: 'Permanent Alert (Emergency)',
    2: 'Temporary Alert (SPI)',
    3: 'SPI condition',
}

FLIGHT_STATUS = {
    0: 'No alert, no SPI, airborne',
    1: 'No alert, no SPI, on ground',
    2: 'Alert, no SPI, airborne',
    3: 'Alert, no SPI, on ground',
    4: 'Alert, SPI',
    5: 'No alert, SPI',
}


def get_tc_description(tc: int) -> str:
    """Retorna descripción del Type Code."""
    for (lo, hi), desc in TC_DESCRIPTION.items():
        if lo <= tc <= hi:
            return desc
    return 'Unknown'


# =============================================================================
# CPR State — Resolución de posición con pyModeS v3
# =============================================================================
class CPRState:
    """
    Estado CPR por aeronave. Almacena los valores cpr_lat/cpr_lon de los
    frames par (even) e impar (odd) para decodificar la posición global
    usando pyModeS.position.airborne_position_pair().

    La decodificación CPR global requiere UN frame par (cpr_format=0) y
    UN frame impar (cpr_format=1) del mismo ICAO, recibidos dentro de un
    margen de 10 segundos entre sí.
    """
    __slots__ = ('cpr_lat_even', 'cpr_lon_even', 't_even',
                 'cpr_lat_odd', 'cpr_lon_odd', 't_odd',
                 'last_lat', 'last_lon', 'last_pos_time')

    def __init__(self):
        self.cpr_lat_even: Optional[int] = None
        self.cpr_lon_even: Optional[int] = None
        self.t_even: float = 0.0
        self.cpr_lat_odd: Optional[int] = None
        self.cpr_lon_odd: Optional[int] = None
        self.t_odd: float = 0.0
        self.last_lat: Optional[float] = None
        self.last_lon: Optional[float] = None
        self.last_pos_time: float = 0.0

    def update(self, cpr_lat: int, cpr_lon: int, cpr_format: int,
               timestamp: float) -> Optional[Tuple[float, float]]:
        """
        Actualiza el estado CPR y retorna (lat, lon) si hay resolución
        global posible.

        Parameters:
            cpr_lat: Valor CPR latitude (17 bits, 0-131071) del decode()
            cpr_lon: Valor CPR longitude (17 bits, 0-131071) del decode()
            cpr_format: 0 = frame par (even), 1 = frame impar (odd)
            timestamp: Tiempo de recepción

        Returns:
            (latitud, longitud) en grados decimales o None
        """
        if cpr_format == 0:
            self.cpr_lat_even = cpr_lat
            self.cpr_lon_even = cpr_lon
            self.t_even = timestamp
        elif cpr_format == 1:
            self.cpr_lat_odd = cpr_lat
            self.cpr_lon_odd = cpr_lon
            self.t_odd = timestamp
        else:
            return None

        # --- Resolución global (requiere ambos frames) ---
        if (self.cpr_lat_even is not None and self.cpr_lat_odd is not None):
            delta = abs(self.t_even - self.t_odd)
            if delta < 10.0:
                try:
                    even_is_newer = self.t_even >= self.t_odd
                    pos = airborne_position_pair(
                        self.cpr_lat_even, self.cpr_lon_even,
                        self.cpr_lat_odd, self.cpr_lon_odd,
                        even_is_newer=even_is_newer
                    )
                    if pos is not None:
                        self.last_lat, self.last_lon = pos
                        self.last_pos_time = timestamp
                        return pos
                except Exception:
                    pass
            else:
                # Ventana expirada: descartar el frame más viejo
                if self.t_even < self.t_odd:
                    self.cpr_lat_even = None
                    self.cpr_lon_even = None
                else:
                    self.cpr_lat_odd = None
                    self.cpr_lon_odd = None

        return None


# =============================================================================
# Aircraft State — Información acumulada por ICAO
# =============================================================================
class AircraftState:
    """Estado completo de una aeronave rastreada."""

    def __init__(self, icao: str):
        self.icao: str = icao
        self.callsign: Optional[str] = None
        self.category: Optional[str] = None
        self.category_code: Optional[int] = None
        self.wake_vortex: Optional[str] = None
        self.altitude_baro: Optional[int] = None
        self.altitude_gnss: Optional[int] = None
        self.speed: Optional[float] = None
        self.heading: Optional[float] = None
        self.vertical_rate: Optional[int] = None
        self.speed_type: Optional[str] = None  # 'GS' / 'TAS' / 'IAS'
        self.vr_source: Optional[str] = None   # 'BARO' / 'GNSS'
        self.latitude: Optional[float] = None
        self.longitude: Optional[float] = None
        self.squawk: Optional[str] = None
        self.emergency: Optional[int] = None
        self.emergency_text: Optional[str] = None
        self.on_ground: Optional[bool] = None
        self.capability: Optional[int] = None
        self.flight_status: Optional[int] = None
        self.flight_status_text: Optional[str] = None
        # Integrity / Accuracy
        self.nic_b: Optional[int] = None
        self.nuc_p: Optional[int] = None
        self.nac_p: Optional[int] = None
        self.nac_v: Optional[int] = None
        self.sil: Optional[int] = None
        self.version: Optional[int] = None
        # Surveillance
        self.surveillance_status: Optional[int] = None
        # Timestamps
        self.first_seen: float = time()
        self.last_seen: float = time()
        self.msg_count: int = 0
        # CPR state
        self.cpr: CPRState = CPRState()

    def age(self) -> float:
        """Segundos desde el último mensaje."""
        return time() - self.last_seen


# =============================================================================
# ADS-B / Mode-S Deep Decoder (pyModeS v3)
# =============================================================================
class ADSBDecoder:
    """
    Decodificador ADS-B/Mode-S completo con análisis profundo de tramas.
    Usa pyModeS v3 API: pyModeS.decode(msg) + manual CPR pair tracking.
    """

    def __init__(self):
        self.aircraft: Dict[str, AircraftState] = {}
        self.cubesat_aircraft: Dict[str, AircraftState] = {}
        self.cubesat_health: dict = {}
        self.stats = {
            'total_received': 0,
            'crc_ok': 0,
            'crc_fail': 0,
            'decode_error': 0,
            'df_counts': defaultdict(int),
            'tc_counts': defaultdict(int),
            'positions_decoded': 0,
            'start_time': time(),
        }
        self._last_cleanup: float = time()

    def _get_aircraft(self, icao: str) -> AircraftState:
        """Obtiene o crea el estado de una aeronave."""
        if icao not in self.aircraft:
            self.aircraft[icao] = AircraftState(icao)
        ac = self.aircraft[icao]
        ac.last_seen = time()
        ac.msg_count += 1
        return ac

    def _cleanup_expired(self, max_memory: int = 500):
        """Mantiene el historial persistente pero limita la cantidad máxima para evitar fuga de memoria."""
        now = time()
        if now - self._last_cleanup < 60.0:
            return
        self._last_cleanup = now
        
        # Eliminar las aeronaves más antiguas SOLO si superamos el límite histórico
        if len(self.aircraft) > max_memory:
            # Ordenar por último avistamiento (las más viejas primero)
            sorted_acs = sorted(self.aircraft.items(), key=lambda x: x[1].last_seen)
            to_delete = len(self.aircraft) - max_memory
            for i in range(to_delete):
                del self.aircraft[sorted_acs[i][0]]

    def process(self, hex_msg: str) -> Optional[Dict[str, Any]]:
        """
        Procesa un mensaje ADS-B/Mode-S en formato hexadecimal.

        Parameters:
            hex_msg: String hexadecimal (14 chars para 56-bit, 28 chars para 112-bit)

        Returns:
            Dict con todos los campos decodificados, o None si es inválido
        """
        self.stats['total_received'] += 1
        self._cleanup_expired()

        # --- Validación de formato ---
        if not isinstance(hex_msg, str):
            return None

        hex_msg = hex_msg.strip().upper()

        if len(hex_msg) not in (14, 28):
            return None

        try:
            int(hex_msg, 16)
        except ValueError:
            return None

        # --- Decodificar con pyModeS v3 ---
        try:
            decoded = pyModeS.decode(hex_msg)
        except (pyModeS.InvalidHexError, pyModeS.InvalidLengthError):
            return None
        except pyModeS.UnknownDFError:
            return None
        except Exception:
            self.stats['decode_error'] += 1
            return None

        # --- Validar CRC ---
        crc_valid = decoded.get('crc_valid', True)
        if not crc_valid:
            self.stats['crc_fail'] += 1
            return None

        self.stats['crc_ok'] += 1

        # --- Extraer campos base ---
        df = decoded.get('df')
        icao = decoded.get('icao')

        if df is None or icao is None:
            return None

        self.stats['df_counts'][df] += 1

        now = time()
        timestamp_str = strftime('%H:%M:%S', localtime(now))

        tc = decoded.get('typecode')
        if tc is not None:
            self.stats['tc_counts'][tc] += 1

        # --- Obtener o crear estado de aeronave ---
        ac = self._get_aircraft(icao)

        # --- Construir resultado unificado ---
        result = {
            # Raw data
            'raw_hex': hex_msg,
            'raw_binary': bin(int(hex_msg, 16))[2:].zfill(len(hex_msg) * 4),
            'msg_length_bits': len(hex_msg) * 4,
            # Message identification
            'df': df,
            'df_description': DF_DESCRIPTION.get(df, f'Unknown DF{df}'),
            'icao': icao,
            'crc_valid': crc_valid,
            'timestamp': now,
            'timestamp_str': timestamp_str,
            'tc': tc,
            'tc_description': get_tc_description(tc) if tc else None,
            'bds': decoded.get('bds'),
            # Capability / Status
            'capability': None,
            'capability_text': None,
            'flight_status': decoded.get('flight_status'),
            'flight_status_text': decoded.get('flight_status_text'),
            # Identification
            'callsign': None,
            'category': None,
            'category_code': None,
            'wake_vortex': None,
            # Position
            'altitude_baro': None,
            'altitude_gnss': None,
            'latitude': None,
            'longitude': None,
            # Velocity
            'speed': None,
            'heading': None,
            'vertical_rate': None,
            'speed_type': None,
            'vr_source': None,
            'airspeed': None,
            'airspeed_type': None,
            'geo_minus_baro': None,
            # Squawk / Emergency
            'squawk': decoded.get('squawk'),
            'emergency': None,
            'emergency_text': None,
            # Surveillance / Integrity
            'surveillance_status': None,
            'surveillance_text': None,
            'nic_b': None,
            'nuc_p': None,
            'nac_p': None,
            'nac_v': decoded.get('nac_v'),
            'sil': None,
            'version': None,
            # CPR
            'cpr_format': decoded.get('cpr_format'),
            'cpr_format_text': None,
            'cpr_lat': decoded.get('cpr_lat'),
            'cpr_lon': decoded.get('cpr_lon'),
            # On ground
            'on_ground': None,
            # Deep analysis
            'field_map': [],
            # Additional from decode
            'downlink_request': decoded.get('downlink_request'),
            'utility_message': decoded.get('utility_message'),
            'subtype': decoded.get('subtype'),
        }

        # --- Populate fields from decoded dict ---

        # Capability (DF17/18)
        if df in (17, 18):
            try:
                msg_int = int(hex_msg, 16)
                ca = extract_unsigned(msg_int, 5, 3, len(hex_msg) * 4)
                result['capability'] = ca
                result['capability_text'] = CAPABILITY.get(ca, f'Unknown ({ca})')
                ac.capability = ca
            except Exception:
                pass

        # Flight status
        if result['flight_status'] is not None:
            ac.flight_status = result['flight_status']
            ac.flight_status_text = result.get('flight_status_text')
            if result['flight_status'] in (1, 3):
                result['on_ground'] = True
                ac.on_ground = True
            elif result['flight_status'] in (0, 2):
                result['on_ground'] = False
                ac.on_ground = False

        # Squawk
        if result['squawk']:
            ac.squawk = result['squawk']

        # CPR format text
        if result['cpr_format'] is not None:
            result['cpr_format_text'] = (
                'Even (0)' if result['cpr_format'] == 0 else 'Odd (1)'
            )

        # === Process by DF/TC ===

        # --- Altitude (DF4, DF20, or BDS 0,5 / 0,6) ---
        alt = decoded.get('altitude')
        if alt is not None:
            bds = decoded.get('bds', '')
            if bds == '0,5' and tc is not None and 20 <= tc <= 22:
                result['altitude_gnss'] = alt
                ac.altitude_gnss = alt
            else:
                result['altitude_baro'] = alt
                ac.altitude_baro = alt

        # --- Callsign (BDS 0,8) ---
        cs = decoded.get('callsign')
        if cs:
            cs = cs.strip('_').strip()
            if cs:
                result['callsign'] = cs
                ac.callsign = cs

        # --- Category (BDS 0,8) ---
        cat = decoded.get('category')
        if cat is not None:
            result['category_code'] = cat
            ac.category_code = cat
            if tc is not None and tc in AIRCRAFT_CATEGORY:
                cat_map = AIRCRAFT_CATEGORY[tc]
                result['category'] = cat_map.get(cat, f'Category {cat}')
            else:
                result['category'] = f'Category {cat}'
            ac.category = result['category']

        wv = decoded.get('wake_vortex')
        if wv:
            result['wake_vortex'] = wv
            ac.wake_vortex = wv

        # --- Surveillance Status (BDS 0,5) ---
        ss = decoded.get('surveillance_status')
        if ss is not None:
            result['surveillance_status'] = ss
            result['surveillance_text'] = SURVEILLANCE_STATUS.get(ss, f'Unknown ({ss})')
            ac.surveillance_status = ss

        # --- NIC / NUC / NAC ---
        nic_b = decoded.get('nic_b')
        if nic_b is not None:
            result['nic_b'] = nic_b
            ac.nic_b = nic_b

        nuc_p = decoded.get('nuc_p')
        if nuc_p is not None:
            result['nuc_p'] = nuc_p
            ac.nuc_p = nuc_p

        nac_v = decoded.get('nac_v')
        if nac_v is not None:
            result['nac_v'] = nac_v
            ac.nac_v = nac_v

        # --- Velocity (BDS 0,9 / TC 19) ---
        if decoded.get('subtype') is not None and tc == 19:
            # Ground speed or airspeed
            gs = decoded.get('groundspeed')
            airspeed = decoded.get('airspeed')
            heading = decoded.get('heading')
            track = decoded.get('track')
            vr = decoded.get('vertical_rate')
            vr_src = decoded.get('vr_source')
            as_type = decoded.get('airspeed_type')
            geo_baro = decoded.get('geo_minus_baro')

            if gs is not None:
                result['speed'] = gs
                result['speed_type'] = 'GS'
                ac.speed = gs
                ac.speed_type = 'GS'
            elif airspeed is not None:
                result['speed'] = airspeed
                result['airspeed'] = airspeed
                result['airspeed_type'] = as_type
                result['speed_type'] = as_type or 'AS'
                ac.speed = airspeed
                ac.speed_type = as_type or 'AS'

            angle = track if track is not None else heading
            if angle is not None:
                result['heading'] = angle
                ac.heading = angle

            if vr is not None:
                result['vertical_rate'] = vr
                ac.vertical_rate = vr

            if vr_src:
                result['vr_source'] = vr_src
                ac.vr_source = vr_src

            if geo_baro is not None:
                result['geo_minus_baro'] = geo_baro

        # --- Emergency (BDS 6,1 / TC 28) ---
        emerg = decoded.get('emergency_state')
        if emerg is not None:
            result['emergency'] = emerg
            result['emergency_text'] = EMERGENCY_STATES.get(emerg, f'Unknown ({emerg})')
            ac.emergency = emerg
            ac.emergency_text = result['emergency_text']

        # squawk from TC28
        sq28 = decoded.get('mode_a')
        if sq28 is not None:
            result['squawk'] = str(sq28)
            ac.squawk = str(sq28)

        # --- CPR Position Resolution ---
        cpr_fmt = decoded.get('cpr_format')
        cpr_lat = decoded.get('cpr_lat')
        cpr_lon = decoded.get('cpr_lon')

        if (cpr_fmt is not None and cpr_lat is not None and cpr_lon is not None):
            pos = ac.cpr.update(cpr_lat, cpr_lon, cpr_fmt, now)
            if pos is not None:
                result['latitude'] = pos[0]
                result['longitude'] = pos[1]
                ac.latitude = pos[0]
                ac.longitude = pos[1]
                self.stats['positions_decoded'] += 1

        # --- Build field map (deep analysis) ---
        result['field_map'] = self._build_field_map(hex_msg, df, tc, decoded, result)

        return result

    def process_cubesat_telemetry(self, payload: dict):
        """Procesa datos de telemetría provenientes del simulador/CubeSat."""
        health = payload.get('health', {})
        attitude = payload.get('attitude', {})
        
        self.cubesat_health['status'] = health.get('status', 'OFFLINE')
        self.cubesat_health['vbat'] = health.get('vbat', 0.0)
        self.cubesat_health['temp'] = health.get('temp', 0.0)
        self.cubesat_health['pitch'] = attitude.get('pitch', 0.0)
        self.cubesat_health['roll'] = attitude.get('roll', 0.0)
        self.cubesat_health['yaw'] = attitude.get('yaw', 0.0)
        self.cubesat_health['last_seen'] = time()
        
        icao = payload.get('icao')
        raw_frame = payload.get('raw_frame')
        
        if not icao or not raw_frame:
            return
            
        if icao not in self.cubesat_aircraft:
            self.cubesat_aircraft[icao] = AircraftState(icao)
            
        ac = self.cubesat_aircraft[icao]
        ac.last_seen = time()
        ac.msg_count += 1
        
        try:
            import pyModeS
            decoded = pyModeS.decode(raw_frame)
            
            if decoded.get('altitude') is not None:
                ac.altitude_baro = decoded.get('altitude')
            if decoded.get('callsign'):
                ac.callsign = decoded.get('callsign').strip('_')
            
            tc = decoded.get('typecode')
            if tc == 19:
                gs = decoded.get('groundspeed')
                airspeed = decoded.get('airspeed')
                track = decoded.get('track')
                heading = decoded.get('heading')
                vr = decoded.get('vertical_rate')
                if gs is not None:
                    ac.speed = gs
                elif airspeed is not None:
                    ac.speed = airspeed
                angle = track if track is not None else heading
                if angle is not None:
                    ac.heading = angle
                if vr is not None:
                    ac.vertical_rate = vr
            
            cpr_fmt = decoded.get('cpr_format')
            cpr_lat = decoded.get('cpr_lat')
            cpr_lon = decoded.get('cpr_lon')
            now = time()
            if (cpr_fmt is not None and cpr_lat is not None and cpr_lon is not None):
                pos = ac.cpr.update(cpr_lat, cpr_lon, cpr_fmt, now)
                if pos is not None:
                    ac.latitude = pos[0]
                    ac.longitude = pos[1]
        except Exception:
            pass

    # =========================================================================
    # Análisis profundo — Mapa de campos
    # =========================================================================
    def _build_field_map(self, msg: str, df: int, tc: Optional[int],
                         decoded: dict, result: dict) -> list:
        """Construye un mapa de campos anotado para estudio del protocolo."""
        fields = []
        n_bits = len(msg) * 4
        msg_int = int(msg, 16)

        # --- DF (bits 1-5) ---
        fields.append({
            'name': 'Downlink Format (DF)',
            'bits': '1-5',
            'value': df,
            'value_bin': bin(df)[2:].zfill(5),
            'description': DF_DESCRIPTION.get(df, 'Unknown'),
            'mandatory': True,
        })

        if n_bits == 112 and df in (17, 18):
            # === DF17/18 Extended Squitter fields ===
            ca = extract_unsigned(msg_int, 5, 3, 112)
            fields.append({
                'name': 'Capability (CA)',
                'bits': '6-8',
                'value': ca,
                'value_bin': bin(ca)[2:].zfill(3),
                'description': CAPABILITY.get(ca, 'Unknown'),
                'mandatory': True,
            })

            fields.append({
                'name': 'ICAO Address',
                'bits': '9-32',
                'value': result['icao'],
                'description': f'24-bit aircraft address',
                'mandatory': True,
            })

            if tc is not None:
                fields.append({
                    'name': 'Type Code (TC)',
                    'bits': '33-37',
                    'value': tc,
                    'value_bin': bin(tc)[2:].zfill(5),
                    'description': get_tc_description(tc),
                    'mandatory': True,
                })

            fields.append({
                'name': 'ME (Message Extended)',
                'bits': '33-88',
                'value': msg[8:22],
                'description': '56-bit payload',
                'mandatory': True,
            })

            fields.append({
                'name': 'PI (Parity/CRC)',
                'bits': '89-112',
                'value': msg[22:28],
                'description': 'CRC-24 parity check',
                'mandatory': True,
            })

            # --- TC-specific fields ---
            if tc is not None and 9 <= tc <= 18:
                ss = decoded.get('surveillance_status')
                if ss is not None:
                    fields.append({
                        'name': 'Surveillance Status',
                        'bits': '53-54',
                        'value': ss,
                        'description': SURVEILLANCE_STATUS.get(ss, ''),
                        'mandatory': True,
                    })

                alt = decoded.get('altitude')
                if alt is not None:
                    fields.append({
                        'name': 'Altitude',
                        'bits': '41-52',
                        'value': alt,
                        'description': f'{alt} ft (barometric)',
                        'mandatory': True,
                    })

                cpr_fmt = decoded.get('cpr_format')
                if cpr_fmt is not None:
                    fields.append({
                        'name': 'CPR Format (F)',
                        'bits': '54',
                        'value': cpr_fmt,
                        'description': 'Even (0)' if cpr_fmt == 0 else 'Odd (1)',
                        'mandatory': True,
                    })

                cpr_lat = decoded.get('cpr_lat')
                if cpr_lat is not None:
                    fields.append({
                        'name': 'CPR Latitude',
                        'bits': '55-71',
                        'value': cpr_lat,
                        'description': f'Encoded lat (17 bits)',
                        'mandatory': True,
                    })

                cpr_lon = decoded.get('cpr_lon')
                if cpr_lon is not None:
                    fields.append({
                        'name': 'CPR Longitude',
                        'bits': '72-88',
                        'value': cpr_lon,
                        'description': f'Encoded lon (17 bits)',
                        'mandatory': True,
                    })

            elif tc == 19:
                sub = decoded.get('subtype')
                if sub is not None:
                    desc = 'Ground Speed' if sub <= 2 else 'Airspeed'
                    fields.append({
                        'name': 'Velocity Subtype',
                        'bits': '38-40',
                        'value': sub,
                        'description': desc,
                        'mandatory': True,
                    })

        elif n_bits == 56:
            # === Short message fields ===
            fields.append({
                'name': 'Address/Parity (AP)',
                'bits': '33-56',
                'value': msg[8:14],
                'description': f'ICAO: {result["icao"]}',
                'mandatory': True,
            })

            if df in (4, 20) and decoded.get('altitude') is not None:
                fields.append({
                    'name': 'Altitude Code (AC)',
                    'bits': '20-32',
                    'value': decoded['altitude'],
                    'description': f'{decoded["altitude"]} ft',
                    'mandatory': True,
                })

            if df in (5, 21) and decoded.get('squawk') is not None:
                fields.append({
                    'name': 'Identity Code (ID)',
                    'bits': '20-32',
                    'value': decoded['squawk'],
                    'description': f'Squawk: {decoded["squawk"]}',
                    'mandatory': True,
                })

            fs = decoded.get('flight_status')
            if fs is not None:
                fields.append({
                    'name': 'Flight Status (FS)',
                    'bits': '6-8',
                    'value': fs,
                    'description': FLIGHT_STATUS.get(fs, f'Unknown ({fs})'),
                    'mandatory': True,
                })

        elif n_bits == 112 and df in (4, 5, 20, 21):
            # Long surveillance messages
            fields.append({
                'name': 'ICAO Address',
                'bits': '9-32',
                'value': result['icao'],
                'description': '24-bit aircraft address',
                'mandatory': True,
            })

        return fields

    # =========================================================================
    # Estadísticas
    # =========================================================================
    def get_stats_summary(self) -> str:
        """Genera un resumen de estadísticas."""
        elapsed = time() - self.stats['start_time']
        rate = self.stats['total_received'] / max(elapsed, 0.1)

        lines = [
            f"{C.CYAN}{'=' * 70}{C.RESET}",
            f"{C.BOLD}{C.CYAN}  ESTADISTICAS{C.RESET}",
            f"{C.CYAN}{'=' * 70}{C.RESET}",
            f"  Tiempo activo:     {elapsed:.0f}s",
            f"  Msgs recibidos:    {self.stats['total_received']}",
            f"  CRC OK:            {self.stats['crc_ok']}",
            f"  CRC Fail:          {self.stats['crc_fail']}",
            f"  Decode errors:     {self.stats['decode_error']}",
            f"  Tasa:              {rate:.1f} msg/s",
            f"  Posiciones:        {self.stats['positions_decoded']}",
            f"  Aeronaves activas: {len(self.aircraft)}",
        ]

        if self.stats['df_counts']:
            lines.append(f"  {C.DIM}Downlink Formats:{C.RESET}")
            for df_val, count in sorted(self.stats['df_counts'].items()):
                desc = DF_DESCRIPTION.get(df_val, '?')
                lines.append(f"    DF{df_val:2d} ({desc[:30]:30s}): {count}")

        if self.stats['tc_counts']:
            lines.append(f"  {C.DIM}Type Codes:{C.RESET}")
            for tc_val, count in sorted(self.stats['tc_counts'].items()):
                desc = get_tc_description(tc_val)
                lines.append(f"    TC{tc_val:2d} ({desc[:30]:30s}): {count}")

        return '\n'.join(lines)


# =============================================================================
# Formateo de salida
# =============================================================================
def format_position(lat: Optional[float], lon: Optional[float]) -> str:
    """Formatea lat/lon con indicadores N/S E/W correctos."""
    if lat is None or lon is None:
        return 'N/A'
    lat_dir = 'N' if lat >= 0 else 'S'
    lon_dir = 'E' if lon >= 0 else 'W'
    return f'{abs(lat):.6f} {lat_dir}, {abs(lon):.6f} {lon_dir}'


def format_output(data: dict, show_deep: bool = True) -> str:
    """Formatea los datos decodificados para impresión en consola."""
    lines = []
    df = data['df']
    tc = data.get('tc')

    # === Encabezado ===
    lines.append(f"{C.BOLD}{C.GREEN}{'=' * 70}{C.RESET}")
    header = (
        f"{C.BOLD}{C.WHITE}  [{data['timestamp_str']}]  "
        f"ICAO: {C.YELLOW}{data['icao']}{C.WHITE}  |  "
        f"DF{df} {data['df_description']}"
        f"{C.RESET}"
    )
    lines.append(header)
    if tc is not None:
        lines.append(
            f"{C.WHITE}     TC{tc}: {data.get('tc_description', '?')}"
            f"  (BDS {data.get('bds', '?')}){C.RESET}"
        )
    lines.append(f"{C.GREEN}{'-' * 70}{C.RESET}")

    # === Identification ===
    if data.get('callsign'):
        lines.append(f"  {C.CYAN}Callsign:      {C.BOLD}{C.WHITE}"
                      f"{data['callsign']}{C.RESET}")

    if data.get('category') or data.get('wake_vortex'):
        cat_str = data.get('wake_vortex') or data.get('category', '')
        cat_code = data.get('category_code', '')
        lines.append(f"  {C.CYAN}Category:      {C.WHITE}"
                      f"{cat_str} (code={cat_code}){C.RESET}")

    if data.get('capability_text'):
        lines.append(f"  {C.CYAN}Capability:    {C.WHITE}"
                      f"{data['capability_text']}{C.RESET}")

    if data.get('flight_status_text'):
        lines.append(f"  {C.CYAN}Flight Status: {C.WHITE}"
                      f"{data['flight_status_text']}{C.RESET}")

    # === Position ===
    if data.get('altitude_baro') is not None:
        lines.append(f"  {C.CYAN}Alt (Baro):    {C.WHITE}"
                      f"{data['altitude_baro']} ft{C.RESET}")

    if data.get('altitude_gnss') is not None:
        lines.append(f"  {C.CYAN}Alt (GNSS):    {C.WHITE}"
                      f"{data['altitude_gnss']} ft{C.RESET}")

    if data.get('latitude') is not None:
        pos_str = format_position(data['latitude'], data['longitude'])
        lines.append(f"  {C.CYAN}Position:      {C.BOLD}{C.GREEN}"
                      f"{pos_str}{C.RESET}")

    # === Velocity ===
    if data.get('speed') is not None:
        speed_label = data.get('speed_type', '')
        lines.append(f"  {C.CYAN}Speed:         {C.WHITE}"
                      f"{data['speed']:.0f} kt ({speed_label}){C.RESET}")

    if data.get('heading') is not None:
        lines.append(f"  {C.CYAN}Heading:       {C.WHITE}"
                      f"{data['heading']:.1f} deg{C.RESET}")

    if data.get('vertical_rate') is not None:
        vr = data['vertical_rate']
        vr_icon = '↑' if vr > 0 else ('↓' if vr < 0 else '→')
        vr_src = f" ({data.get('vr_source', '')})" if data.get('vr_source') else ''
        lines.append(f"  {C.CYAN}Vert Rate:     {C.WHITE}"
                      f"{vr_icon} {vr} ft/min{vr_src}{C.RESET}")

    if data.get('geo_minus_baro') is not None:
        lines.append(f"  {C.CYAN}Geo-Baro:      {C.WHITE}"
                      f"{data['geo_minus_baro']} ft{C.RESET}")

    # === Squawk / Emergency ===
    if data.get('squawk'):
        sq = str(data['squawk'])
        sq_color = C.RED if sq in ('7500', '7600', '7700') else C.WHITE
        lines.append(f"  {C.CYAN}Squawk:        {sq_color}{sq}{C.RESET}")

    if data.get('emergency') is not None and data['emergency'] != 0:
        lines.append(f"  {C.RED}{C.BOLD}  !! EMERGENCY: "
                      f"{data.get('emergency_text', '?')}{C.RESET}")

    # === Surveillance / Integrity ===
    if data.get('surveillance_text'):
        lines.append(f"  {C.CYAN}Surveillance:  {C.WHITE}"
                      f"{data['surveillance_text']}{C.RESET}")

    if data.get('cpr_format_text'):
        lines.append(f"  {C.CYAN}CPR Frame:     {C.WHITE}"
                      f"{data['cpr_format_text']}{C.RESET}")

    integrity_parts = []
    if data.get('nuc_p') is not None:
        integrity_parts.append(f"NUCp={data['nuc_p']}")
    if data.get('nic_b') is not None:
        integrity_parts.append(f"NIC_b={data['nic_b']}")
    if data.get('nac_p') is not None:
        integrity_parts.append(f"NACp={data['nac_p']}")
    if data.get('nac_v') is not None:
        integrity_parts.append(f"NACv={data['nac_v']}")
    if data.get('sil') is not None:
        integrity_parts.append(f"SIL={data['sil']}")
    if data.get('version') is not None:
        integrity_parts.append(f"Ver={data['version']}")
    if integrity_parts:
        lines.append(f"  {C.CYAN}Integrity:     {C.WHITE}"
                      f"{', '.join(integrity_parts)}{C.RESET}")

    # === Deep Analysis ===
    if show_deep:
        lines.append(f"{C.GREEN}{'-' * 70}{C.RESET}")
        lines.append(f"  {C.DIM}Raw Hex:  {data['raw_hex']}{C.RESET}")

        binstr = data['raw_binary']
        bin_fmt = ' '.join(binstr[i:i + 8] for i in range(0, len(binstr), 8))
        lines.append(f"  {C.DIM}Raw Bin:  {bin_fmt}{C.RESET}")

        if data.get('field_map'):
            lines.append(f"  {C.DIM}{'-' * 66}{C.RESET}")
            lines.append(f"  {C.DIM}{C.BOLD}  Field Map:{C.RESET}")
            for f in data['field_map']:
                m = '*' if f.get('mandatory') else ' '
                val = str(f.get('value', ''))
                if f.get('value_bin'):
                    val += f" (0b{f['value_bin']})"
                lines.append(
                    f"  {C.DIM}  {m} [{f['bits']:>7s}] "
                    f"{f['name']:30s} = {val:>16s}  "
                    f"{f.get('description', '')}{C.RESET}"
                )

    return '\n'.join(lines)


# render_dashboard fue movido a tui.py


def run_dump1090_mode(host: str, port: int):
    """
    Modo dump1090: se conecta al puerto TCP 30002 de dump1090 y lee
    mensajes hexadecimales crudos en formato AVR (*HEXHEX...;).
    
    Este es el modo recomendado porque dump1090 tiene un demodulador
    de señal muy superior al bloque adsb.demod de GNU Radio (soporta
    corrección de fase, corrección de errores de bits, y detección
    adaptativa de umbral).
    """
    import socket

    endpoint = f"tcp://{host}:{port}"

    decoder = ADSBDecoder()
    last_stats_time = time()
    STATS_INTERVAL = 30.0

    while True:
        sock = None
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(10.0)
            print(f"{C.YELLOW}  [*]{C.RESET} Conectando a dump1090 en {host}:{port}...")
            sock.connect((host, port))
            print(f"{C.GREEN}  [+]{C.RESET} Conectado exitosamente a dump1090!")
            print()

            buffer = ""
            sock.settimeout(2.0)

            while True:
                try:
                    data = sock.recv(4096)
                    if not data:
                        print(f"{C.RED}  [!] dump1090 cerró la conexión.{C.RESET}")
                        break
                    buffer += data.decode('ascii', errors='ignore')

                    # Procesar mensajes completos del formato AVR: *HEXHEX...;\n
                    while '\n' in buffer:
                        line, buffer = buffer.split('\n', 1)
                        line = line.strip()

                        if not line:
                            continue

                        # Formato AVR: *8D4840D6202CC371C32CE0576098;
                        if line.startswith('*') and line.endswith(';'):
                            hex_str = line[1:-1].upper()
                        elif line.startswith('@'):
                            # Formato AVR con timestamp: @TTTTTTTTTTTT8D...;
                            hex_str = line[13:-1].upper() if len(line) > 14 else ''
                        else:
                            # Intentar tratar como hex directo
                            hex_str = line.strip('*; \r').upper()

                        if not hex_str:
                            continue

                        # Validar que sea hexadecimal puro
                        if not all(c in '0123456789ABCDEF' for c in hex_str):
                            continue

                        # Filtrar por longitud válida (14 o 28 hex chars)
                        if len(hex_str) not in (14, 28):
                            continue

                        result = decoder.process(hex_str)

                        if result is not None:
                            icao = result.get('icao')
                            if icao and icao in decoder.aircraft and decoder.aircraft[icao].msg_count >= 2:
                                print(format_output(result, show_deep=True))
                                print()

                            now = time()
                            if now - last_stats_time >= STATS_INTERVAL:
                                print(decoder.get_stats_summary())
                                print(format_aircraft_summary(decoder.aircraft))
                                print()
                                last_stats_time = now

                except socket.timeout:
                    now = time()
                    if now - last_stats_time >= STATS_INTERVAL:
                        if decoder.stats['total_received'] > 0:
                            print(decoder.get_stats_summary())
                            print(format_aircraft_summary(decoder.aircraft))
                            print()
                        last_stats_time = now
                    continue

        except ConnectionRefusedError:
            print(f"{C.RED}  [!] No se pudo conectar a dump1090 en {host}:{port}{C.RESET}")
            print(f"{C.YELLOW}  [*] Asegúrate de que dump1090 esté corriendo con --net{C.RESET}")
            print(f"{C.YELLOW}  [*] Reintentando en 5 segundos...{C.RESET}")
            import time as t
            t.sleep(5)
            continue

        except socket.timeout:
            print(f"{C.RED}  [!] Timeout conectando a dump1090. Reintentando...{C.RESET}")
            continue

        except KeyboardInterrupt:
            break

        finally:
            if sock:
                try:
                    sock.close()
                except Exception:
                    pass

    # Resumen final
    print()
    print(decoder.get_stats_summary())
    print(format_aircraft_summary(decoder.aircraft))
    print()
    print(f"{C.WHITE}  [*] Total mensajes procesados: "
          f"{decoder.stats['total_received']}{C.RESET}")
    print(f"{C.WHITE}  [*] Total aeronaves rastreadas: "
          f"{len(decoder.aircraft)}{C.RESET}")
    print(f"{C.GREEN}  [*] Conexión cerrada limpiamente.{C.RESET}")

import threading
import json
import socket

def udp_cubesat_listener(decoder):
    """Hilo secundario que escucha paquetes UDP del CubeSat/Simulador."""
    UDP_IP = "127.0.0.1"
    UDP_PORT = 5556
    
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((UDP_IP, UDP_PORT))
    sock.settimeout(1.0)
    
    while True:
        try:
            data, _ = sock.recvfrom(4096)
            payload = json.loads(data.decode('utf-8'))
            decoder.process_cubesat_telemetry(payload)
        except socket.timeout:
            pass
        except Exception:
            pass

def run_zmq_mode():
    """
    Modo GNU Radio: se conecta al puerto ZMQ PUB de GNU Radio y lee
    mensajes PMT serializados. Usar solo si el bloque adsb.demod de
    GNU Radio está generando mensajes correctamente.
    """
    if zmq is None or pmt is None:
        print(f"{C.RED}  [!] ERROR: Las librerías zmq/pmt no están disponibles.{C.RESET}")
        print(f"{C.RED}  [!] Este modo requiere ejecutarse desde Radioconda Prompt.{C.RESET}")
        return

    endpoint = "tcp://127.0.0.1:5555"

    # --- Configurar ZMQ ---
    ctx = zmq.Context()
    subscriber = ctx.socket(zmq.SUB)
    subscriber.setsockopt(zmq.RCVHWM, 200)
    subscriber.setsockopt(zmq.SUBSCRIBE, b'')
    subscriber.setsockopt(zmq.RCVTIMEO, 2000)

    try:
        subscriber.connect(endpoint)
    except zmq.ZMQError as e:
        print(f"{C.RED}  [!] Error conectando a ZMQ: {e}{C.RESET}")
        print(f"{C.RED}  [!] Verifique que GNU Radio esta ejecutandose "
              f"y publicando en el puerto 5555{C.RESET}")
        subscriber.close()
        ctx.term()
        return

    decoder = ADSBDecoder()
    
    # Iniciar hilo de CubeSat UDP (Puerto 5556)
    t_cubesat = threading.Thread(target=udp_cubesat_listener, args=(decoder,), daemon=True)
    t_cubesat.start()

    tui = TUIDashboard()
    
    last_ui_update = 0.0
    UI_UPDATE_INTERVAL = 1.0 # 1 fps pedido por el user
    event_log = []
    MAX_LOG_LINES = 8

    try:
        while True:
            # --- Manejo de Teclado Asincrono ---
            if msvcrt.kbhit():
                key = msvcrt.getch().decode('utf-8', 'ignore').lower()
                if key == 'q':
                    break
                elif key == 'r':
                    decoder.stats['total_received'] = 0
                    decoder.stats['crc_ok'] = 0
                    decoder.stats['crc_fail'] = 0
                    decoder.stats['decode_error'] = 0
                    decoder.stats['start_time'] = time()
                elif key == 'p':
                    tui.paused = not tui.paused
                elif key == b'\xe0'.decode('utf-8', 'ignore'): # Flechas en windows mandan 0xE0 primero
                    # es una tecla especial
                    arr = msvcrt.getch()
                    if arr == b'H': # Arriba
                        if tui.page > 0:
                            tui.page -= 1
                    elif arr == b'P': # Abajo
                        tui.page += 1
                        
            if tui.paused:
                # Solo renderizamos si esta pausado (para ver el status), pero frenamos consumo? 
                # No, si frenamos consumo se llena el buffer de ZMQ y droppea.
                # Mejor seguimos consumiendo ZMQ pero no procesamos? O procesamos pero no actualizamos?
                # Vamos a seguir consumiendo para no romper ZMQ, pero no hacemos render ni decodificamos profundo.
                try:
                    raw_data = subscriber.recv(flags=zmq.NOBLOCK)
                except zmq.Again:
                    pass
                
                now = time()
                if now - last_ui_update >= UI_UPDATE_INTERVAL:
                    tui.render(decoder, "ZMQ", event_log)
                    last_ui_update = now
                    
                sleep(0.05)
                continue

            # Renderizar UI a intervalo regular
            now = time()
            if now - last_ui_update >= UI_UPDATE_INTERVAL:
                tui.render(decoder, "ZMQ", event_log)
                last_ui_update = now

            try:
                # Recepción NO BLOQUEANTE para no frenar la UI ni el teclado
                raw_data = subscriber.recv(flags=zmq.NOBLOCK)
                pdu = pmt.deserialize_str(raw_data)

                # Extraer payload del PDU (metadata . payload)
                if pmt.is_pair(pdu):
                    data_vector = pmt.cdr(pdu)
                else:
                    data_vector = pdu

                # Manejo dinámico del payload
                if pmt.is_u8vector(data_vector):
                    bits = pmt.u8vector_elements(data_vector)
                    if len(bits) in (56, 112) and all(b in (0, 1) for b in bits):
                        packed_bytes = bytearray()
                        for i in range(0, len(bits), 8):
                            byte_val = 0
                            for j in range(8):
                                byte_val = (byte_val << 1) | bits[i + j]
                            packed_bytes.append(byte_val)
                        hex_str = packed_bytes.hex().upper()
                    else:
                        hex_str = bytes(bits).hex().upper()
                elif pmt.is_symbol(data_vector):
                    hex_str = pmt.symbol_to_string(data_vector).strip().upper()
                elif pmt.is_blob(data_vector):
                    blob_data = pmt.blob_data(data_vector)
                    hex_str = bytes(blob_data).hex().upper()
                else:
                    continue

            except zmq.Again:
                sleep(0.05)
                continue

            except Exception:
                continue

            result = decoder.process(hex_str)

            if result is not None:
                icao = result.get('icao')
                if icao and icao in decoder.aircraft and decoder.aircraft[icao].msg_count == 2:
                    # Nuevo avion confirmado! (paso filtro de fantasmas)
                    event_log.append(f"{C.GREEN}[{result['timestamp_str']}] Nuevo avion detectado: {icao}{C.RESET}")
                    if len(event_log) > MAX_LOG_LINES: event_log.pop(0)
                    
                if icao and icao in decoder.aircraft and decoder.aircraft[icao].msg_count >= 2:
                    # Opcionalmente reportar cambios de estado en log si es necesario
                    # pero no saturar
                    pass

    except KeyboardInterrupt:
        print(f"\n{C.YELLOW}  [*] Interrumpido por usuario.{C.RESET}")
    finally:
        print()
        print(decoder.get_stats_summary())
        print()
        print(f"{C.WHITE}  [*] Total mensajes procesados: "
              f"{decoder.stats['total_received']}{C.RESET}")
        print(f"{C.WHITE}  [*] Total aeronaves rastreadas: "
              f"{len(decoder.aircraft)}{C.RESET}")
        subscriber.close()
        ctx.term()
        print(f"{C.GREEN}  [*] ZMQ cerrado limpiamente.{C.RESET}")


def main():
    """
    Punto de entrada principal. Selecciona el modo de operación:
    
    Por defecto: Modo dump1090 (TCP puerto 30002)
        python adsb_decoder.py
        python adsb_decoder.py --host 127.0.0.1 --port 30002
    
    Modo GNU Radio (ZMQ):
        python adsb_decoder.py --zmq
    """
    import argparse
    parser = argparse.ArgumentParser(
        description='AERO-LITORAL 26 - ADS-B/Mode-S Deep Decoder v2.1',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Modos de operación:
  Por defecto:  Conecta a dump1090 via TCP (puerto 30002).
                Requiere: dump1090 --net corriendo en la misma PC.
  
  --zmq:        Conecta a GNU Radio via ZeroMQ (puerto 5555).
                Requiere: adsb_rx_completo.py corriendo en Radioconda.

Ejemplos:
  python adsb_decoder.py                  # dump1090 local
  python adsb_decoder.py --host 192.168.1.50  # dump1090 remoto
  python adsb_decoder.py --zmq            # GNU Radio ZMQ
"""
    )
    parser.add_argument('--zmq', action='store_true',
                        help='Usar modo GNU Radio ZMQ (puerto 5555) en lugar de dump1090')
    parser.add_argument('--host', type=str, default='127.0.0.1',
                        help='IP de dump1090 (default: 127.0.0.1)')
    parser.add_argument('--port', type=int, default=30002,
                        help='Puerto TCP de dump1090 raw output (default: 30002)')

    args = parser.parse_args()

    if args.zmq:
        run_zmq_mode()
    else:
        run_dump1090_mode(args.host, args.port)


if __name__ == "__main__":
    main()

