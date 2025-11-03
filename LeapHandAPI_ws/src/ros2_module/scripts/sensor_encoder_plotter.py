#!/usr/bin/env python3
# sensor_encoder_plotter.py
import os
# Ensure interactive backend before pyplot import
try:
    import matplotlib
    if os.environ.get("MPLBACKEND", "").lower() not in ("tkagg", "qt5agg", "qtagg"):
        matplotlib.use("TkAgg")
except Exception:
    pass

import rclpy
from rclpy.node import Node
from std_msgs.msg import Float32MultiArray

import matplotlib.pyplot as plt
from collections import deque
import numpy as np
import time
import math

TOPIC          = '/sensor_vs_encoder'
WINDOW_SEC     = 8.0      # cross-correlation window
PLOT_RATE_HZ   = 20.0
SUB_QUEUE_SIZE = 50

class SEPlotter(Node):
    def __init__(self):
        super().__init__('sensor_encoder_plotter')
        self.sub = self.create_subscription(Float32MultiArray, TOPIC, self.cb, SUB_QUEUE_SIZE)
        self.t0 = time.time()

        self.t = deque()
        self.sensor = deque()
        self.encoder = deque()

        self.create_timer(1.0 / PLOT_RATE_HZ, self.update_plot)

        # matplotlib
        plt.ion()
        self.fig, self.ax = plt.subplots(1, 1, figsize=(9, 4.8))
        self.l_sens, = self.ax.plot([], [], label='Sensor (deg)')
        self.l_enc,  = self.ax.plot([], [], label='Encoder (deg)')
        self.ax.set_xlabel('time (s)')
        self.ax.set_ylabel('deg')
        self.ax.legend(loc='upper left')
        self.text = self.ax.text(0.02, 0.95, '', transform=self.ax.transAxes, va='top')
        self.fig.tight_layout()

        # debug rate
        self.msg_count = 0
        self.last_rate_print = time.time()

    def cb(self, msg: Float32MultiArray):
        now = time.time() - self.t0
        if len(msg.data) < 2:
            return
        s, e = msg.data
        # Store even if NaN; we'll mask later
        self.t.append(now)
        self.sensor.append(float(s))
        self.encoder.append(float(e))

        # prune window
        while self.t and (now - self.t[0] > WINDOW_SEC):
            self.t.popleft(); self.sensor.popleft(); self.encoder.popleft()

        # debug input rate
        self.msg_count += 1
        if now - self.last_rate_print > 2.0:
            rate = self.msg_count / (now - self.last_rate_print)
            self.get_logger().info(f"{TOPIC} ~{rate:.1f} msg/s")
            self.msg_count = 0
            self.last_rate_print = now

    def update_plot(self):
        if not self.t:
            return
        x = np.asarray(self.t, dtype=float)
        s = np.asarray(self.sensor, dtype=float)
        e = np.asarray(self.encoder, dtype=float)

        # mask NaNs
        m_s = np.isfinite(s)
        m_e = np.isfinite(e)

        self.l_sens.set_data(x[m_s], s[m_s])
        self.l_enc.set_data(x[m_e],  e[m_e])

        # axes limits
        xmin = max(0.0, x[-1] - WINDOW_SEC)
        xmax = x[-1] if x[-1] > xmin else xmin + 1.0
        self.ax.set_xlim(xmin, xmax)

        # y autoscale based on finite values
        yvals = []
        if np.any(m_s): yvals.append(s[m_s])
        if np.any(m_e): yvals.append(e[m_e])
        if yvals:
            ycat = np.concatenate(yvals)
            ylo, yhi = np.nanmin(ycat), np.nanmax(ycat)
            if ylo == yhi:
                ylo -= 1.0; yhi += 1.0
            pad = 0.05 * (yhi - ylo) + 0.1
            self.ax.set_ylim(ylo - pad, yhi + pad)

        # delay estimate (ms): cross-correlation on detrended, z-scored signals
        delay_ms = np.nan
        if np.sum(m_s) > 10 and np.sum(m_e) > 10:
            # resample both onto a uniform grid for stable correlation
            grid = np.linspace(x[-1] - min(WINDOW_SEC, x[-1]-x[0]), x[-1], 256)
            try:
                s_i = np.interp(grid, x[m_s], s[m_s])
                e_i = np.interp(grid, x[m_e], e[m_e])

                # detrend & normalize
                s_i = (s_i - np.mean(s_i)) / (np.std(s_i) + 1e-6)
                e_i = (e_i - np.mean(e_i)) / (np.std(e_i) + 1e-6)

                cc = np.correlate(s_i, e_i, mode='full')
                lags = np.arange(-len(grid)+1, len(grid))
                best = np.argmax(cc)
                lag_s = lags[best] * (grid[1] - grid[0])

                # Convention: positive lag => encoder lags sensor by lag_s
                delay_ms = 1000.0 * lag_s
            except Exception:
                pass

        # print on figure
        if np.isfinite(delay_ms):
            self.text.set_text(f"Estimated hardware delay: {delay_ms:+6.1f} ms")
        else:
            self.text.set_text("Estimating delay...")

        # draw
        self.fig.canvas.draw_idle()
        self.fig.canvas.flush_events()
        plt.pause(1.0 / PLOT_RATE_HZ)

def main(args=None):
    rclpy.init(args=args)
    node = SEPlotter()
    try:
        while rclpy.ok():
            rclpy.spin_once(node, timeout_sec=0.02)
            plt.pause(0.001)
    except KeyboardInterrupt:
        pass
    plt.ioff(); plt.show()
    node.destroy_node()
    rclpy.shutdown()

if __name__ == '__main__':
    main()
