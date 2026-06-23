"""
LITORAL-RADAR-FRP - Módulo de Interfaz y Exportación (TUI / JSON)
===================================================================
Este script tiene dos responsabilidades principales:
1. Renderizar una Interfaz de Usuario en la Terminal (TUI) utilizando secuencias de escape ANSI.
   Permite al operador visualizar las estadísticas de decodificación y el estado de las aeronaves
   directamente en la consola sin necesidad de un navegador web.
2. Serializar el estado actual del decodificador (`ADSBDecoder`) y volcarlo periódicamente
   en el archivo `web/data.json`. Este archivo es consumido asíncronamente por el Frontend Web
   (app.js) para renderizar el mapa interactivo y el panel de telemetría táctico.
"""
import os
import sys
import math
from time import time, strftime, localtime
from typing import Dict, Any, List
import re
import json

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

# Códigos ANSI para colores
class C:
    RESET = '\033[0m'
    BOLD = '\033[1m'
    DIM = '\033[2m'
    RED = '\033[31m'
    GREEN = '\033[32m'
    YELLOW = '\033[33m'
    BLUE = '\033[34m'
    MAGENTA = '\033[35m'
    CYAN = '\033[36m'
    WHITE = '\033[37m'
    BG_BLUE = '\033[44m'

# Limpieza de ANSI regex
ansi_escape = re.compile(r'(?:\x1B[@-_]|[\x80-\x9F])[0-?]*[ -/]*[@-~]')

