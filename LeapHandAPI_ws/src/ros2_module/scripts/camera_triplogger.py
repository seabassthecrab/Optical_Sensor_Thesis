#!/usr/bin/env python3
# camera_triplogger.py  (live view in separate window + overlayed finger lines)
#
# Subscribes: /sensor_vs_encoder = [sensor_raw, sensor_filt, encoder_deg]
# Computes:   Arducam MCP-based index–middle angle (MCP→TIP vectors)
# Logs @ 1 kHz CSV; shows live plots and a separate camera window (optional recording)
#
# Example:
#   python3 camera_triplogger.py --cam 1 --csv triple_1khz_log.csv --show \
#       --record out.mp4 --record-fps 30 --width 1280 --height 720

import argparse, threading, time, csv, math, collections, os
import numpy as np

# ---- choose a non-Qt backend BEFORE importing pyplot ----
import matplotlib
try:
    matplotlib.use('TkAgg')      # live GUI without Qt
except Exception:
    matplotlib.use('Agg')        # headless fallback
import matplotlib.pyplot as plt

import cv2, mediapipe as mp
import rclpy
from rclpy.node import Node
from std_msgs.msg import Float32MultiArray

# ---------------- Config ----------------
DEFAULT_TOPIC = '/sensor_vs_encoder'
DEFAULT_CSV = 'triple_1khz_log.csv'
SAMPLE_HZ = 1000.0
PLOT_HZ = 1000.0
USE_FILTERED_SENSOR = True

CAM_W, CAM_H, CAM_FPS = 1280, 720, 30
IDX_MCP, IDX_TIP = 5, 8
MID_MCP, MID_TIP = 9, 12

# ---------------- Shared state ----------------
lock = threading.Lock()
sensor_raw_deg  = float('nan')
sensor_filt_deg = float('nan')
leap_deg        = float('nan')
arducam_deg     = float('nan')
latest_frame    = None
running         = True

def set_shared(name, val):
    global sensor_raw_deg, sensor_filt_deg, leap_deg, arducam_deg
    with lock:
        if name == 'sensor_raw':   sensor_raw_deg = val
        elif name == 'sensor_filt': sensor_filt_deg = val
        elif name == 'leap':       leap_deg = val
        elif name == 'cam':        arducam_deg = val

def get_shared_all():
    with lock:
        return sensor_raw_deg, sensor_filt_deg, leap_deg, arducam_deg

def set_latest_frame(frame):
    global latest_frame
    with lock:
        latest_frame = frame

def get_latest_frame():
    with lock:
        return None if latest_frame is None else latest_frame.copy()

# ---------------- ROS2 subscriber ----------------
class TripLoggerNode(Node):
    def __init__(self, topic):
        super().__init__('camera_triplogger')
        self.sub = self.create_subscription(Float32MultiArray, topic, self.cb, 10)
    def cb(self, msg: Float32MultiArray):
        if len(msg.data) >= 3:
            sr, sf, enc = msg.data[0], msg.data[1], msg.data[2]
            set_shared('sensor_raw',  float(sr))
            set_shared('sensor_filt', float(sf))
            set_shared('leap',        float(enc))

# ---------------- Camera + MediaPipe ----------------
mp_hands = mp.solutions.hands

def angle_between(v1, v2):
    a = np.linalg.norm(v1); b = np.linalg.norm(v2)
    if a == 0 or b == 0: return None
    c = np.clip(np.dot(v1, v2)/(a*b), -1.0, 1.0)
    return math.degrees(math.acos(c))

