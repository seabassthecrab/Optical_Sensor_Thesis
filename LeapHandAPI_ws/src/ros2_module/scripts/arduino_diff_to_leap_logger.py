#!/usr/bin/env python3
# arduino_diff_to_leap_logger.py
#
# Control:
# - Reads Arduino "DATA,<raw>,<angle_deg>"
# - Median + One-Euro filter on sensor angle
# - Keeps (joint_B - joint_A) == filtered angle (0..45°) via symmetric split
# - Linspace mini-trajectory; per-joint slew & deadband for smoothness
# - Publishes /cmd_leap, requests /leap_position asynchronously
#
# Logging:
# - Continuous CSV: iso_time, mono_time, sensor_raw_deg, sensor_filt_deg, cmd_diff_deg, enc_diff_deg
# - Events CSV (per step): times of sensor step, cmd sent, motion start, reach + all derived delays (ms)
# - Publishes /sensor_vs_encoder: [sensor_raw_deg, sensor_filt_deg, encoder_deg] for plotting

import rclpy
from rclpy.node import Node
from rclpy.executors import MultiThreadedExecutor
from sensor_msgs.msg import JointState
from std_msgs.msg import Float32MultiArray
from leap_hand.srv import LeapPosition

import serial
import time
import math
import csv
import os
from datetime import datetime
import numpy as np
from collections import deque

# -----------------------
# CONFIG
# -----------------------
SERIAL_PORT       = '/dev/ttyACM0'
BAUD_RATE         = 250000
READ_TIMEOUT      = 0.01

CMD_TOPIC         = '/cmd_leap'
POSE_SERVICE_NAME = '/leap_position'
DIFF_TOPIC        = '/ab_diff'
TRACE_TOPIC       = '/sensor_vs_encoder'

# LEAP indexing: Index(0-3), Middle(4-7), Ring(8-11), Thumb(12-15)
JOINT_A = 0   # Index MCP-Side
JOINT_B = 4   # Middle MCP-Side

# Base pose (radians)
BASE_POSE = np.array([
    3.24, 3.14, 3.14, 1.5,        # Index
    3.12, 3.14, 3.14, 3.14159,    # Middle
    3.14, 3.7,  3.14, 3.14159,    # Ring
    4.21, 3.749,3.14159,3.14159   # Thumb
], dtype=float)

# Mapping & safety
MAX_DIFF_DEG      = 45.0
ANGLE_SCALE       = 1.0
ANGLE_OFFSET_DEG  = 0.0

# Sensor filtering (median + One-Euro)
ANGLE_MEDIAN_WINDOW = 5
OEURO_MIN_CUTOFF    = 2.0
OEURO_BETA          = 0.04
OEURO_DCUTOFF       = 1.0
SERIAL_STALE_SEC    = 0.15

# Midpoint behavior
ADAPTIVE_MID      = False

# Rates
PUBLISH_RATE_HZ   = 100.0
LOG_RATE_HZ       = 5.0
SERIAL_POLL_HZ    = 500.0
MEAS_RATE_HZ      = 50.0    # async measured pose (<= ~90 Hz)
TRACE_PUB_RATE_HZ = 50.0

# Joint limits
LOWER = 0.0
UPPER = 2.0 * math.pi

# Target diff smoothing
MAX_DIFF_DEG_RATE   = 420.0
MIN_DIFF_STEP_DEG   = 0.1

# Interpolation buffer
INTERP_STEPS_MIN     = 3
INTERP_STEPS_MAX     = 30
INTERP_STEP_SIZE_RAD = 0.12
TARGET_REGEN_THRESH  = 0.03

# Per-joint motion shaping
MAX_JOINT_SPEED_RAD_S = 15.0
MIN_JOINT_STEP_RAD    = 0.001

# Motion-onset detection (encoder)
ENC_VEL_START_DEG_S   = 20.0   # threshold velocity to consider "started moving"
ENC_VEL_DEBOUNCE_MS   = 20.0   # must exceed threshold for this long
ENC_DIR_ENFORCE       = True   # require movement is toward target

