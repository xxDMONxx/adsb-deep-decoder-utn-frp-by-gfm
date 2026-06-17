import os
import sys
import math
from time import time, strftime, localtime
from typing import Dict, Any, List
import re

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

        # --- HEADER ---
        w = self.term_width - 2
        now_str = strftime('%H:%M:%S', localtime())
        status_txt = "● PAUSADO " if self.paused else "● ONLINE  "
        header_text = f" ADS-B RECEIVER v{self.version}                              {status_txt}                           {now_str} "
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
        lines.append("")

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
        lines.append(f"└{'─' * 32}┘   └{'─' * 36}┘")
        lines.append("")

        # --- AERONAVES ---
        table_title = f" AERONAVES (Total: {len(decoder.aircraft)}) "
        pad_l = (w - len(table_title)) // 2
        pad_r = w - len(table_title) - pad_l
        lines.append(f"┌{'─' * pad_l}{table_title}{'─' * pad_r}┐")
        header_cols = "ESTADO │ ICAO   │ VUELO │ ALT(m)│ SPD │ HDG │ V/S │ DIST │ RSSI │ LAT         │ LON         │ ÚLTIMO"
        lines.append(f"│{header_cols:<{w}}│")
        lines.append(f"├{'─' * 7}┼{'─' * 8}┼{'─' * 7}┼{'─' * 7}┼{'─' * 5}┼{'─' * 5}┼{'─' * 5}┼{'─' * 6}┼{'─' * 6}┼{'─' * 13}┼{'─' * 13}┼{'─' * 8}┤")

        # No limit on aircraft rendering if they're real
        real_aircraft = [ac for ac in decoder.aircraft.values() if ac.msg_count >= 2]
        sorted_acs = sorted(real_aircraft, key=lambda x: x.last_seen, reverse=True)
        
        # Calculate max rows dynamically
        used_lines = 4 + 3 + (4 + max_bar_lines) + 2 + 3 + 8 + 3
        self.max_rows = max(self.term_height - used_lines - 4, 3) 

        # Paginación simplificada
        max_pages = math.ceil(len(sorted_acs) / self.max_rows) if len(sorted_acs) > 0 else 1
        if self.page >= max_pages:
            self.page = max_pages - 1
            
        display_acs = sorted_acs[self.page * self.max_rows : (self.page + 1) * self.max_rows]

        for ac in display_acs:
            age_sec = ac.age()
            if age_sec < 30:
                est_raw = "🟢 LIVE"
                color = C.GREEN
            elif age_sec < 120:
                est_raw = "🟡 LOST"
                color = C.YELLOW
            else:
                est_raw = "🔴 DEAD"
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

            raw_row = f"{est_raw:<7}│ {icao:<6} │ {cs:<5} │ {alt:>5} │ {spd:>3} │ {hdg:>3} │ {vr:>3} │ {dist:>4} │ {rssi:>4} │ {lat:<11} │ {lon:<11} │ {age_s:<6}"
            
            # The length of '🟢 LIVE' is visually 7, but len("🟢 LIVE") in Python might be 6 or 7 depending on encoding. 
            # Emojis usually count as 1 char but occupy 2 spaces in monospaced fonts.
            # We will use ansi padding
            
            painted_row = f"{color}{est_raw}{C.RESET}│ {icao:<6} │ {cs:<5} │ {alt:>5} │ {spd:>3} │ {hdg:>3} │ {vr:>3} │ {dist:>4} │ {rssi:>4} │ {lat:<11} │ {lon:<11} │ {age_s:<6}"
            
            clean_len = len(ansi_escape.sub('', painted_row))
            # Emojis take 2 spaces, let's assume length is clean_len + 1 for padding
            pad_len = w - clean_len - 1
            if pad_len > 0:
                painted_row += " " * pad_len
            
            lines.append(f"│{painted_row}│")
            
        for _ in range(self.max_rows - len(display_acs)):
            lines.append(f"│{' ' * w}│")
            
        lines.append(f"└{'─' * w}┘")
        lines.append("")

        # --- EVENTOS ---
        ev_title = " EVENTOS "
        pad_l = (w - len(ev_title)) // 2
        pad_r = w - len(ev_title) - pad_l
        lines.append(f"┌{'─' * pad_l}{ev_title}{'─' * pad_r}┐")
        
        # Mostrar ultimos 6
        for i in range(6):
            if i < len(event_log):
                raw_ev = event_log[-(i+1)]
                clean_ev = ansi_escape.sub('', raw_ev)
                
                pad_len = w - len(clean_ev) - 2 # left and right space
                if pad_len < 0:
                    clean_ev = clean_ev[:w-5] + "..."
                    pad_len = 0
                
                lines.append(f"│ {raw_ev}{' ' * pad_len} │")
            else:
                lines.append(f"│{' ' * w}│")
                
        lines.append(f"└{'─' * w}┘")
        lines.append("")

        # --- FOOTER ---
        footer_txt = f" Q Salir     R Reset     S Exportar CSV     P Pausar     ↑↓ Pag: {self.page+1}/{max_pages} "
        lines.append(f" {footer_txt} ")

        # Imprimir de una: ocultar cursor, mover a origen, imprimir, mostrar cursor (al final, o dejarlo oculto)
        # \033[?25l = oculta cursor
        # \033[?25h = muestra cursor
        sys.stdout.write("\033[?25l\033[H" + "\n".join(lines) + "\n\033[?25h")
        sys.stdout.flush()

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
