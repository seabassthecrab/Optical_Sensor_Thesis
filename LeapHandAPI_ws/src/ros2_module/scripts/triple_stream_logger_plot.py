#!/usr/bin/env python3
import threading, time, csv, math, collections, argparse
import numpy as np
import serial
import cv2
import mediapipe as mp
import matplotlib.pyplot as plt

# ----- ROS2 (LEAP encoders) -----
import rclpy
from rclpy.node import Node
from leap_hand.srv import LeapPosition

# ----- Config -----
SERIAL_PORT = '/dev/ttyACM0'
BAUD = 250000
CSV_PATH = 'triple_1khz_log.csv'
SAMPLE_HZ = 1000.0          # logging rate
PLOT_HZ = 30.0              # UI update
LEAP_QUERY_HZ = 100.0       # reasonable service rate (don’t try 1 kHz)
CAM_ID = 1                  # set to your Arducam index
CAM_W, CAM_H, CAM_FPS = 1280, 720, 30

# MCP-based angle: Index(5,8) Middle(9,12); use MCP->TIP vectors
IDX_MCP, IDX_TIP = 5, 8
MID_MCP, MID_TIP = 9, 12
JOINT_A, JOINT_B = 0, 4     # LEAP diff: Index MCP-Side (0), Middle MCP-Side (4)

# ----- Shared state -----
sensor_deg = float('nan')
leap_deg = float('nan')
arducam_deg = float('nan')
lock = threading.Lock()
running = True

def safe_set(name, val):
    global sensor_deg, leap_deg, arducam_deg
    with lock:
        if name == 'sensor': sensor_deg = val
        elif name == 'leap': leap_deg = val
        elif name == 'cam': arducam_deg = val

def safe_get_all():
    with lock:
        return sensor_deg, leap_deg, arducam_deg

# ----- Arduino reader (non-blocking loop) -----
def arduino_thread(port, baud):
    global running
    try:
        ser = serial.Serial(port, baud, timeout=0.01)
        time.sleep(2.0); ser.reset_input_buffer()
    except Exception as e:
        print(f"[Arduino] open failed: {e}")
        return
    while running:
        try:
            if ser.in_waiting:
                line = ser.readline().decode(errors='ignore').strip()
                if line.startswith('DATA'):
                    parts = line.split(',')
                    if len(parts) >= 3:
                        ang = float(parts[2])
                        safe_set('sensor', ang)
        except Exception:
            pass
        time.sleep(0.0005)  # ~2 kHz poll

# ----- MediaPipe camera angle (MCP-based) -----
mp_hands = mp.solutions.hands
def angle_between(v1, v2):
    a = np.linalg.norm(v1); b = np.linalg.norm(v2)
    if a == 0 or b == 0: return None
    c = np.clip(np.dot(v1, v2)/(a*b), -1.0, 1.0)
    return math.degrees(math.acos(c))

def cam_thread(cam_id):
    global running
    hands = mp_hands.Hands(static_image_mode=False, max_num_hands=1,
                           min_detection_confidence=0.6, min_tracking_confidence=0.6)
    cap = cv2.VideoCapture(cam_id, cv2.CAP_V4L2)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAM_W)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAM_H)
    cap.set(cv2.CAP_PROP_FPS, CAM_FPS)
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))

    while running:
        ok, frame = cap.read()
        if not ok:
            time.sleep(0.01); continue
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        res = hands.process(rgb)
        a_deg = float('nan')
        if res.multi_hand_landmarks:
            lm = res.multi_hand_landmarks[0].landmark
            def P(i): return np.array([lm[i].x*CAM_W, lm[i].y*CAM_H, lm[i].z*CAM_W], float)
            v_idx = P(IDX_TIP) - P(IDX_MCP)
            v_mid = P(MID_TIP) - P(MID_MCP)
            ang = angle_between(v_idx, v_mid)
            if ang is not None: a_deg = float(ang)
        safe_set('cam', a_deg)
        # no imshow here; plotting handled separately
    cap.release()

# ----- ROS2 client thread (LEAP encoders) -----
class LeapClient(Node):
    def __init__(self): super().__init__('leap_reader'); self.cli = self.create_client(LeapPosition, 'leap_position')