# Reach detection
ENC_TOL_DEG     = 1.0   # within ± tol of target
HOLD_MS         = 60.0  # must stay inside tol for this long

# Event trigger
THRESH_STEP_DEG = 5.0   # sensor filtered step threshold
MAX_EVENT_WIN_S = 1.0   # max window to wait encoder to reach

# CSV paths
CSV_CONTINUOUS = 'signals_stream.csv'
CSV_EVENTS     = 'delay_events.csv'

def clamp(v, lo=LOWER, hi=UPPER):
    return float(max(lo, min(hi, v)))

class OneEuro:
    def __init__(self, min_cutoff=1.0, beta=0.0, d_cutoff=1.0):
        self.min_cutoff = float(min_cutoff)
        self.beta = float(beta)
        self.d_cutoff = float(d_cutoff)
        self._x_prev = None
        self._dx_prev = 0.0
        self._t_prev = None
    def _alpha(self, cutoff, dt):
        tau = 1.0 / (2.0 * math.pi * cutoff)
        return 1.0 / (1.0 + tau / dt)
    def filter(self, t, x):
        if self._t_prev is None:
            self._t_prev, self._x_prev = t, float(x)
            return float(x)
        dt = max(1e-3, t - self._t_prev)
        dx = (x - self._x_prev) / dt
        a_d = self._alpha(self.d_cutoff, dt)
        dx_hat = a_d * dx + (1 - a_d) * self._dx_prev
        cutoff = self.min_cutoff + self.beta * abs(dx_hat)
        a = self._alpha(cutoff, dt)
        x_hat = a * x + (1 - a) * self._x_prev
        self._t_prev, self._x_prev, self._dx_prev = t, x_hat, dx_hat
        return x_hat