def draw_overlay(frame, a_deg, fps_est, pts_idx, pts_mid):
    """Draw finger lines + overlay text onto frame (in camera thread)."""
    sr, sf, enc, cam = get_shared_all()
    sens = sf if USE_FILTERED_SENSOR else sr
    diff = (sens - cam) if (not math.isnan(sens) and not math.isnan(cam)) else float('nan')

    # Finger lines
    if pts_idx and pts_mid:
        cv2.line(frame, pts_idx[0], pts_idx[1], (0,255,0), 2)   # index
        cv2.line(frame, pts_mid[0], pts_mid[1], (255,0,0), 2)   # middle
        if not math.isnan(a_deg):
            midpt = ((pts_idx[1][0]+pts_mid[1][0])//2, (pts_idx[1][1]+pts_mid[1][1])//2)
            cv2.putText(frame, f"{a_deg:.1f}°", midpt, cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0,255,255), 2)

    # Text overlay
    y = 30; h = 22
    def put(text, yoff, col=(0,255,255)):
        cv2.putText(frame, text, (10, y+yoff), cv2.FONT_HERSHEY_SIMPLEX, 0.6, col, 2, cv2.LINE_AA)
    put(f"Sensor:  {sens:.1f}°" if not math.isnan(sens) else "Sensor:  n/a", 0, (0,255,0))
    put(f"LEAP:    {enc:.1f}°"  if not math.isnan(enc)  else "LEAP:    n/a", h, (255,255,0))
    put(f"Arducam: {cam:.1f}°"  if not math.isnan(cam)  else "Arducam: n/a", 2*h, (0,255,255))
    put(f"Diff(S-C): {diff:.1f}°" if not math.isnan(diff) else "Diff(S-C): n/a", 3*h, (255,255,255))
    put(f"FPS: {fps_est:.1f}", 4*h, (200,200,200))

def cam_thread(cam_id, width, height, fps, record_path, record_fps):
    """Camera runs here; no GUI calls in this thread."""
    global running
    hands = mp_hands.Hands(static_image_mode=False, max_num_hands=1,
                           min_detection_confidence=0.6, min_tracking_confidence=0.6)
    cap = cv2.VideoCapture(cam_id, cv2.CAP_V4L2)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH,  width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    cap.set(cv2.CAP_PROP_FPS,          fps)
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))

    writer = None
    if record_path:
        # choose FOURCC from extension
        ext = os.path.splitext(record_path)[1].lower()
        if ext == '.mp4':
            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        else:
            fourcc = cv2.VideoWriter_fourcc(*'MJPG')
        writer = cv2.VideoWriter(record_path, fourcc, record_fps, (width, height))

    t_last = time.time(); fps_est = 0.0
    while running:
        ok, frame = cap.read()
        if not ok:
            time.sleep(0.01); continue
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        res = hands.process(rgb)

        a_deg = float('nan')
        pts_idx = pts_mid = None
        if res.multi_hand_landmarks:
            lm = res.multi_hand_landmarks[0].landmark
            def P(i): return np.array([lm[i].x*width, lm[i].y*height, lm[i].z*width], float)
            v_idx = P(IDX_TIP) - P(IDX_MCP)
            v_mid = P(MID_TIP) - P(MID_MCP)
            ang = angle_between(v_idx, v_mid)
            if ang is not None: a_deg = float(ang)
            pts_idx = ((int(lm[IDX_MCP].x*width), int(lm[IDX_MCP].y*height)),
                       (int(lm[IDX_TIP].x*width), int(lm[IDX_TIP].y*height)))
            pts_mid = ((int(lm[MID_MCP].x*width), int(lm[MID_MCP].y*height)),
                       (int(lm[MID_TIP].x*width), int(lm[MID_TIP].y*height)))
        set_shared('cam', a_deg)

        # overlay + export frame to main thread
        now = time.time(); dt = now - t_last; t_last = now
        if dt > 0: fps_est = 0.9*fps_est + 0.1*(1.0/dt)
        draw_overlay(frame, a_deg, fps_est, pts_idx, pts_mid)
        set_latest_frame(frame)

        if writer is not None:
            writer.write(frame)

    if writer is not None: writer.release()
    cap.release()

