#!/usr/bin/env python3
import os
# pick an interactive backend before pyplot import
try:
    import matplotlib
    if os.environ.get("MPLBACKEND", "").lower() not in ("tkagg","qt5agg","qtagg"):
        matplotlib.use("TkAgg")
except Exception:
    pass

import rclpy
from rclpy.node import Node
from std_msgs.msg import Float32MultiArray

import matplotlib.pyplot as plt
import numpy as np
from collections import deque
import time
import math

TOPIC            = '/sensor_vs_encoder'
WINDOW_SEC       = 6.0     # correlation window
PLOT_RATE_HZ     = 20.0
FS_RESAMPLE_HZ   = 300.0   # resample to uniform grid
MAX_LAG_MS       = 300.0   # only consider hardware delays 0..MAX_LAG_MS
MIN_VARIANCE_DEG = 0.3     # need enough motion in window (deg RMS) to estimate
SMOOTH_N         = 7       # median over last N lag estimates

class DelayPlotter(Node):
    def __init__(self):
        super().__init__('sensor_encoder_delay_plotter')
        self.sub = self.create_subscription(Float32MultiArray, TOPIC, self.cb, 50)

        self.t0 = time.time()
        self.t = deque()
        self.raw = deque()
        self.filt = deque()
        self.enc = deque()

        self.lag_hist_ms = deque(maxlen=SMOOTH_N)
        self.msg_count = 0
        self.last_rate_print = time.time()

        self.create_timer(1.0 / PLOT_RATE_HZ, self.update_plot)

        # figure
        plt.ion()
        self.fig, (self.ax1, self.ax2) = plt.subplots(2, 1, figsize=(10,6), sharex=True)
        self.l_raw,  = self.ax1.plot([], [], label='Sensor RAW (deg)', alpha=0.4)
        self.l_filt, = self.ax1.plot([], [], label='Sensor FILT (deg)')
        self.l_enc,  = self.ax1.plot([], [], label='Encoder (deg)')
        self.ax1.legend(loc='upper left')
        self.ax1.set_ylabel('deg')
        self.ax1.set_title('Sensor vs Encoder')

        self.text = self.ax1.text(0.01, 0.98, '', transform=self.ax1.transAxes, va='top')

        self.ax2.set_ylabel('deg/s (detrended)')
        self.ax2.set_xlabel('time (s)')
        self.l_dr,  = self.ax2.plot([], [], label='d/dt sensor', alpha=0.6)
        self.l_de,  = self.ax2.plot([], [], label='d/dt encoder', alpha=0.6)
        self.ax2.legend(loc='upper left')

        self.fig.tight_layout()

    def cb(self, msg: Float32MultiArray):
        now = time.time() - self.t0
        data = list(msg.data)

        # Accept either [raw, filt, enc] or [filt, enc]
        if len(data) >= 3:
            raw, filt, enc = data[0], data[1], data[2]
        elif len(data) == 2:
            raw = float('nan')
            filt, enc = data
        else:
            return

        self.t.append(now)
        self.raw.append(float(raw))
        self.filt.append(float(filt))
        self.enc.append(float(enc))

        # prune window
        while self.t and (now - self.t[0] > WINDOW_SEC):
            self.t.popleft(); self.raw.popleft(); self.filt.popleft(); self.enc.popleft()

        # rx rate debug
        self.msg_count += 1
        if now - self.last_rate_print > 2.0:
            rate = self.msg_count / (now - self.last_rate_print)
            self.get_logger().info(f"{TOPIC} ~{rate:.1f} msg/s")
            self.msg_count = 0
            self.last_rate_print = now

    # ----- helpers -----
    @staticmethod
    def _uniform_resample(x_t, y, fs_hz):
        """Resample (t,y) to uniform grid at fs_hz. Returns grid_t, y_i."""
        if len(x_t) < 4:
            return None, None
        t0, t1 = x_t[0], x_t[-1]
        if t1 - t0 < 0.02:
            return None, None
        n = int((t1 - t0) * fs_hz) + 1
        grid = np.linspace(t0, t1, n)
        y_i = np.interp(grid, x_t, y)
        return grid, y_i

    @staticmethod
    def _diff_highpass(y_i, fs_hz):
        """Simple high-pass via first difference (approx derivative)."""
        dt = 1.0 / fs_hz
        dy = np.gradient(y_i, dt)
        # remove mean to avoid zero-lag bias
        dy -= np.mean(dy)
        # unit energy for PHAT stability
        std = np.std(dy)
        if std < 1e-6:
            return None
        return dy / std

    @staticmethod
    def _gcc_phat(sig, ref, fs_hz, max_lag_ms):
        """
        GCC-PHAT of sig vs ref (both same length).
        Returns (lag_seconds, quality) with lag >= 0 and <= max_lag.
        """
        n = len(sig)
        if n < 8: return None, None

        # FFT size: next power of two
        N = 1 << (n*2 - 1).bit_length()
        SIG = np.fft.rfft(sig, n=N)
        REF = np.fft.rfft(ref, n=N)

        cps = SIG * np.conj(REF)
        mag = np.abs(cps)
        cps /= (mag + 1e-12)  # PHAT

        corr = np.fft.irfft(cps, n=N)
        # make it "full" by rolling so that zero lag is at index 0
        corr = np.concatenate((corr[-(n-1):], corr[:n]))

        # build lag array for that "full" view
        lags = np.arange(-(n-1), n) / fs_hz

        # restrict to plausible hardware lag: [0, max_lag]
        max_lag = max_lag_ms / 1000.0
        mask = (lags >= 0.0) & (lags <= max_lag)
        if not np.any(mask):
            return None, None

        c = corr[mask]
        L = lags[mask]

        # pick peak and a crude quality (z-score of the peak)
        idx = int(np.argmax(c))
        peak = c[idx]
        mu = np.mean(c)
        sd = np.std(c) + 1e-12
        quality = (peak - mu) / sd

        lag = float(L[idx])
        return lag, quality

    def _estimate_delay_ms(self, t, s_in, e_in):
        """Robust delay estimate using derivative + GCC-PHAT, bounded to [0, MAX_LAG_MS]."""
        if len(t) < 8:
            return None

        # choose the "sensor" to use: prefer RAW if available
        s = np.array(s_in, dtype=float)
        e = np.array(e_in, dtype=float)

        # need enough finite data and motion
        m_s = np.isfinite(s)
        m_e = np.isfinite(e)
        if np.sum(m_s) < 10 or np.sum(m_e) < 10:
            return None

        # resample each on same uniform grid
        grid_s, s_i = self._uniform_resample(np.array(t)[m_s], s[m_s], FS_RESAMPLE_HZ)
        grid_e, e_i = self._uniform_resample(np.array(t)[m_e], e[m_e], FS_RESAMPLE_HZ)
        if s_i is None or e_i is None:
            return None

        # re-interp encoder onto sensor grid (shortest common window)
        t0 = max(grid_s[0], grid_e[0])
        t1 = min(grid_s[-1], grid_e[-1])
        if t1 - t0 < 0.2:
            return None
        n = int((t1 - t0) * FS_RESAMPLE_HZ) + 1
        grid = np.linspace(t0, t1, n)
        s_u = np.interp(grid, grid_s, s_i)
        e_u = np.interp(grid, grid_e, e_i)

        # require some variance (deg RMS) to avoid random estimates
        if np.std(s_u) < MIN_VARIANCE_DEG or np.std(e_u) < MIN_VARIANCE_DEG:
            return None

        # high-pass via derivative, normalize
        s_hp = self._diff_highpass(s_u, FS_RESAMPLE_HZ)
        e_hp = self._diff_highpass(e_u, FS_RESAMPLE_HZ)
        if s_hp is None or e_hp is None:
            return None

        lag_s, quality = self._gcc_phat(s_hp, e_hp, FS_RESAMPLE_HZ, MAX_LAG_MS)
        if lag_s is None or quality is None:
            return None

        # require decent peak prominence
        if quality < 3.0:
            return None

        return lag_s * 1000.0  # ms

    def update_plot(self):
        if not self.t:
            return

        x = np.asarray(self.t, dtype=float)
        raw = np.asarray(self.raw, dtype=float)
        fil = np.asarray(self.filt, dtype=float)
        enc = np.asarray(self.enc, dtype=float)

        # draw lines (mask NaNs)
        def maskline(axline, x, y):
            m = np.isfinite(y)
            axline.set_data(x[m], y[m])

        maskline(self.l_raw,  x, raw)
        maskline(self.l_filt, x, fil)
        maskline(self.l_enc,  x, enc)

        # d/dt preview on bottom axes
        def dd_dt(x, y):
            m = np.isfinite(y)
            if np.sum(m) < 5: return None, None
            yy = y[m]; xx = x[m]
            dy = np.gradient(yy, np.gradient(xx))
            return xx, dy

        xs, ds = dd_dt(x, fil if np.any(np.isfinite(raw)) is False else raw)
        xe, de = dd_dt(x, enc)
        if xs is not None and xe is not None:
            self.l_dr.set_data(xs, ds - np.nanmean(ds))
            self.l_de.set_data(xe, de - np.nanmean(de))

        # axes limits
        xmin = max(0.0, x[-1] - WINDOW_SEC)
        xmax = x[-1] if x[-1] > xmin else xmin + 1.0
        for ax in (self.ax1, self.ax2):
            ax.set_xlim(xmin, xmax)
        # y autoscale
        def ylims(vals):
            vals = np.concatenate([v[np.isfinite(v)] for v in vals if v is not None])
            if vals.size == 0: return (-1, 1)
            lo, hi = np.min(vals), np.max(vals)
            if lo == hi: lo -= 1.0; hi += 1.0
            pad = 0.05 * (hi - lo) + 0.1
            return lo - pad, hi + pad

        y1_lo, y1_hi = ylims([raw, fil, enc])
        self.ax1.set_ylim(y1_lo, y1_hi)

        if xs is not None and xe is not None:
            y2_lo, y2_hi = ylims([ds, de])
            self.ax2.set_ylim(y2_lo, y2_hi)

        # delay estimate (prefer RAW if present)
        sens = raw if np.any(np.isfinite(raw)) else fil
        lag_ms = self._estimate_delay_ms(x, sens, enc)
        if lag_ms is not None:
            self.lag_hist_ms.append(lag_ms)

        if self.lag_hist_ms:
            med = float(np.median(self.lag_hist_ms))
            self.text.set_text(f"Estimated hardware delay (median {SMOOTH_N}): {med:6.1f} ms")
        else:
            self.text.set_text("Estimating hardware delay...")

        # draw
        self.fig.canvas.draw_idle()
        self.fig.canvas.flush_events()
        plt.pause(1.0 / PLOT_RATE_HZ)

def main(args=None):
    rclpy.init(args=args)
    node = DelayPlotter()
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
