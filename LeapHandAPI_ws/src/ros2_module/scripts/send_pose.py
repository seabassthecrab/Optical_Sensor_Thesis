#!/usr/bin/env python3

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import JointState
import numpy as np
import time
import serial
import csv
import threading
from datetime import datetime

SERIAL_PORT = '/dev/ttyACM0'  # Adjust to your Arduino's port
BAUD_RATE = 115200
log_file = 'synchronized_joint_data.csv'

joint1_index = 0  # Index of 2.757
joint2_index = 4  # Index of 3.533
arduino_angle = None
real_joint_state = None


# Read Arduino data when PC sends "LOG\n"
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
    pose.header.stamp = rclpy.time.Time().to_msg()  # Optional
    return pose

def interpolate_and_send(pub, node, start_pose, end_pose, steps=20, delay=0.05):
    """
    Smoothly interpolate from start_pose to end_pose and send to the hand.
    """
    for alpha in np.linspace(0, 1, steps):
        pose_array = (1 - alpha) * start_pose + alpha * end_pose
        pose_msg = create_pose(pose_array)
        pub.publish(pose_msg)
        node.get_logger().info(f"Sending interpolated pose (alpha={alpha:.2f})")
        time.sleep(delay)


def log_data(current_pose, arduino_angle):
    joint1_rad = current_pose[joint1_index]
    joint2_rad = current_pose[joint2_index]
    leap_diff_rad = abs(joint1_rad - joint2_rad)

    joint1_deg = np.degrees(joint1_rad)
    joint2_deg = np.degrees(joint2_rad)
    leap_avg_deg = (joint1_deg + joint2_deg) / 2

    if arduino_angle is not None:
        angle_diff_deg = abs(leap_avg_deg - arduino_angle)
    else:
        angle_diff_deg = ""

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

def main():
    rclpy.init()
    node = Node('send_hand_poses')
    pub = node.create_publisher(JointState, '/cmd_leap', 10)
    def joint_state_callback(msg):
        global real_joint_state
        real_joint_state = msg.position  # tuple of joint positions


    time.sleep(1.0)  # Give ROS some time to set up

    # --- Define different poses ---

    open_hand = np.array([
        3.14, 3.14159, 3.14159, 3.14159,
        3.14, 0, 1.8, 3.14159,
        3.14, 0, 3.45, 3.14159,
        3.14, 4.7, 3.14159, 3.14159
    ])

    closed_fist = np.array([
        3.14, 4, 3.14159, 3.14159,
        3.14, 3.14, 1.8, 3.14159,
        3.14, 3.14, 3.45, 3.14159,
        3.14, 4.7, 3.14159, 3.14159
    ])

    peace_sign = np.array([
        3.14, 3.14159, 3.14159, 3.14159,
        3.14, 0, 1.8, 3.14159,
        3.14, 0, 3.45, 3.14159,
        3.14, 4.7, 3.14159, 3.14159
    ])

    peace_sign1 = np.array([
         2.757, 3.14, 3.14, 1.5,           
         3.533, 3.14, 3.14, 3.14159,   
         3.14, 3.7, 3.14, 3.14159, 
         4.21, 7.749, 3.14159, 3.14159
                
    ])

    closed_two_finger = np.array([
         3.24, 3.14, 3.14, 1.5,           
         3.12, 3.14, 3.14, 3.14159,   
         3.14, 3.7, 3.14, 3.14159, 
         4.21, 7.749, 3.14159, 3.14159
                
    ])

    #poses = [open_hand, closed_fist, peace_sign]
    
    poses =[closed_two_finger, peace_sign1]

    current_pose =closed_two_finger

    #current_pose = open_hand

   # while rclpy.ok():
   #     for next_pose in poses:
   #         interpolate_and_send(pub, node, current_pose, next_pose, steps=30, delay=0.03)
    #        current_pose = next_pose
   #         time.sleep(1.0)  # Pause at each pose



     # Initialize CSV
    with open(log_file, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp", "leap_joint1_rad", "leap_joint2_rad", "leap_diff_rad",
                         "arduino_angle_deg", "leap_avg_deg", "angle_difference_deg"])

    # Set up Arduino
    ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1)
    time.sleep(2)

    # Phase 1: Run poses once, 5s pause
    for next_pose in poses:
        interpolate_and_send(pub, node, current_pose, next_pose, steps=30, delay=0.03)
        current_pose = next_pose
        end_time = time.time() + 7.0
        while time.time() < end_time:
            angle = request_arduino_angle(ser)
            log_data(current_pose, angle)
            time.sleep(0.25)

    # Phase 2: Loop for 30 minutes at 1s per pose
    start_time = time.time()
    duration = 30 * 60
    log_interval = 0.25
    next_log_time = time.time()

    while rclpy.ok() and (time.time() - start_time < duration):
        for next_pose in poses:
            interpolate_and_send(pub, node, current_pose, next_pose, steps=30, delay=0.03)
            current_pose = next_pose
            end_time = time.time() + 1.0
            while time.time() < end_time:
                if time.time() >= next_log_time:
                    angle = request_arduino_angle(ser)
                    log_data(current_pose, angle)
                    next_log_time += log_interval
                time.sleep(0.01)

    node.destroy_node()
    rclpy.shutdown()

if __name__ == '__main__':
    main()