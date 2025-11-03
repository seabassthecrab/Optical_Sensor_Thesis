import csv
import matplotlib.pyplot as plt
import numpy as np

# Set IEEE-style plotting parameters
plt.rcParams['font.family'] = 'serif'
plt.rcParams['font.size'] = 10
plt.rcParams['axes.labelsize'] = 11
plt.rcParams['axes.titlesize'] = 12
plt.rcParams['legend.fontsize'] = 9
plt.rcParams['figure.dpi'] = 300

def load_csv_data(filename):
    """Load CSV data and return as dictionary of lists"""
    data = {
        't_s': [],
        'sensor_deg': [],
        'leap_deg': [],
        'arducam_deg': [],
        'sensor_minus_arducam_deg': []
    }
    
    with open(filename, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            data['t_s'].append(float(row['t_s']))
            data['sensor_deg'].append(float(row['sensor_deg']))
            data['leap_deg'].append(float(row['leap_deg']))
            data['arducam_deg'].append(float(row['arducam_deg']))
            data['sensor_minus_arducam_deg'].append(float(row['sensor_minus_arducam_deg']))
    
    return data

def plot_combined_sensors(data, title, filename, start_time=None):
    """Plot sensor, leap, and arducam data on same graph"""
    fig, ax = plt.subplots(figsize=(7, 4))
    
    t = np.array(data['t_s'])
    if start_time is None:
        start_time = t[0]
    
    # Normalize time to start at 0
    t_normalized = t - start_time
    
    ax.plot(t_normalized, data['sensor_deg'], label='Optical Sensor', 
            linewidth=1.2, color='#1f77b4', alpha=0.9)
    ax.plot(t_normalized, data['leap_deg'], label='LEAP Hand', 
            linewidth=1.2, color='#ff7f0e', alpha=0.9)
    ax.plot(t_normalized, data['arducam_deg'], label='Arducam', 
            linewidth=1.2, color='#2ca02c', alpha=0.9)
    
    ax.set_xlabel('Time (s)')
    ax.set_ylabel('Angle (degrees)')
    ax.set_title(title)
    ax.legend(loc='best', framealpha=0.9)
    ax.grid(True, alpha=0.3, linestyle='--', linewidth=0.5)
    
    # Set tight layout
    plt.tight_layout()
    plt.savefig(filename, bbox_inches='tight')
    print(f"Saved: {filename}")
    plt.close()

def plot_error(data, title, filename, start_time=None):
    """Plot sensor minus arducam error"""
    fig, ax = plt.subplots(figsize=(7, 4))
    
    t = np.array(data['t_s'])
    if start_time is None:
        start_time = t[0]
    
    # Normalize time to start at 0
    t_normalized = t - start_time
    error = np.array(data['sensor_minus_arducam_deg'])
    
    ax.plot(t_normalized, error, linewidth=1.0, color='#d62728', alpha=0.8)
    
    # Add reference lines at ±2 degrees
    ax.axhline(y=2, color='gray', linestyle='--', linewidth=0.8, alpha=0.6, label='±2° bounds')
    ax.axhline(y=-2, color='gray', linestyle='--', linewidth=0.8, alpha=0.6)
    ax.axhline(y=0, color='black', linestyle='-', linewidth=0.5, alpha=0.5)
    
    ax.set_xlabel('Time (s)')
    ax.set_ylabel('Measurement Error (degrees)')
    ax.set_title(title)
    ax.legend(loc='best', framealpha=0.9)
    ax.grid(True, alpha=0.3, linestyle='--', linewidth=0.5)
    
    # Calculate and display statistics
    mean_error = np.mean(error)
    std_error = np.std(error)
    textstr = f'μ = {mean_error:.3f}°\nσ = {std_error:.3f}°'
    props = dict(boxstyle='round', facecolor='wheat', alpha=0.5)
    ax.text(0.02, 0.98, textstr, transform=ax.transAxes, fontsize=9,
            verticalalignment='top', bbox=props)
    
    plt.tight_layout()
    plt.savefig(filename, bbox_inches='tight')
    print(f"Saved: {filename}")
    plt.close()

# File paths
adjusted_file = '/home/hikikomori/Project/Robotic_work/LeapHandAPI_ws/src/ros2_module/scripts/adjusted_arducam_data.csv'
extended_file = '/home/hikikomori/Project/Robotic_work/LeapHandAPI_ws/src/ros2_module/scripts/extended_arducam_data.csv'
output_dir = '/home/hikikomori/Project/Robotic_work/LeapHandAPI_ws/src/ros2_module/scripts/'

# Load data
print("Loading data...")
adjusted_data = load_csv_data(adjusted_file)
extended_data = load_csv_data(extended_file)

# Calculate durations
adjusted_duration = adjusted_data['t_s'][-1] - adjusted_data['t_s'][0]
extended_duration = extended_data['t_s'][-1] - extended_data['t_s'][0]

print(f"Adjusted data duration: {adjusted_duration:.1f} seconds")
print(f"Extended data duration: {extended_duration:.1f} seconds")

# Generate plots for adjusted data (~20 seconds)
print("\nGenerating plots for adjusted data...")
plot_combined_sensors(
    adjusted_data,
    'Multi-Sensor Angle Measurement Comparison',
    output_dir + 'adjusted_combined_sensors.png'
)

plot_error(
    adjusted_data,
    'Optical Sensor-Camera Measurement Error',
    output_dir + 'adjusted_error.png'
)

# Generate plots for extended data (~5 minutes)
print("\nGenerating plots for extended data...")
plot_combined_sensors(
    extended_data,
    'Multi-Sensor Angle Measurement Comparison (Extended)',
    output_dir + 'extended_combined_sensors.png'
)

plot_error(
    extended_data,
    'Optical Sensor-Camera Measurement Error (Extended)',
    output_dir + 'extended_error.png'
)

print("\nAll plots generated successfully!")
print(f"\nPlots saved to: {output_dir}")