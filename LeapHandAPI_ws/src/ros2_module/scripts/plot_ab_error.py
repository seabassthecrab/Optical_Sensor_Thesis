#!/usr/bin/env python3
# ab_diff_plotter.py
import os
# ---- choose an interactive backend BEFORE importing pyplot ----
# Try Tk first; fall back to Qt if needed.
try:
    import matplotlib
    if os.environ.get("MPLBACKEND", "").lower() not in ("tkagg", "qt5agg", "qtagg"):
        matplotlib.use("TkAgg")
except Exception:
    try:
        import matplotlib
        matplotlib.use("Qt5Agg")
    except Exception:
        pass  # hope default is interactive

import rclpy
from rclpy.node import Node
from std_msgs.msg import Float32MultiArray

import matplotlib.pyplot as plt
from collections import deque
import numpy as np
import time
import math

WINDOW_SEC   = 10.0   # show last N seconds
PLOT_RATE_HZ = 20.0   # redraw rate

class DiffPlotter(Node):
    def __init__(self):
        super().__init__('ab_diff_plotter')
        self.sub = self.create_subscription(Float32MultiArray, '/ab_diff', self.cb, 10)

        self.times = deque()
        self.cmd = deque()
        self.act = deque()
        self.err = deque()
        self.t0 = time.time()

        # Rx rate debug
        self.msg_count = 0
        self.last_rate_print = time.time()

        self.create_timer(1.0 / PLOT_RATE_HZ, self.update_plot)

        # matplotlib setup
        plt.ion()
        self.fig, (self.ax1, self.ax2) = plt.subplots(2, 1, figsize=(9, 6))
        self.l_cmd, = self.ax1.plot([], [], label='cmd diff (deg)')
        self.l_act, = self.ax1.plot([], [], label='act diff (deg)')
        self.ax1.legend(loc='upper left')
        self.ax1.set_ylabel('deg')
        self.ax1.set_title('A–B difference')

        self.l_err, = self.ax2.plot([], [], label='error (cmd - act)')
        self.ax2.legend(loc='upper left')
        self.ax2.set_ylabel('deg')
        self.ax2.set_xlabel('time (s)')

        self.fig.tight_layout()

    def cb(self, msg: Float32MultiArray):
        t = time.time() - self.t0
        # Expect [cmd, act, err]
        if len(msg.data) < 3:
            return
        c, a, e = msg.data

        # sanitize nans: keep cmd as finite; allow NaNs for act/err but store as np.nan
        if math.isnan(c):
            c = float('nan')  # shouldn't happen, but don't crash
        a = float('nan') if (isinstance(a, float) and math.isnan(a)) else a
        e = float('nan') if (isinstance(e, float) and math.isnan(e)) else e

        self.times.append(t)
        self.cmd.append(float(c))
        self.act.append(float(a))
        self.err.append(float(e))

        # prune by time window
        while self.times and (t - self.times[0] > WINDOW_SEC):
            self.times.popleft(); self.cmd.popleft(); self.act.popleft(); self.err.popleft()

        # simple Rx rate printout (helps diagnose "no data")
        self.msg_count += 1
        if t - self.last_rate_print > 2.0:
            rate = self.msg_count / (t - self.last_rate_print)
            self.get_logger().info(f"/ab_diff incoming ~{rate:.1f} msg/s")
            self.msg_count = 0
            self.last_rate_print = t

    def update_plot(self):
        if not self.times:
            return

        x = np.array(self.times, dtype=float)

        y_cmd = np.array(self.cmd, dtype=float)
        y_act = np.array(self.act, dtype=float)
        y_err = np.array(self.err, dtype=float)

        # mask NaNs so lines draw correctly
        mask_cmd = np.isfinite(y_cmd)
        mask_act = np.isfinite(y_act)
        mask_err = np.isfinite(y_err)

        # update lines
        self.l_cmd.set_data(x[mask_cmd], y_cmd[mask_cmd])
        self.l_act.set_data(x[mask_act], y_act[mask_act])
        self.l_err.set_data(x[mask_err], y_err[mask_err])

        # x-limits: last WINDOW_SEC
        xmin = max(0.0, x[-1] - WINDOW_SEC)
        xmax = x[-1] if x[-1] > xmin else xmin + 1.0
        self.ax1.set_xlim(xmin, xmax)
        self.ax2.set_xlim(xmin, xmax)

        # y-limits: robust autoscale using finite values
        def finite_minmax(arr):
            if np.any(np.isfinite(arr)):
                return np.nanmin(arr), np.nanmax(arr)
            return 0.0, 1.0

        y1_lo, y1_hi = finite_minmax(np.concatenate([y_cmd[mask_cmd], y_act[mask_act]]) if (mask_cmd.any() or mask_act.any()) else np.array([np.nan]))
        y2_lo, y2_hi = finite_minmax(y_err[mask_err])

        # add margins so lines aren't on the frame
        def margin(lo, hi):
            if not np.isfinite(lo) or not np.isfinite(hi) or lo == hi:
                return (lo - 1.0, hi + 1.0) if np.isfinite(lo) and np.isfinite(hi) else (-1.0, 1.0)
            pad = 0.05 * (hi - lo) + 0.1
            return lo - pad, hi + pad

        y1_lo, y1_hi = margin(y1_lo, y1_hi)
        y2_lo, y2_hi = margin(y2_lo, y2_hi)

        self.ax1.set_ylim(y1_lo, y1_hi)
        self.ax2.set_ylim(y2_lo, y2_hi)

        # redraw
        self.fig.canvas.draw_idle()
        self.fig.canvas.flush_events()
        plt.pause(1.0 / PLOT_RATE_HZ)

def main(args=None):
    rclpy.init(args=args)
    node = DiffPlotter()
    try:
        # keep matplotlib responsive while spinning
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