def leap_thread():
    global running
    rclpy.init()
    node = LeapClient()
    while running and not node.cli.wait_for_service(timeout_sec=0.5):
        print("[LEAP] waiting for leap_position...")
    last = time.time()
    period = 1.0/LEAP_QUERY_HZ
    while running and rclpy.ok():
        now = time.time()
        if now - last >= period:
            last = now
            try:
                req = LeapPosition.Request()
                fut = node.cli.call_async(req)
                rclpy.spin_until_future_complete(node, fut, timeout_sec=0.05)
                if fut.done() and fut.result() is not None:
                    pos = list(fut.result().position)
                    if pos and len(pos) >= max(JOINT_A, JOINT_B)+1:
                        val = math.degrees(pos[JOINT_B] - pos[JOINT_A])
                        safe_set('leap', float(val))
            except Exception:
                pass
        rclpy.spin_once(node, timeout_sec=0.0)
        time.sleep(0.001)
    node.destroy_node(); rclpy.shutdown()

# ----- Logger + realtime plots -----
def run_logger_and_plot():
    # CSV init
    f = open(CSV_PATH, 'w', newline='')
    w = csv.writer(f)
    w.writerow(['t_s','sensor_deg','leap_deg','arducam_deg','sensor_minus_arducam_deg'])

    # plotting buffers (last N seconds)
    win_s = 10.0
    max_pts = int(win_s * PLOT_HZ * 5)  # generous
    t_buf = collections.deque(maxlen=max_pts)
    sens_buf = collections.deque(maxlen=max_pts)
    leap_buf = collections.deque(maxlen=max_pts)
    cam_buf = collections.deque(maxlen=max_pts)
    diff_buf = collections.deque(maxlen=max_pts)

    # matplotlib live
    plt.ion()
    fig, (ax1, ax2) = plt.subplots(2,1, figsize=(10,7), sharex=True)
    l1, = ax1.plot([], [], label='sensor (deg)')
    l2, = ax1.plot([], [], label='leap (deg)')
    l3, = ax1.plot([], [], label='arducam (deg)')
    ax1.legend(); ax1.set_ylabel('deg'); ax1.set_title('Angles')
    l4, = ax2.plot([], [], label='sensor - arducam (deg)')
    ax2.legend(); ax2.set_xlabel('time (s)'); ax2.set_ylabel('deg')
    last_plot = time.time()

    # 1 kHz loop
    period = 1.0 / SAMPLE_HZ
    t0 = time.monotonic()
    try:
        while running:
            t = time.monotonic() - t0
            s, l, c = safe_get_all()
            diff = (s - c) if (not math.isnan(s) and not math.isnan(c)) else float('nan')
            # CSV row
            w.writerow([f"{t:.6f}",
                        ("" if math.isnan(s) else f"{s:.6f}"),
                        ("" if math.isnan(l) else f"{l:.6f}"),
                        ("" if math.isnan(c) else f"{c:.6f}"),
                        ("" if math.isnan(diff) else f"{diff:.6f}")])
            # plot buffers (decimate by time window, not every sample)
            now = time.time()
            if now - last_plot >= 1.0/PLOT_HZ:
                t_buf.append(t)
                sens_buf.append(np.nan if math.isnan(s) else s)
                leap_buf.append(np.nan if math.isnan(l) else l)
                cam_buf.append(np.nan if math.isnan(c) else c)
                diff_buf.append(np.nan if math.isnan(diff) else diff)

                l1.set_data(t_buf, sens_buf)
                l2.set_data(t_buf, leap_buf)
                l3.set_data(t_buf, cam_buf)
                ax1.relim(); ax1.autoscale_view()

                l4.set_data(t_buf, diff_buf)
                ax2.relim(); ax2.autoscale_view()

                plt.pause(0.001)
                last_plot = now

            # sleep to keep 1 kHz
            next_t = period - ((time.monotonic() - t0) - t)
            if next_t > 0: time.sleep(next_t)
    except KeyboardInterrupt:
        pass
    finally:
        f.close()
        plt.ioff(); plt.show()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--serial', default=SERIAL_PORT)
    ap.add_argument('--cam', type=int, default=CAM_ID)
    args = ap.parse_args()

    ta = threading.Thread(target=arduino_thread, args=(args.serial, BAUD), daemon=True)
    tc = threading.Thread(target=cam_thread, args=(args.cam,), daemon=True)
    tl = threading.Thread(target=leap_thread, daemon=True)

    ta.start(); tc.start(); tl.start()
    run_logger_and_plot()

if __name__ == '__main__':
    try:
        main()
    finally:
        running = False