# ---------------- Logger + plots + separate camera window ----------------
def run_logger_and_plot(csv_path, show=False, cam_window=True):
    f = open(csv_path, 'w', newline='')
    w = csv.writer(f)
    w.writerow(['t_s','sensor_deg','leap_deg','arducam_deg','sensor_minus_arducam_deg'])

    win_s = 10.0
    max_pts = int(win_s * PLOT_HZ * 5)
    t_buf, sens_buf, leap_buf, cam_buf, diff_buf = [collections.deque(maxlen=max_pts) for _ in range(5)]

    plt.ion()
    fig, (ax1, ax2) = plt.subplots(2,1, figsize=(10,7), sharex=True)
    l1, = ax1.plot([], [], label='sensor (deg)')
    l2, = ax1.plot([], [], label='leap (deg)')
    l3, = ax1.plot([], [], label='arducam (deg)')
    ax1.legend(); ax1.set_ylabel('deg'); ax1.set_title('Angles')
    l4, = ax2.plot([], [], label='sensor - arducam (deg)')
    ax2.legend(); ax2.set_xlabel('time (s)'); ax2.set_ylabel('deg')

    # Separate camera window
    cam_im = None
    if show and cam_window:
        cam_fig, cam_ax = plt.subplots(1,1, num="Arducam view", figsize=(9,5))
        cam_ax.axis('off')
        cam_im = cam_ax.imshow(np.zeros((10,10,3), dtype=np.uint8))

    last_plot = time.time()
    period = 1.0 / SAMPLE_HZ
    t0 = time.monotonic()

    try:
        while running:
            t = time.monotonic() - t0
            sr, sf, l, c = get_shared_all()
            s = sf if USE_FILTERED_SENSOR else sr
            diff = (s - c) if (not math.isnan(s) and not math.isnan(c)) else float('nan')

            w.writerow([
                f"{t:.6f}",
                ("" if math.isnan(s) else f"{s:.6f}"),
                ("" if math.isnan(l) else f"{l:.6f}"),
                ("" if math.isnan(c) else f"{c:.6f}"),
                ("" if math.isnan(diff) else f"{diff:.6f}")
            ])

            now = time.time()
            if now - last_plot >= 1.0/PLOT_HZ:
                t_buf.append(t)
                sens_buf.append(np.nan if math.isnan(s) else s)
                leap_buf.append(np.nan if math.isnan(l) else l)
                cam_buf.append(np.nan  if math.isnan(c) else c)
                diff_buf.append(np.nan if math.isnan(diff) else diff)

                l1.set_data(t_buf, sens_buf); l2.set_data(t_buf, leap_buf); l3.set_data(t_buf, cam_buf)
                ax1.relim(); ax1.autoscale_view()
                l4.set_data(t_buf, diff_buf)
                ax2.relim(); ax2.autoscale_view()

                # update camera window
                if show and cam_im is not None:
                    frm = get_latest_frame()
                    if frm is not None:
                        cam_im.set_data(cv2.cvtColor(frm, cv2.COLOR_BGR2RGB))

                plt.pause(0.001)
                last_plot = now

            next_t = period - ((time.monotonic() - t0) - t)
            if next_t > 0: time.sleep(next_t)
    except KeyboardInterrupt:
        pass
    finally:
        f.close()
        plt.ioff(); plt.show()

# ---------------- Main ----------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--topic', default=DEFAULT_TOPIC)
    ap.add_argument('--csv',   default=DEFAULT_CSV)
    ap.add_argument('--cam',   type=int, default=0)
    ap.add_argument('--width', type=int, default=CAM_W)
    ap.add_argument('--height',type=int, default=CAM_H)
    ap.add_argument('--fps',   type=int, default=CAM_FPS)
    ap.add_argument('--show',  action='store_true', help="show live plots + camera window")
    ap.add_argument('--record', default='', help='Save camera feed (e.g., out.mp4 or out.avi)')
    ap.add_argument('--record-fps', type=int, default=30)
    args = ap.parse_args()

    # Camera producer thread (no GUI here)
    t_cam = threading.Thread(target=cam_thread,
        args=(args.cam, args.width, args.height, args.fps, args.record, args.record_fps),
        daemon=True)
    t_cam.start()

    # ROS2 node + tiny spin thread
    rclpy.init()
    node = TripLoggerNode(args.topic)
    def _spin():
        while running:
            rclpy.spin_once(node, timeout_sec=0.05)
    threading.Thread(target=_spin, daemon=True).start()

    try:
        run_logger_and_plot(args.csv, show=args.show, cam_window=True)
    except KeyboardInterrupt:
        pass
    finally:
        global running
        running = False
        node.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    main()
