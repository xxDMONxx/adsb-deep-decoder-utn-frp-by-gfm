#!/usr/bin/env python3
# -*- coding: utf-8 -*-

#
# SPDX-License-Identifier: GPL-3.0
#
# GNU Radio Python Flow Graph
# Title: Recepcion ADS-B (AERO-LITORAL 26)
# GNU Radio version: 3.10.12.0

from PyQt5 import Qt
from gnuradio import qtgui
from gnuradio import blocks
from gnuradio import blocks, gr
from gnuradio import gr
from gnuradio.filter import firdes
from gnuradio.fft import window
import sys
import signal
from PyQt5 import Qt
from argparse import ArgumentParser
from gnuradio.eng_arg import eng_float, intx
from gnuradio import eng_notation
from gnuradio import soapy
from gnuradio import zeromq
import gnuradio.adsb as adsb
import threading
import time
import numpy as np
import pmt

class rf_monitor(gr.sync_block):
    def __init__(self, framer_block):
        gr.sync_block.__init__(self, name="rf_monitor", in_sig=[np.float32], out_sig=None)
        self.framer_block = framer_block
        self.tags_count = 0
        self.buffer = []
        self.burst_tag = pmt.intern("burst")
        self.thresholds = [0.002]
        self.current_th_idx = 0
        self.sweep_interval = 60.0
        self.last_print = time.time()
        self.last_sweep = time.time()
        
        if self.framer_block:
            self.framer_block.set_threshold(self.thresholds[self.current_th_idx])
            print(f"\n{'='*50}\n[SWEEP INICIAL] Threshold = {self.thresholds[self.current_th_idx]}\n{'='*50}")
            
    def work(self, input_items, output_items):
        in0 = input_items[0]
        n = len(in0)
        if n == 0: return 0
            
        tags = self.get_tags_in_range(0, self.nitems_read(0), self.nitems_read(0) + n, self.burst_tag)
        self.tags_count += len(tags)
        
        # Submuestreo estadístico (1 de cada 100) para no fundir el CPU
        self.buffer.append(in0[::100].copy())
        
        now = time.time()
        
        # Cada 10 segundos calculamos e imprimimos percentiles
        if now - self.last_print >= 10.0:
            if len(self.buffer) > 0:
                all_samples = np.concatenate(self.buffer)
                p90, p95, p99, p999, p100 = np.percentile(all_samples, [90, 95, 99, 99.9, 100])
                mean = np.mean(all_samples)
            else:
                mean = p90 = p95 = p99 = p999 = p100 = 0.0
                
            try:
                cpu_usage = f"{psutil.cpu_percent()}%"
            except:
                cpu_usage = "N/A"
                
            rate = self.tags_count * 6
            th = self.thresholds[self.current_th_idx]
            
            print(f"\n[TH={th}] CPU: {cpu_usage} | Bursts/min: {rate}")
            print(f"   -> Mag2 Mean: {mean:.6f} | P90: {p90:.6f} | P95: {p95:.6f} | P99: {p99:.6f} | P99.9: {p999:.6f} | Max: {p100:.6f}")
            
            self.tags_count = 0
            self.buffer = []
            self.last_print = now
            
        return n