class ArduinoDiffToLeapLogger(Node):
    def __init__(self):
        super().__init__('arduino_diff_to_leap_logger')

        # Publishers
        self.pub_cmd   = self.create_publisher(JointState, CMD_TOPIC, 10)
        self.pub_diff  = self.create_publisher(Float32MultiArray, DIFF_TOPIC, 10)
        self.pub_trace = self.create_publisher(Float32MultiArray, TRACE_TOPIC, 10)

        # Service client
        self.cli = self.create_client(LeapPosition, POSE_SERVICE_NAME)
        while not self.cli.wait_for_service(timeout_sec=2.0):
            self.get_logger().info(f'Waiting for {POSE_SERVICE_NAME} service...')

        # Serial
        try:
            self.ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=READ_TIMEOUT)
            time.sleep(2.0)
            self.ser.reset_input_buffer()
            self.get_logger().info(f"Opened serial {SERIAL_PORT} @ {BAUD_RATE}")
        except Exception as e:
            self.get_logger().error(f"Serial open failed: {e}")
            raise

        # State
        self.filtered_angle_deg = None
        self.last_raw_angle_deg = float('nan')
        self.last_cmd = BASE_POSE.copy()
        self.fixed_mid = 0.5 * (BASE_POSE[JOINT_A] + BASE_POSE[JOINT_B])
        self.prev_cmd_diff_deg = 0.0
        self.last_publish_sec = self.get_clock().now().nanoseconds * 1e-9
        self.last_measured_pose = [None]*16

        # Interpolator
        self.current_cmd = BASE_POSE.copy()
        self.target_cmd  = BASE_POSE.copy()
        self.traj_buf    = []

        # Sensor filtering
        self.angle_window = deque(maxlen=ANGLE_MEDIAN_WINDOW)
        self.oneeuro = OneEuro(OEURO_MIN_CUTOFF, OEURO_BETA, OEURO_DCUTOFF)
        self.last_sensor_time = time.time()

        # ---- CSVs ----
        self._stream_csv = open(CSV_CONTINUOUS, 'w', newline='')
        self._stream_w   = csv.writer(self._stream_csv)
        self._stream_w.writerow([
            'iso_time', 'mono_time_s',
            'sensor_raw_deg', 'sensor_filt_deg',
            'cmd_diff_deg', 'enc_diff_deg'
        ])

        self._events_csv = open(CSV_EVENTS, 'w', newline='')
        self._events_w   = csv.writer(self._events_csv)
        self._events_w.writerow([
            'iso_time', 'mono_time_s',
            'step_dir',
            'sensor_at_step_deg', 'target_cmd_deg',
            't_sensor_step_s', 't_cmd_sent_s', 't_motion_start_s', 't_encoder_reach_s',
            'sensor_to_cmd_ms', 'cmd_to_start_ms', 'sensor_to_start_ms',
            'cmd_to_reach_ms', 'sensor_to_reach_ms'
        ])

        # ---- Event state machine ----
        self._event_state = 'idle'
        self._last_event_sensor_deg = None
        self._step_dir = 0  # +1/-1

        self._t_sensor_step = None
        self._t_cmd_sent    = None
        self._t_motion_start = None
        self._t_encoder_reach = None
        self._target_cmd_deg = None

        self._hold_start = None

        # motion-onset helpers
        self._enc_last_diff = None
        self._enc_last_time = None
        self._enc_above_vel_since = None

        # Timers
        self.create_timer(1.0 / SERIAL_POLL_HZ,    self._poll_serial)
        self.create_timer(1.0 / PUBLISH_RATE_HZ,   self._publish_command)
        self.create_timer(1.0 / LOG_RATE_HZ,       self._log_console_and_abdiff)
        self.create_timer(1.0 / MEAS_RATE_HZ,      self._request_measured_pose)
        self.create_timer(1.0 / TRACE_PUB_RATE_HZ, self._publish_trace_and_detect)

    # --------- Serial polling ---------
    def _poll_serial(self):
        try:
            while self.ser.in_waiting:
                line = self.ser.readline().decode(errors='ignore').strip()
                if not line.startswith('DATA'):
                    continue
                parts = line.split(',')
                if len(parts) < 3:
                    continue
                try:
                    angle_deg = float(parts[2])
                except ValueError:
                    continue

                angle_deg = ANGLE_SCALE * angle_deg + ANGLE_OFFSET_DEG
                angle_deg = max(0.0, min(MAX_DIFF_DEG, angle_deg))

                self.last_raw_angle_deg = float(angle_deg)

                self.angle_window.append(angle_deg)
                med = sorted(self.angle_window)[len(self.angle_window)//2]
                t_now = time.time()
                filt = self.oneeuro.filter(t_now, med)

                self.filtered_angle_deg = float(filt)
                self.last_sensor_time = t_now

        except Exception as e:
            self.get_logger().warn(f"Serial read error: {e}")
            try: self.ser.reset_input_buffer()
            except Exception: pass

    # --------- Build target pose from desired diff (deg) ---------
    def _build_target_from_diff(self, desired_diff_deg: float) -> np.ndarray:
        desired_diff_deg = max(0.0, min(MAX_DIFF_DEG, desired_diff_deg))
        diff_rad = math.radians(desired_diff_deg)
        if ADAPTIVE_MID:
            mid = 0.5 * (self.current_cmd[JOINT_A] + self.current_cmd[JOINT_B])
        else:
            mid = self.fixed_mid
        a = clamp(mid - 0.5 * diff_rad)
        b = clamp(mid + 0.5 * diff_rad)
        tgt = self.current_cmd.copy()
        tgt[JOINT_A] = a
        tgt[JOINT_B] = b
        return tgt

    # --------- Update target & trajectory ---------
    def _maybe_update_target_and_traj(self, now_sec: float):
        if (time.time() - self.last_sensor_time) > SERIAL_STALE_SEC:
            return
        if self.filtered_angle_deg is None:
            return

        dt = max(1e-3, now_sec - self.last_publish_sec)
        desired = float(self.filtered_angle_deg)

        # deadband + slew
        if abs(desired - self.prev_cmd_diff_deg) < MIN_DIFF_STEP_DEG:
            desired = self.prev_cmd_diff_deg
        max_step = MAX_DIFF_DEG_RATE * dt
        delta    = desired - self.prev_cmd_diff_deg
        desired  = self.prev_cmd_diff_deg + max(-max_step, min(max_step, delta))
        desired  = max(0.0, min(MAX_DIFF_DEG, desired))
        self.prev_cmd_diff_deg = desired

        new_target = self._build_target_from_diff(desired)
        dist = float(np.linalg.norm(new_target - self.target_cmd)) if len(self.traj_buf) else float('inf')
        if dist > TARGET_REGEN_THRESH:
            self.target_cmd = new_target
            steps = max(
                INTERP_STEPS_MIN,
                min(INTERP_STEPS_MAX,
                    int(max(2, np.linalg.norm(self.target_cmd - self.current_cmd) / INTERP_STEP_SIZE_RAD)))
            )
            self.traj_buf = [
                (1.0 - alpha) * self.current_cmd + alpha * self.target_cmd
                for alpha in np.linspace(0.0, 1.0, steps, endpoint=True)
            ]

    # --------- Publish commanded pose ---------
    def _publish_command(self):
        now_sec = self.get_clock().now().nanoseconds * 1e-9
        mono = time.monotonic()

        # If a step event is armed but we haven't stamped cmd_sent yet, stamp it now
        if self._event_state == 'waiting_encoder' and self._t_cmd_sent is None:
            # we are about to send commands for this step; mark "cmd sent" time
            self._t_cmd_sent = mono

        self._maybe_update_target_and_traj(now_sec)

        candidate = self.traj_buf.pop(0) if self.traj_buf else self.current_cmd
        dt = max(1e-3, now_sec - self.last_publish_sec)
        max_step = MAX_JOINT_SPEED_RAD_S * dt
        step = np.clip(candidate - self.current_cmd, -max_step, max_step)
        step[np.abs(step) < MIN_JOINT_STEP_RAD] = 0.0
        self.current_cmd = self.current_cmd + step

        self.last_cmd = self.current_cmd.copy()
        msg = JointState()
        msg.position = self.current_cmd.tolist()
        msg.header.stamp = self.get_clock().now().to_msg()
        self.pub_cmd.publish(msg)

        self.last_publish_sec = now_sec

    # --------- Measured pose request (non-blocking) ---------
    def _request_measured_pose(self):
        req = LeapPosition.Request()
        future = self.cli.call_async(req)
        future.add_done_callback(self._pose_future_cb)

    def _pose_future_cb(self, future):
        try:
            res = future.result()
            if res is not None:
                self.last_measured_pose = list(res.position)
        except Exception:
            pass

    # --------- Motion/Reach detection + stream CSV + trace topic ---------
    def _publish_trace_and_detect(self):
        iso = datetime.now().isoformat()
        mono = time.monotonic()

        # sensor
        sens_raw  = self.last_raw_angle_deg
        sens_filt = self.filtered_angle_deg if self.filtered_angle_deg is not None else float('nan')

        # command diff
        cmd_diff_deg = math.degrees(self.last_cmd[JOINT_B] - self.last_cmd[JOINT_A])

        # encoder diff + velocity (deg/s)
        a = self.last_measured_pose[JOINT_A]
        b = self.last_measured_pose[JOINT_B]
        enc_diff_deg = math.degrees(b - a) if (a is not None and b is not None) else float('nan')

        enc_vel = 0.0
        if self._enc_last_diff is not None and self._enc_last_time is not None and not math.isnan(enc_diff_deg):
            dt = max(1e-3, mono - self._enc_last_time)
            enc_vel = (enc_diff_deg - self._enc_last_diff) / dt
        self._enc_last_diff = enc_diff_deg if not math.isnan(enc_diff_deg) else self._enc_last_diff
        self._enc_last_time = mono

        # publish trace
        msg = Float32MultiArray()
        msg.data = [float(sens_raw), float(sens_filt), float(enc_diff_deg)]
        self.pub_trace.publish(msg)

        # continuous CSV
        self._stream_w.writerow([iso, f"{mono:.6f}", sens_raw, sens_filt, cmd_diff_deg, enc_diff_deg])

        # ---- Event state machine ----
        # Trigger on filtered sensor step
        if not math.isnan(sens_filt):
            if self._event_state == 'idle':
                if self._last_event_sensor_deg is None:
                    self._last_event_sensor_deg = sens_filt
                delta = sens_filt - self._last_event_sensor_deg
                if abs(delta) >= THRESH_STEP_DEG:
                    # Start new event
                    self._event_state = 'waiting_encoder'
                    self._t_sensor_step = mono
                    self._t_cmd_sent    = None         # will be set in _publish_command
                    self._t_motion_start = None
                    self._t_encoder_reach = None
                    self._target_cmd_deg = float(self.prev_cmd_diff_deg)  # where we're heading
                    self._hold_start = None
                    self._step_dir = 1 if delta > 0 else -1
                    self._last_event_sensor_deg = sens_filt

            elif self._event_state == 'waiting_encoder':
                # timeout?
                if mono - self._t_sensor_step > MAX_EVENT_WIN_S:
                    # give up & reset
                    self._reset_event_state()
                    return

                # Motion-start detection (requires cmd_sent and measured encoder)
                if self._t_cmd_sent is not None and not math.isnan(enc_diff_deg) and self._target_cmd_deg is not None:
                    toward = (self._target_cmd_deg - enc_diff_deg)
                    # require correct direction if enabled
                    dir_ok = (not ENC_DIR_ENFORCE) or (np.sign(toward) == np.sign(enc_vel) and abs(toward) > 0.2)
                    if dir_ok and abs(enc_vel) >= ENC_VEL_START_DEG_S:
                        # debounce
                        if self._enc_above_vel_since is None:
                            self._enc_above_vel_since = mono
                        if (mono - self._enc_above_vel_since) * 1000.0 >= ENC_VEL_DEBOUNCE_MS:
                            if self._t_motion_start is None:
                                self._t_motion_start = mono
                    else:
                        self._enc_above_vel_since = None

                # Reach detection: inside tolerance & hold
                if not math.isnan(enc_diff_deg) and self._target_cmd_deg is not None:
                    if abs(enc_diff_deg - self._target_cmd_deg) <= ENC_TOL_DEG:
                        if self._hold_start is None:
                            self._hold_start = mono
                        if (mono - self._hold_start) * 1000.0 >= HOLD_MS:
                            self._t_encoder_reach = mono
                            # Log event (compute all delays)
                            self._log_event_row(iso)
                            # reset for next
                            self._reset_event_state()
                    else:
                        self._hold_start = None

    def _reset_event_state(self):
        self._event_state = 'idle'
        self._t_sensor_step = None
        self._t_cmd_sent = None
        self._t_motion_start = None
        self._t_encoder_reach = None
        self._target_cmd_deg = None
        self._hold_start = None
        self._enc_above_vel_since = None
        self._step_dir = 0

    def _log_event_row(self, iso):
        mono_now = time.monotonic()
        # unpack times
        t_s = self._t_sensor_step
        t_c = self._t_cmd_sent
        t_m = self._t_motion_start
        t_r = self._t_encoder_reach
        # compute delays (ms) if available
        sensor_to_cmd_ms   = (t_c - t_s) * 1000.0 if (t_s is not None and t_c is not None) else ''
        cmd_to_start_ms    = (t_m - t_c) * 1000.0 if (t_c is not None and t_m is not None) else ''
        sensor_to_start_ms = (t_m - t_s) * 1000.0 if (t_s is not None and t_m is not None) else ''
        cmd_to_reach_ms    = (t_r - t_c) * 1000.0 if (t_c is not None and t_r is not None) else ''
        sensor_to_reach_ms = (t_r - t_s) * 1000.0 if (t_s is not None and t_r is not None) else ''

        self._events_w.writerow([
            iso, f"{mono_now:.6f}",
            self._step_dir,
            f"{self._last_event_sensor_deg:.3f}" if self._last_event_sensor_deg is not None else '',
            f"{self._target_cmd_deg:.3f}" if self._target_cmd_deg is not None else '',
            f"{t_s:.6f}" if t_s is not None else '',
            f"{t_c:.6f}" if t_c is not None else '',
            f"{t_m:.6f}" if t_m is not None else '',
            f"{t_r:.6f}" if t_r is not None else '',
            f"{sensor_to_cmd_ms:.1f}"   if sensor_to_cmd_ms   != '' else '',
            f"{cmd_to_start_ms:.1f}"    if cmd_to_start_ms    != '' else '',
            f"{sensor_to_start_ms:.1f}" if sensor_to_start_ms != '' else '',
            f"{cmd_to_reach_ms:.1f}"    if cmd_to_reach_ms    != '' else '',
            f"{sensor_to_reach_ms:.1f}" if sensor_to_reach_ms != '' else '',
        ])

        # quick console summary
        if cmd_to_start_ms != '':
            self.get_logger().info(f"HW delay (cmd→start): {cmd_to_start_ms:.1f} ms")
        if cmd_to_reach_ms != '':
            self.get_logger().info(f"HW delay (cmd→reach): {cmd_to_reach_ms:.1f} ms")

    # --------- Console + /ab_diff for your other plotter ---------
    def _log_console_and_abdiff(self):
        cmd_list = self.last_cmd.tolist()
        a = self.last_measured_pose[JOINT_A]
        b = self.last_measured_pose[JOINT_B]
        cmd_diff_deg = math.degrees(cmd_list[JOINT_B] - cmd_list[JOINT_A])
        if a is not None and b is not None:
            act_diff_deg = math.degrees(b - a)
            err_deg = cmd_diff_deg - act_diff_deg
            sensor_disp = self.filtered_angle_deg if self.filtered_angle_deg is not None else float('nan')
            self.get_logger().info(
                f"AB diff  cmd:{cmd_diff_deg:6.2f}° | act:{act_diff_deg:6.2f}° | err:{err_deg:6.2f}° | sensor:{sensor_disp:6.2f}°"
            )
        else:
            act_diff_deg = float('nan'); err_deg = float('nan')
            sensor_disp = self.filtered_angle_deg if self.filtered_angle_deg is not None else float('nan')
            self.get_logger().info(
                f"AB diff  cmd:{cmd_diff_deg:6.2f}° | act:   n/a   | err:   n/a   | sensor:{sensor_disp:6.2f}°"
            )

        msg = Float32MultiArray()
        msg.data = [
            float(cmd_diff_deg),
            float(act_diff_deg) if not math.isnan(act_diff_deg) else float('nan'),
            float(err_deg) if not math.isnan(err_deg) else float('nan'),
        ]
        self.pub_diff.publish(msg)

    # --------- Cleanup ---------
    def destroy_node(self):
        try:
            self._stream_csv.close()
            self._events_csv.close()
            self.get_logger().info(
                f"Saved:\n  {os.path.abspath(CSV_CONTINUOUS)}\n  {os.path.abspath(CSV_EVENTS)}"
            )
        except Exception:
            pass
        super().destroy_node()

def main(args=None):
    rclpy.init(args=args)
    node = ArduinoDiffToLeapLogger()
    try:
        executor = MultiThreadedExecutor()
        executor.add_node(node)
        executor.spin()
    except KeyboardInterrupt:
        pass
    node.destroy_node()
    rclpy.shutdown()

if __name__ == '__main__':
    main()
