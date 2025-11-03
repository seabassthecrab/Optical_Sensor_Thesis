#!/usr/bin/env python3

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import JointState
from leap_hand.srv import LeapPosition

import numpy as np
import time
import serial
import csv
from datetime import datetime

# --- CONFIG ---
SERIAL_PORT = '/dev/ttyACM0'  # Update to match your Arduino port
BAUD_RATE = 250000
log_file = 'synchronized_joint_data.csv'

joint1_index = 0
joint2_index = 4

# --- HELPERS ---

def request_arduino_angle(ser):
    ser.write(b'LOG\n')
    start = time.time()
    while time.time() - start < 0.1:
        if ser.in_waiting:
            line = ser.readline().decode().strip()
            if line.startswith("DATA"):
                try:
                    _, raw, angle = line.split(',')
                    return float(angle)
                except:
                    return None
    return None

def create_pose(values):
    pose = JointState()
    pose.position = values.tolist()
    pose.header.stamp = rclpy.time.Time().to_msg()
    return pose

def interpolate_and_send(pub, node, start_pose, end_pose, cli, angle_getter, steps=30, delay=0.03):
    for alpha in np.linspace(0, 1, steps):
        pose_array = (1 - alpha) * start_pose + alpha * end_pose
        pose_msg = create_pose(pose_array)
        pub.publish(pose_msg)

        # Wait a bit to let the hand react
        time.sleep(delay)

        # Get actual feedback from hardware
        measured_pose = get_actual_leap_pose(node, cli)
        arduino_angle = angle_getter() if angle_getter else None

        # Log this commanded vs measured
        log_data(pose_array, measured_pose, arduino_angle)

def get_actual_leap_pose(node, cli):
    req = LeapPosition.Request()
    future = cli.call_async(req)
    rclpy.spin_until_future_complete(node, future)
    if future.result() is not None:
        return future.result().position
    else:
        node.get_logger().warn("Failed to read LEAP joint position")
        return [None] * 16

def log_data(commanded_pose, measured_pose, arduino_angle):
    joint1_rad = measured_pose[joint1_index] 
    joint2_rad = measured_pose[joint2_index] 

    if joint1_rad != "" and joint2_rad != "":
        leap_diff_rad = abs(joint1_rad - joint2_rad)
        joint1_deg = np.degrees(joint1_rad)
        joint2_deg = np.degrees(joint2_rad)
        leap_avg_deg = (joint1_deg + joint2_deg) / 2
        angle_diff_deg = abs(leap_avg_deg - arduino_angle) if arduino_angle is not None else ""
    else:
        leap_diff_rad = leap_avg_deg = angle_diff_deg = ""

    timestamp = datetime.now().isoformat()

    with open(log_file, 'a', newline='') as f:
        writer = csv.writer(f)
        writer.writerow([
            timestamp,
            joint1_rad, joint2_rad, leap_diff_rad,
            arduino_angle if arduino_angle is not None else "",
            leap_avg_deg,
            angle_diff_deg
        ])

# --- MAIN ---

def main():
    rclpy.init()
    node = Node('send_and_log_pose')
    pub = node.create_publisher(JointState, '/cmd_leap', 10)

    cli = node.create_client(LeapPosition, 'leap_position')
    while not cli.wait_for_service(timeout_sec=2.0):
        node.get_logger().info('Waiting for leap_position service...')

    time.sleep(1.0)

    # --- Define poses ---

    closed_two_finger = np.array([
        3.24, 3.14, 3.14, 1.5,
        3.12, 3.14, 3.14, 3.14159,
        3.14, 3.7, 3.14, 3.14159,
        4.21, 7.749, 3.14159, 3.14159
    ])

    peace_sign1 = np.array([
        2.757, 3.14, 3.14, 1.5,
        3.533, 3.14, 3.14, 3.14159,
        3.14, 3.7, 3.14, 3.14159,
        4.21, 7.749, 3.14159, 3.14159
    ])

    poses = [closed_two_finger, peace_sign1]
    current_pose = closed_two_finger

    # --- Initialize CSV file ---
    with open(log_file, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow([
            "timestamp", "leap_joint1_rad", "leap_joint2_rad", "leap_diff_rad",
            "arduino_angle_deg", "leap_avg_deg", "angle_difference_deg"
        ])

    # --- Set up Arduino ---
    ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1)
    time.sleep(2)

    # --- Phase 1: Run poses once with 7s pause ---
    for next_pose in poses:
        interpolate_and_send(pub, node, current_pose, next_pose, cli, lambda: request_arduino_angle(ser))

        current_pose = next_pose
        end_time = time.time() + 7.0
        while time.time() < end_time:
            angle = request_arduino_angle(ser)
            measured_pose = get_actual_leap_pose(node, cli)
            log_data(current_pose, measured_pose, angle)
            time.sleep(0.25)

    # --- Phase 2: Loop poses for 30 minutes at 1s per pose ---
    start_time = time.time()
    duration = 30 * 60  # 30 minutes
    log_interval = 0.01
    next_log_time = time.time()

    while rclpy.ok() and (time.time() - start_time < duration):
        for next_pose in poses:
            interpolate_and_send(pub, node, current_pose, next_pose, cli, lambda: request_arduino_angle(ser))

            current_pose = next_pose
            end_time = time.time() + 1.0
            while time.time() < end_time:
                if time.time() >= next_log_time:
                    angle = request_arduino_angle(ser)
                    measured_pose = get_actual_leap_pose(node, cli)
                    log_data(current_pose, measured_pose, angle)
                    next_log_time += log_interval
                time.sleep(0.001)

    node.destroy_node()
    rclpy.shutdown()

if __name__ == '__main__':
    main()
