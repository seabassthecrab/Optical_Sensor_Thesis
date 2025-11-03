#!/usr/bin/env python3

import rospy
from sensor_msgs.msg import JointState
import numpy as np
import time

def create_pose(values):
    pose = JointState()
    pose.position = values
    #pose.name = [f'joint_{i}' for i in range(16)]  # Optional, some systems need names
    pose.header.stamp = rospy.Time.now()
    return pose

def interpolate_and_send(pub, start_pose, end_pose, steps=20, delay=0.05):
    """
    Smoothly interpolate from start_pose to end_pose and send to the hand.
    """
    for alpha in np.linspace(0, 1, steps):
        pose_array = (1 - alpha) * start_pose + alpha * end_pose
        pose_msg = create_pose(pose_array)
        pub.publish(pose_msg)
        rospy.sleep(delay)

def main():
    rospy.init_node('send_hand_poses', anonymous=True)
    pub = rospy.Publisher('/leaphand_node/cmd_leap', JointState, queue_size=10)
    
    rospy.sleep(1)  # Give ROS some time to set up

    # --- Define different poses ---
    
    # Open hand (flat)
    open_hand = np.array([3.14, 3.14159, 3.14159, 3.14159,   # Index finger (MCP Side, MCP Forward, PIP, DIP)
                           3.14, 0, 1.8, 3.14159,   # Middle finger
                           3.14, 0, 3.45, 3.14159,   # Ring finger
                           3.14, 4.7, 3.14159, 3.14159])   # Thumb

    # Closed fist
    closed_fist = np.array([3.14, 4, 3.14159, 3.14159,   # Index finger (MCP Side, MCP Forward, PIP, DIP)
                           3.14, 3.14, 1.8, 3.14159,   # Middle finger
                           3.14, 3.14, 3.45, 3.14159,   # Ring finger
                           3.14, 4.7, 3.14159, 3.14159])   # Thumb

    # Peace sign ✌️ (Index and Middle open, rest closed)
    peace_sign = np.array([3.14, 3.14159, 3.14159, 3.14159,   # Index finger (MCP Side, MCP Forward, PIP, DIP)
                           3.14, 0, 1.8, 3.14159,   # Middle finger
                           3.14, 0, 3.45, 3.14159,   # Ring finger
                           3.14, 4.7, 3.14159, 3.14159])   # Thumb
    

    # Moving poses ()



    poses = [open_hand] #, closed_fist, peace_sign]

    # --- Publish poses one by one ---
    rate = rospy.Rate(0.5)  # 0.5 Hz => one pose every 2 seconds

    while not rospy.is_shutdown():
        for pose_array in poses:
            pose_msg = create_pose(pose_array)
            pub.publish(pose_msg)
            rospy.loginfo("Published a new hand pose")
            rate.sleep()

if __name__ == '__main__':
    try:
        main()
    except rospy.ROSInterruptException:
        pass