class adsb_rx_completo(gr.top_block, Qt.QWidget):

    def __init__(self):
        gr.top_block.__init__(self, "Recepcion ADS-B (AERO-LITORAL 26)", catch_exceptions=True)
        Qt.QWidget.__init__(self)
        self.setWindowTitle("Recepcion ADS-B (AERO-LITORAL 26)")
        qtgui.util.check_set_qss()
        try:
            self.setWindowIcon(Qt.QIcon.fromTheme('gnuradio-grc'))
        except BaseException as exc:
            print(f"Qt GUI: Could not set Icon: {str(exc)}", file=sys.stderr)
        self.top_scroll_layout = Qt.QVBoxLayout()
        self.setLayout(self.top_scroll_layout)
        self.top_scroll = Qt.QScrollArea()
        self.top_scroll.setFrameStyle(Qt.QFrame.NoFrame)
        self.top_scroll_layout.addWidget(self.top_scroll)
        self.top_scroll.setWidgetResizable(True)
        self.top_widget = Qt.QWidget()
        self.top_scroll.setWidget(self.top_widget)
        self.top_layout = Qt.QVBoxLayout(self.top_widget)
        self.top_grid_layout = Qt.QGridLayout()
        self.top_layout.addLayout(self.top_grid_layout)

        self.settings = Qt.QSettings("gnuradio/flowgraphs", "adsb_rx_completo")

        try:
            geometry = self.settings.value("geometry")
            if geometry:
                self.restoreGeometry(geometry)
        except BaseException as exc:
            print(f"Qt GUI: Could not restore geometry: {str(exc)}", file=sys.stderr)
        self.flowgraph_started = threading.Event()

        ##################################################
        # Variables
        ##################################################
        self.samp_rate = samp_rate = 2000000
        self.freq = freq = 1090e6

        ##################################################
        # Blocks
        ##################################################

        self.zeromq_pub_msg_sink_0 = zeromq.pub_msg_sink('tcp://127.0.0.1:5555', 100, True)
        self.soapy_rtlsdr_source_0 = None
        dev = 'driver=rtlsdr'
        stream_args = 'bufflen=1048576'
        tune_args = ['']
        settings = ['']

        def _set_soapy_rtlsdr_source_0_gain_mode(channel, agc):
            self.soapy_rtlsdr_source_0.set_gain_mode(channel, agc)
            if not agc:
                  self.soapy_rtlsdr_source_0.set_gain(channel, self._soapy_rtlsdr_source_0_gain_value)
        self.set_soapy_rtlsdr_source_0_gain_mode = _set_soapy_rtlsdr_source_0_gain_mode

        def _set_soapy_rtlsdr_source_0_gain(channel, name, gain):
            self._soapy_rtlsdr_source_0_gain_value = gain
            if not self.soapy_rtlsdr_source_0.get_gain_mode(channel):
                self.soapy_rtlsdr_source_0.set_gain(channel, gain)
        self.set_soapy_rtlsdr_source_0_gain = _set_soapy_rtlsdr_source_0_gain

        def _set_soapy_rtlsdr_source_0_bias(bias):
            if 'biastee' in self._soapy_rtlsdr_source_0_setting_keys:
                self.soapy_rtlsdr_source_0.write_setting('biastee', bias)
        self.set_soapy_rtlsdr_source_0_bias = _set_soapy_rtlsdr_source_0_bias

        self.soapy_rtlsdr_source_0 = soapy.source(dev, "fc32", 1, '',
                                  stream_args, tune_args, settings)

        self._soapy_rtlsdr_source_0_setting_keys = [a.key for a in self.soapy_rtlsdr_source_0.get_setting_info()]

        self.soapy_rtlsdr_source_0.set_sample_rate(0, samp_rate)
        self.soapy_rtlsdr_source_0.set_frequency(0, freq)
        self.soapy_rtlsdr_source_0.set_frequency_correction(0, 0)
        self.set_soapy_rtlsdr_source_0_bias(bool(False))
        self._soapy_rtlsdr_source_0_gain_value = 49.6
        self.set_soapy_rtlsdr_source_0_gain_mode(0, bool(False))
        self.set_soapy_rtlsdr_source_0_gain(0, 'TUNER', 49.6)
        self.blocks_null_sink_0 = blocks.null_sink(gr.sizeof_float*1)
        self.blocks_message_debug_0 = blocks.message_debug(True, gr.log_levels.info)
        self.blocks_complex_to_mag_squared_0 = blocks.complex_to_mag_squared(1)
        from custom_framer import framer as custom_framer
        self.adsb_framer_0 = custom_framer(2e6, 0.002)
        self.rf_monitor_0 = rf_monitor(self.adsb_framer_0)
        self.adsb_demod_0 = adsb.demod(2e6)


        ##################################################
        # Connections
        ##################################################
        self.msg_connect((self.adsb_demod_0, 'demodulated'), (self.blocks_message_debug_0, 'print'))
        self.msg_connect((self.adsb_demod_0, 'demodulated'), (self.zeromq_pub_msg_sink_0, 'in'))
        self.connect((self.adsb_demod_0, 0), (self.blocks_null_sink_0, 0))
        self.connect((self.soapy_rtlsdr_source_0, 0), (self.blocks_complex_to_mag_squared_0, 0))
        self.connect((self.blocks_complex_to_mag_squared_0, 0), (self.adsb_framer_0, 0))
        self.connect((self.adsb_framer_0, 0), (self.adsb_demod_0, 0))
        self.connect((self.adsb_framer_0, 0), (self.rf_monitor_0, 0))


    def closeEvent(self, event):
        self.settings = Qt.QSettings("gnuradio/flowgraphs", "adsb_rx_completo")
        self.settings.setValue("geometry", self.saveGeometry())
        self.stop()
        self.wait()

        event.accept()

    def get_samp_rate(self):
        return self.samp_rate

    def set_samp_rate(self, samp_rate):
        self.samp_rate = samp_rate
        self.soapy_rtlsdr_source_0.set_sample_rate(0, self.samp_rate)

    def get_freq(self):
        return self.freq

    def set_freq(self, freq):
        self.freq = freq
        self.soapy_rtlsdr_source_0.set_frequency(0, self.freq)




def main(top_block_cls=adsb_rx_completo, options=None):

    qapp = Qt.QApplication(sys.argv)
    tb = top_block_cls()

    tb.start()
    tb.flowgraph_started.set()

    # Eliminamos tb.show() para que no aparezca la ventana en blanco
    
    def sig_handler(sig=None, frame=None):
        tb.stop()
        tb.wait()
        Qt.QApplication.quit()

    signal.signal(signal.SIGINT, sig_handler)
    try:
        signal.signal(signal.SIGTERM, sig_handler)
    except AttributeError:
        pass  # Evita el crasheo nativo en Windows

    timer = Qt.QTimer()
    timer.start(500)
    timer.timeout.connect(lambda: None)

    print("Receptor de Radio activo y trabajando en 2do plano.")
    qapp.exec_()

if __name__ == '__main__':
    main()
