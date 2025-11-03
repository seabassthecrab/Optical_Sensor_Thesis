#!/usr/bin/env python3
# pip install opencv-python mediapipe numpy
import cv2, math, csv, time
import mediapipe as mp
import numpy as np

# --- settings ---
CAM_ID = 4                  # your Arducam device index
WIDTH, HEIGHT = 1280, 720   # set to your camera mode
LOG_CSV = "finger_angle.csv"
SHOW_ANGLE_HISTORY = True   # draw small plot in the corner

mp_hands = mp.solutions.hands
hands = mp_hands.Hands(
    static_image_mode=False,
    max_num_hands=1,
    min_detection_confidence=0.6,
    min_tracking_confidence=0.6
)
mp_draw = mp.solutions.drawing_utils

# MediaPipe landmark indices:
# Index:  MCP=5,  PIP=6,  TIP=8
# Middle: MCP=9,  PIP=10, TIP=12

def angle_between(v1, v2):
    a = np.linalg.norm(v1); b = np.linalg.norm(v2)
    if a == 0 or b == 0: return None
    cosang = np.clip(np.dot(v1, v2)/(a*b), -1.0, 1.0)
    return math.degrees(math.acos(cosang))

def compute_spread_angle(lm, img_w, img_h, use_pip=False):
    """
    MCP-based spread:
      - if use_pip=False: vectors MCP->TIP (more range)
      - if use_pip=True : vectors MCP->PIP (stiffer, less jitter)
    Returns (angle_deg, draw_points)
    """
    def p(i):
        return np.array([lm[i].x*img_w, lm[i].y*img_h, lm[i].z*img_w], dtype=float)

    # Bases
    idx_mcp = p(5)
    mid_mcp = p(9)

    if use_pip:
        idx_target = p(6)   # index PIP
        mid_target = p(10)  # middle PIP
    else:
        idx_target = p(8)   # index TIP
        mid_target = p(12)  # middle TIP

    v_idx = idx_target - idx_mcp
    v_mid = mid_target - mid_mcp

    ang = angle_between(v_idx, v_mid)

    # points to draw: (base->target) for each finger
    draw_pts = (tuple(idx_mcp[:2].astype(int)), tuple(idx_target[:2].astype(int)),
                tuple(mid_mcp[:2].astype(int)), tuple(mid_target[:2].astype(int)))
    return ang, draw_pts

def draw_history(frame, history, maxlen=200):
    if not history: return
    h, w = frame.shape[:2]
    plot_w, plot_h = 260, 120
    x0, y0 = 20, 20
    cv2.rectangle(frame, (x0, y0), (x0+plot_w, y0+plot_h), (20,20,20), -1)
    vals = history[-maxlen:]
    if len(vals) < 2: return
    vmin = max(0, min(vals)-5); vmax = max(vals)+5
    vmax = max(vmax, vmin+1)
    pts = []
    for i, v in enumerate(vals):
        px = x0 + int(i*(plot_w-10)/(len(vals)-1)) + 5
        py = y0 + int((1-(v-vmin)/(vmax-vmin))*(plot_h-10)) + 5
        pts.append((px, py))
    cv2.polylines(frame, [np.array(pts,np.int32)], False, (255,255,255), 1)
    cv2.putText(frame, f"{vals[-1]:.1f} deg", (x0+10, y0+20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255,255,255), 1)

def main():
    cap = cv2.VideoCapture(CAM_ID)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, HEIGHT)
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))  # often helps on UVC cams

    csvf = open(LOG_CSV, "w", newline="")
    writer = csv.writer(csvf); writer.writerow(["time_s","angle_deg"])

    angle_hist = []
    t0 = time.time()

    while True:
        ok, frame = cap.read()
        if not ok: break
        img_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        res = hands.process(img_rgb)

        angle_deg = None
        if res.multi_hand_landmarks:
            lm = res.multi_hand_landmarks[0].landmark
            angle_deg, pts = compute_spread_angle(lm, frame.shape[1], frame.shape[0])

            # draw landmarks and vectors
            angle_deg, pts = compute_spread_angle(lm, frame.shape[1], frame.shape[0], use_pip=False)
            if angle_deg is not None:
                idx_base, idx_tip, mid_base, mid_tip = pts
                cv2.line(frame, idx_base, idx_tip, (0,255,0), 2)
                cv2.line(frame, mid_base, mid_tip, (0,255,0), 2)
                cv2.putText(frame, f"MCP-based spread: {angle_deg:.1f} deg",
                        (30, frame.shape[0]-30), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0,255,255), 2)

        # log + history
        ts = time.time() - t0
        if angle_deg is not None:
            writer.writerow([f"{ts:.3f}", f"{angle_deg:.3f}"])
            angle_hist.append(angle_deg)

        if SHOW_ANGLE_HISTORY:
            draw_history(frame, angle_hist)

        cv2.imshow("Arducam Finger Angle (index vs middle)", frame)
        if cv2.waitKey(1) & 0xFF == 27:  # ESC to quit
            break

    csvf.close()
    cap.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()
