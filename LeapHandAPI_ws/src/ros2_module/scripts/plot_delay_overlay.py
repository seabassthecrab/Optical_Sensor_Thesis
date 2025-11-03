#!/usr/bin/env python3
import argparse
import csv
from typing import List, Dict, Optional

import matplotlib.pyplot as plt


def _to_float(s: str) -> Optional[float]:
    try:
        return float(s)
    except:
        return None


def load_signals(path: str):
    """
    signals_stream.csv columns:
      iso_time, mono_time_s, sensor_raw_deg, sensor_filt_deg, cmd_diff_deg, enc_diff_deg
    """
    t, sens_raw, sens_filt, cmd, enc = [], [], [], [], []
    with open(path, "r", newline="") as f:
        r = csv.DictReader(f)
        for row in r:
            t.append(_to_float(row["mono_time_s"]))
            sens_raw.append(_to_float(row["sensor_raw_deg"]))
            sens_filt.append(_to_float(row["sensor_filt_deg"]))
            cmd.append(_to_float(row["cmd_diff_deg"]))
            enc.append(_to_float(row["enc_diff_deg"]))
    return {"t": t, "sensor_raw": sens_raw, "sensor_filt": sens_filt, "cmd": cmd, "enc": enc}


def load_events(path: str):
    """
    delay_events.csv columns:
      iso_time, mono_time_s, step_dir, sensor_at_step_deg, target_cmd_deg,
      t_sensor_step_s, t_cmd_sent_s, t_motion_start_s, t_encoder_reach_s,
      sensor_to_cmd_ms, cmd_to_start_ms, sensor_to_start_ms, cmd_to_reach_ms, sensor_to_reach_ms
    """
    events = []
    with open(path, "r", newline="") as f:
        r = csv.DictReader(f)
        for row in r:
            e = {k: row.get(k, "") for k in row.keys()}
            # parse floats
            keys_f = [
                "mono_time_s",
                "t_sensor_step_s", "t_cmd_sent_s", "t_motion_start_s", "t_encoder_reach_s",
                "sensor_at_step_deg", "target_cmd_deg",
                "sensor_to_cmd_ms", "cmd_to_start_ms", "sensor_to_start_ms",
                "cmd_to_reach_ms", "sensor_to_reach_ms",
            ]
            for k in keys_f:
                e[k] = _to_float(e.get(k, ""))
            try:
                e["step_dir"] = int(e.get("step_dir", 0))
            except:
                e["step_dir"] = 0
            events.append(e)
    return events


def subset_by_time(sig: Dict[str, List[Optional[float]]], events: List[Dict], tmin: Optional[float], tmax: Optional[float]):
    if tmin is None and tmax is None:
        return sig, events

    # subset signals
    idx = []
    for i, ti in enumerate(sig["t"]):
        if ti is None: 
            continue
        if (tmin is None or ti >= tmin) and (tmax is None or ti <= tmax):
            idx.append(i)

    def pick(arr):
        return [arr[i] for i in idx]

    sig_sub = {
        "t": pick(sig["t"]),
        "sensor_raw": pick(sig["sensor_raw"]),
        "sensor_filt": pick(sig["sensor_filt"]),
        "cmd": pick(sig["cmd"]),
        "enc": pick(sig["enc"]),
    }

    # subset events by their reference time (mono_time_s or t_cmd_sent_s)
    ev_sub = []
    for e in events:
        tref = e.get("mono_time_s")
        # prefer using t_cmd_sent_s if available for plotting on delay axis
        if e.get("t_cmd_sent_s") is not None:
            tref = e["t_cmd_sent_s"]
        if tref is None:
            continue
        if (tmin is None or tref >= tmin) and (tmax is None or tref <= tmax):
            ev_sub.append(e)

    return sig_sub, ev_sub


def normalize_time(sig: Dict[str, List[Optional[float]]], events: List[Dict], t0: Optional[float]):
    """Shift all times so t0 becomes 0."""
    if t0 is None:
        # first available signal time
        t0 = next((x for x in sig["t"] if x is not None), 0.0)

    def shift(v):
        return None if v is None else v - t0

    sig_norm = sig.copy()
    sig_norm["t"] = [shift(x) for x in sig["t"]]

    for e in events:
        for key in ["mono_time_s", "t_sensor_step_s", "t_cmd_sent_s", "t_motion_start_s", "t_encoder_reach_s"]:
            if e.get(key) is not None:
                e[key] = shift(e[key])

    return sig_norm, events


def compute_avg_cmd_to_start(events: List[Dict]) -> Optional[float]:
    vals = [e["cmd_to_start_ms"] for e in events if e.get("cmd_to_start_ms") is not None]
    vals = [v for v in vals if v is not None]
    if not vals:
        return None
    return sum(vals) / len(vals)