class TUIDashboard:
    def __init__(self, version="3.2"):
        self.version = version
        self.term_width = 110
        self.term_height = 30
        self._update_terminal_size()
        
        # Paginación
        self.page = 0
        self.max_rows = 10
        self.paused = False
        
        # Limpiar la pantalla por primera y única vez
        sys.stdout.write("\033[2J")

    def _update_terminal_size(self):
        try:
            size = os.get_terminal_size()
            self.term_width = max(size.columns, 100)
            self.term_height = max(size.lines, 24)
        except OSError:
            pass

    def render(self, decoder, source_mode: str, event_log: List[str]):
        """Renderiza todo el dashboard y lo escupe a la consola sobrescribiendo."""
        self._update_terminal_size()
        lines = []

        # Usar term_width - 1 para evitar que Windows CMD haga auto-wrap de las líneas
        safe_width = self.term_width - 1
        w = safe_width - 2  # Espacio interno restando los bordes izquierdo y derecho

        # --- HEADER ---
        now_str = strftime('%H:%M:%S', localtime())
        status_txt = "● PAUSADO" if self.paused else "● ONLINE"
        title = f"AERO-LITORAL 26 - UTN-FRP | Dev: Moreira, G.F. | v{self.version}"
        
        # Calculamos padding exacto sin exceder w
        rem = w - len(title) - len(status_txt) - len(now_str) - 2 # 2 espacios para separar
        if rem > 0:
            pad1 = rem // 2
            pad2 = rem - pad1
            header_text = f" {title}{' ' * pad1}{status_txt}{' ' * pad2}{now_str} "
        else:
            header_text = f" {title} {status_txt} {now_str} "[:w]
            
        lines.append(f"┌{'─' * w}┐")
        lines.append(f"│{header_text:<{w}}│")
        lines.append(f"├{'─' * w}┤")

        # --- ESTADISTICAS ---
        stats = decoder.stats
        elapsed = max(time() - stats['start_time'], 0.1)
        fps = stats['total_received'] / elapsed
        act_count = len([ac for ac in decoder.aircraft.values() if ac.age() < 60])
        
        m_s = int(elapsed)
        m = m_s // 60
        s = m_s % 60
        h = m // 60
        m = m % 60
        uptime = f"{h:02d}:{m:02d}:{s:02d}"

        stats_text = (f" Tiempo: {uptime} │ Msg/s: {fps:.2f} │ CRC OK: {stats['crc_ok']} │ "
                      f"CRC FAIL: {stats['crc_fail']} │ Decode: {stats['decode_error']} │ "
                      f"Activas: {act_count} │ ZMQ: OK ")
        lines.append(f"│{stats_text:<{w}}│")
        lines.append(f"└{'─' * w}┘")
        lines.append(" " * (w + 2))

        # --- PROGRESS BARS (DF / TC) ---
        df_counts = sorted(stats['df_counts'].items(), key=lambda x: x[0])
        tc_counts = sorted(stats['tc_counts'].items(), key=lambda x: x[0])
        
        df_lines = self._build_bars(df_counts, prefix="DF", width=30)
        tc_lines = self._build_bars(tc_counts, prefix="TC", width=34)

        max_bar_lines = max(len(df_lines), len(tc_lines), 4)
        
        lines.append(f"┌{'─' * 14} DF {'─' * 14}┐   ┌{'─' * 12} TYPE CODES {'─' * 12}┐")
        for i in range(max_bar_lines):
            df_l = df_lines[i] if i < len(df_lines) else ""
            tc_l = tc_lines[i] if i < len(tc_lines) else ""
            lines.append(f"│ {df_l:<30} │   │ {tc_l:<34} │")
        lines.append(f"└{'─' * 32}┘   └{'─' * 36}┘".ljust(w + 2))
        lines.append(" " * (w + 2))

        # --- AERONAVES ---
        table_title = f" AERONAVES (Total: {len(decoder.aircraft)}) "
        pad_l = (w - len(table_title)) // 2
        pad_r = w - len(table_title) - pad_l
        lines.append(f"┌{'─' * pad_l}{table_title}{'─' * pad_r}┐")
        header_cols = " ESTADO │ ICAO   │ VUELO │ ALT(m)│ SPD │ HDG │ V/S │ DIST │ RSSI │ LAT         │ LON         │ ÚLTIMO"
        lines.append(f"│{header_cols:<{w}}│")
        lines.append(f"├{'─' * w}┤")

        real_aircraft = [ac for ac in decoder.aircraft.values() if ac.msg_count >= 2]
        sorted_acs = sorted(real_aircraft, key=lambda x: x.last_seen, reverse=True)
        
        # Calculate max rows dynamically, leaving 1 blank line at bottom
        used_lines = 4 + 3 + (4 + max_bar_lines) + 2 + 3 + 8 + 3
        self.max_rows = max(self.term_height - used_lines - 2, 3) 

        max_pages = math.ceil(len(sorted_acs) / self.max_rows) if len(sorted_acs) > 0 else 1
        if self.page >= max_pages:
            self.page = max_pages - 1
            
        display_acs = sorted_acs[self.page * self.max_rows : (self.page + 1) * self.max_rows]

        for ac in display_acs:
            age_sec = ac.age()
            if age_sec < 30:
                est_raw = "LIVE"
                color = C.GREEN
            elif age_sec < 120:
                est_raw = "LOST"
                color = C.YELLOW
            else:
                est_raw = "DEAD"
                color = C.DIM + C.RED

            icao = ac.icao
            cs = ac.callsign or '---'
            alt = f'{int(ac.altitude_baro * 0.3048)}' if ac.altitude_baro is not None else '---'
            spd = f'{int(ac.speed * 1.852)}' if ac.speed is not None else '---'
            hdg = f'{ac.heading:.0f}°' if ac.heading is not None else '---'
            vr = f'{int(ac.vertical_rate * 0.3048)}' if ac.vertical_rate is not None else '---'
            lat = f"{abs(ac.latitude):.6f} {'S' if ac.latitude<0 else 'N'}" if ac.latitude else '---'
            lon = f"{abs(ac.longitude):.6f} {'W' if ac.longitude<0 else 'E'}" if ac.longitude else '---'
            age_s = f"{age_sec:.0f} s"
            
            dist = "---"
            rssi = "---"

            # Reemplacé los emojis por texto puro para evitar el desajuste de padding en Windows CMD
            painted_row = f"{color} {est_raw:<5} {C.RESET}│ {icao:<6} │ {cs:<5} │ {alt:>5} │ {spd:>3} │ {hdg:>3} │ {vr:>3} │ {dist:>4} │ {rssi:>4} │ {lat:<11} │ {lon:<11} │ {age_s:<6}"
            
            clean_len = len(ansi_escape.sub('', painted_row))
            pad_len = w - clean_len
            if pad_len > 0:
                painted_row += " " * pad_len
            
            lines.append(f"│{painted_row}│")
            
        for _ in range(self.max_rows - len(display_acs)):
            lines.append(f"│{' ' * w}│")
            
        lines.append(f"└{'─' * w}┘")
        lines.append(" " * (w + 2))

        # --- EVENTOS ---
        ev_title = " EVENTOS "
        pad_l = (w - len(ev_title)) // 2
        pad_r = w - len(ev_title) - pad_l
        lines.append(f"┌{'─' * pad_l}{ev_title}{'─' * pad_r}┐")
        
        for i in range(6):
            if i < len(event_log):
                raw_ev = event_log[-(i+1)]
                clean_ev = ansi_escape.sub('', raw_ev)
                
                pad_len = w - len(clean_ev) - 2 # left and right space
                if pad_len < 0:
                    clean_ev = clean_ev[:w-5] + "..."
                    raw_ev = clean_ev
                    pad_len = 0
                
                lines.append(f"│ {raw_ev}{' ' * pad_len} │")
            else:
                lines.append(f"│{' ' * w}│")
                
        lines.append(f"└{'─' * w}┘")
        lines.append(" " * (w + 2))

        # --- FOOTER ---
        footer_txt = f" Q Salir     R Reset     S Exportar CSV     P Pausar     ↑↓ Pag: {self.page+1}/{max_pages} "
        lines.append(f" {footer_txt} ")

        # Truncar cantidad total de lineas a term_height - 1 para evitar cascada
        max_lines_allowed = self.term_height - 1
        if len(lines) > max_lines_allowed:
            lines = lines[:max_lines_allowed]

        # Imprimir de una sin \n al final!
        sys.stdout.write("\033[?25l\033[H" + "\n".join(lines) + "\033[?25h")
        sys.stdout.flush()

        # EXPORTACIÓN SILENCIOSA PARA WEB DASHBOARD
        self._export_json(decoder)

    def _export_json(self, decoder):
        """Exporta el estado actual a web/data.json para el LITORAL-RADAR-FRP."""
        health = getattr(decoder, 'cubesat_health', {})
        if time() - health.get('last_seen', 0) > 5.0:
            health['status'] = 'OFFLINE'
            
        data = {
            "timestamp": time(),
            "stats": {
                "total_received": decoder.stats['total_received'],
                "crc_ok": decoder.stats['crc_ok'],
                "crc_fail": decoder.stats['crc_fail'],
                "decode_error": decoder.stats['decode_error']
            },
            "aircraft": [],
            "cubesat_aircraft": [],
            "cubesat_health": health
        }
        
        # Filtrar aeronaves reales de Tierra
        for icao, ac in decoder.aircraft.items():
            if ac.msg_count >= 2:
                data["aircraft"].append({
                    "icao": icao,
                    "callsign": ac.callsign,
                    "altitude": ac.altitude_baro,
                    "speed": ac.speed,
                    "heading": ac.heading,
                    "vertical_rate": ac.vertical_rate,
                    "latitude": ac.latitude,
                    "longitude": ac.longitude,
                    "age": ac.age(),
                    "first_seen": ac.first_seen,
                    "last_seen": ac.last_seen
                })

        # Filtrar aeronaves reales del CubeSat
        if hasattr(decoder, 'cubesat_aircraft'):
            for icao, ac in decoder.cubesat_aircraft.items():
                if ac.msg_count >= 2:
                    data["cubesat_aircraft"].append({
                        "icao": icao,
                        "callsign": ac.callsign,
                        "altitude": ac.altitude_baro,
                        "speed": ac.speed,
                        "heading": ac.heading,
                        "vertical_rate": ac.vertical_rate,
                        "latitude": ac.latitude,
                        "longitude": ac.longitude,
                        "age": ac.age(),
                        "first_seen": ac.first_seen,
                        "last_seen": ac.last_seen
                    })
        
        try:
            os.makedirs("web", exist_ok=True)
            with open("web/data.json", "w", encoding="utf-8") as f:
                json.dump(data, f)
        except Exception:
            pass

    def _build_bars(self, counts, prefix, width):
        if not counts:
            return []
        max_val = max(v for k, v in counts)
        res = []
        for k, v in sorted(counts, key=lambda x: x[1], reverse=True)[:4]:
            bar_w = int((v / max_val) * (width - 15))
            bar = '█' * bar_w
            res.append(f"{prefix}{k:<2} {bar} {v}")
        return res
