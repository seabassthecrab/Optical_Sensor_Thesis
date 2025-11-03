# 🖐️ Real-Time MCP Finger Joint Angle Tracking with a Novel Optical Sensor

This project demonstrates a **real-time MCP finger joint angle tracking system** using a **custom optical bend sensor** and validation through a **Leap Hand** and **Arducam 4K camera**.  
It integrates **ROS 2**, **Python**, **MediaPipe**, and **Arduino** firmware to measure, filter, and compare angular motion across multiple sensing modalities.

---

## 🧩 System Overview

| Component | Description |
|------------|--------------|
| **Teensy 4.0** | Runs firmware to read optical sensor voltage, map to angle, and stream via serial. |
| **Leap Hand** | Robot hand controlled over ROS 2; receives joint commands and returns joint encoder feedback. |
| **Arducam (4K)** | Captures real-time finger pose and estimates angle between MCP joints using MediaPipe. |
| **Host PC (ROS 2 + Python)** | Runs ROS 2 nodes for command, feedback, logging, plotting, and camera visualization. |

---

## 🧱 Dependencies

### 1. System Requirements
- Ubuntu 22.04 LTS (recommended)
- ROS 2 Humble or newer
- Python 3.10+
- Teensyduino + Arduino IDE

### 2. Python Packages

Make sure your ROS 2 workspace (e.g., `~/LeapHandAPI_ws`) has an isolated environment:
```bash
cd ~/LeapHandAPI_ws/src/ros2_module/scripts
python3 -m venv mp-env
source mp-env/bin/activate
pip install --upgrade pip
pip install rclpy opencv-python mediapipe matplotlib numpy pyserial
```

Optional (for performance and plotting GUI fixes):
```bash
sudo apt install python3-pyqt5 python3-tk
```

---

## 🔧 Setup & Installation

1. **Build ROS 2 packages:**
   ```bash
   cd ~/LeapHandAPI_ws
   colcon build --symlink-install
   ```

2. **Source your ROS 2 workspace:**
   ```bash
   source /opt/ros/humble/setup.bash
   source ~/LeapHandAPI_ws/install/setup.bash
   ```

3. **Connect your hardware:**
   - Plug in the Teensy 4.0 (flashed with `arduino_angle_stream.ino`)
   - Ensure the Leap Hand is powered and connected via USB/serial
   - Connect the Arducam (USB)

---

## 🚀 Launch Sequence

### **Step 1: Start the Leap Hand ROS 2 Driver**
This initializes the hand’s control nodes and the `/leap_position` service:
```bash
ros2 launch leap_hand launch_leap.py
```

> 💡 Wait until you see the log message confirming that the hand’s services are active before continuing.

---

### **Step 2: Start the Arduino Sensor Interface**
Run the main control and logger node that:
- Reads serial data from the Teensy
- Filters via Median + One Euro filter
- Commands Leap Hand finger motion
- Logs both continuous and event data to CSV

```bash
cd ~/LeapHandAPI_ws/src/ros2_module/scripts
source mp-env/bin/activate
python3 arduino_diff_to_leap_logger.py
```

It will create:
- `signals_stream.csv` — continuous data (sensor, filtered, commanded, encoder)
- `delay_events.csv` — event-based delays (sensor→command, command→motion start, etc.)

---

### **Step 3: Run the Camera Logger + Plotter**
This node synchronizes data streams at 1 kHz, computes camera-based MCP angles, and displays real-time plots with optional video recording.

```bash
python3 camera_triplogger.py --topic /sensor_vs_encoder --cam 1 --show --record out.avi --record-fps 30
```

**Common arguments:**
| Flag | Description |
|------|--------------|
| `--cam N` | Select camera index (try 0 or 1 depending on your USB device). |
| `--show` | Opens a live window with finger overlays and real-time angles. |
| `--record <filename>` | Save camera feed with overlay. |
| `--record-fps <int>` | Set desired recording frame rate (try 30). |
| `--csv <filename>` | Save synchronized data logs (default `triple_1khz_log.csv`). |

> ⚠️ If OpenCV gives a Qt plugin error, switch to a **non-Qt backend**:
> ```bash
> export QT_QPA_PLATFORM=offscreen
> python3 camera_triplogger.py --show ...
> ```

---

## 📊 Output Files

| File | Description |
|------|--------------|
| **signals_stream.csv** | Continuous sensor, command, and encoder angles. |
| **delay_events.csv** | Hardware delay metrics (sensor→cmd, cmd→motion start, etc.). |
| **triple_1khz_log.csv** | Combined sensor + Leap + Arducam synchronized at 1 kHz. |
| **out.avi** | Optional recorded camera feed with MediaPipe overlays. |

---

## 🧠 Notes & Tips

- To ensure real-time performance, close unnecessary background apps.
- If the Arducam runs below 30 FPS, reduce the resolution or use `MJPG` compression.
- The live plotting uses **Matplotlib** with `Qt5Agg`; if you run headless, disable plotting via `--no-show`.
- Make sure to `source ~/LeapHandAPI_ws/install/setup.bash` in every new terminal running a ROS 2 node.

---

## 📘 Example Full Run

```bash
# Terminal 1: Launch Leap Hand
ros2 launch leap_hand launch_leap.py

# Terminal 2: Run Arduino + Leap interface
cd ~/LeapHandAPI_ws/src/ros2_module/scripts
source mp-env/bin/activate
python3 arduino_diff_to_leap_logger.py

# Terminal 3: Run Arducam logger + plots
source mp-env/bin/activate
python3 camera_triplogger.py --topic /sensor_vs_encoder --cam 1 --show --record out.avi --record-fps 30
```