def plot_overlay(sig: Dict[str, List[Optional[float]]], events: List[Dict], shade_windows: bool, title: str):
    t = sig["t"]
    fig, (ax_sig, ax_delay) = plt.subplots(2, 1, figsize=(11, 8), sharex=True,
                                           gridspec_kw={"height_ratios": [3, 1]})

    # --- Signals subplot ---
    ax_sig.plot(t, sig["sensor_raw"], label="sensor raw (deg)", linewidth=1.0)
    ax_sig.plot(t, sig["sensor_filt"], label="sensor filtered (deg)", linewidth=1.8)
    ax_sig.plot(t, sig["cmd"], label="commanded diff (deg)", linewidth=1.8)
    ax_sig.plot(t, sig["enc"], label="encoder diff (deg)", linewidth=1.8)

    # Event lines & shading
    for e in events:
        ts = e.get("t_sensor_step_s")
        tc = e.get("t_cmd_sent_s")
        tm = e.get("t_motion_start_s")
        tr = e.get("t_encoder_reach_s")

        if ts is not None: ax_sig.axvline(ts, linestyle="--", linewidth=1.0, alpha=0.8, label="sensor step")
        if tc is not None: ax_sig.axvline(tc, linestyle="-.", linewidth=1.0, alpha=0.8, label="cmd sent")
        if tm is not None: ax_sig.axvline(tm, linestyle=":",  linewidth=1.0, alpha=0.8, label="motion start")
        if tr is not None: ax_sig.axvline(tr, linestyle="-",  linewidth=1.0, alpha=0.8, label="reach")

        if shade_windows and tc is not None:
            if tm is not None and tm >= tc:
                ax_sig.axvspan(tc, tm, alpha=0.12, label="cmd→start")
            if tr is not None and tr >= tc:
                ax_sig.axvspan(tc, tr, alpha=0.08, label="cmd→reach")

    ax_sig.set_ylabel("degrees")
    ax_sig.set_title(title)
    ax_sig.grid(True, linestyle=":", alpha=0.4)
    # dedupe legend
    handles, labels = ax_sig.get_legend_handles_labels()
    seen, h2, l2 = set(), [], []
    for h, l in zip(handles, labels):
        if l not in seen:
            h2.append(h); l2.append(l); seen.add(l)
    ax_sig.legend(h2, l2, loc="best", ncol=2)

    # --- Delay subplot: cmd→start per event + average line ---
    xs, ys = [], []
    for e in events:
        x = e.get("t_cmd_sent_s")
        y = e.get("cmd_to_start_ms")
        if x is not None and y is not None:
            xs.append(x); ys.append(y)

    if xs:
        ax_delay.scatter(xs, ys, s=18, label="cmd→start delay (ms)")
        avg = compute_avg_cmd_to_start(events)
        if avg is not None:
            ax_delay.axhline(avg, linestyle="--", linewidth=2.0, label=f"avg: {avg:.1f} ms")
            ax_delay.text(xs[0], avg, f"  avg {avg:.1f} ms", va="center")

    ax_delay.set_xlabel("time (s)")
    ax_delay.set_ylabel("ms")
    ax_delay.grid(True, linestyle=":", alpha=0.4)
    if xs:
        ax_delay.legend(loc="best")

    plt.tight_layout()
    plt.show()


def main():
    ap = argparse.ArgumentParser(description="Overlay sensor/command/encoder with cmd→start delay plot + average line.")
    ap.add_argument("--signals", default="signals_stream.csv", help="Path to signals_stream.csv")
    ap.add_argument("--events",  default="delay_events.csv",   help="Path to delay_events.csv")
    ap.add_argument("--tmin", type=float, default=None, help="Min time (s) to plot")
    ap.add_argument("--tmax", type=float, default=None, help="Max time (s) to plot")
    ap.add_argument("--normalize", action="store_true", help="Normalize time to start at 0")
    ap.add_argument("--shade", action="store_true", help="Shade cmd→start & cmd→reach windows")
    args = ap.parse_args()

    sig = load_signals(args.signals)
    ev  = load_events(args.events)

    # Optional time window
    sig, ev = subset_by_time(sig, ev, args.tmin, args.tmax)

    # Optional normalization
    if args.normalize:
        # normalize to first available signal time in the (possibly subselected) data
        t0 = next((x for x in sig["t"] if x is not None), 0.0)
        sig, ev = normalize_time(sig, ev, t0)

    plot_overlay(sig, ev, shade_windows=args.shade, title="Signals + Events (with cmd→start delay avg)")

if __name__ == "__main__":
    main()
