import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch_ros.actions import Node

def generate_launch_description():
    return LaunchDescription([
        Node(
            package='leap_hand',
            executable='leaphand_node.py',
            name='leaphand_node',
            emulate_tty=True,
            output='screen',
            parameters=[{
                'kP': 700.0,
                'kI': 0.0,
                'kD': 1000.0,
                'curr_lim': 500.0,
                'startup_pose': [
                    2.757, 3.14, 3.14, 1.5,             # Index
                    3.533, 3.14, 3.14, 3.14159,     # Middle
                    3.14, 3.7, 3.14, 3.14159, # Ring
                    4.21, 4.609, 3.14159, 3.14159 # Thumb
                
                ]
            }]
        ),

#closed two fingers pose

                    #3.2398, 3.14, 3.14, 1.5,             # Index
                    #3.1169, 3.14, 3.14, 3.14159,     # Middle
                    #3.14, 3.7, 3.14, 3.14159, # Ring
                    #4.21, 7.749, 3.14159, 3.14159 # Thumb
                

        #Node(
        #    package='leap_hand',
        #    executable='ros2_example.py',
        #    name='ros2_example',
        #    emulate_tty=True,
        #    output='screen'
        #)
 

    ])
