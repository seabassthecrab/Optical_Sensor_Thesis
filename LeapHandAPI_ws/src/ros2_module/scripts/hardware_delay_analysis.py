import csv
import numpy as np
import matplotlib.pyplot as plt
from scipy import signal
from scipy.interpolate import interp1d

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

def detect_transitions(values, threshold=5.0):
    """Detect rising edge transitions in the data"""
    transitions = []
    in_transition = False
    
    for i in range(1, len(values)):
        if not in_transition and values[i] > threshold and values[i-1] <= threshold:
            # Rising edge detected
            transitions.append(i)
            in_transition = True
        elif in_transition and values[i] < threshold * 0.5:
            # Back below threshold
            in_transition = False
    
    return transitions

def cross_correlation_delay(sensor, leap, sample_rate):
    """Calculate delay using cross-correlation"""
    # Normalize signals
    sensor_norm = (sensor - np.mean(sensor)) / (np.std(sensor) + 1e-10)
    leap_norm = (leap - np.mean(leap)) / (np.std(leap) + 1e-10)
    
    # Compute cross-correlation
    correlation = signal.correlate(leap_norm, sensor_norm, mode='full')
    lags = signal.correlation_lags(len(leap_norm), len(sensor_norm), mode='full')
    
    # Find peak correlation
    peak_idx = np.argmax(correlation)
    lag_samples = lags[peak_idx]
    
    # Convert to time delay
    delay_seconds = lag_samples / sample_rate
    
    return delay_seconds, correlation[peak_idx], lags, correlation

def event_based_delay(data, threshold=5.0):
    """Calculate delay by matching rising edge events"""
    t = np.array(data['t_s'])
    sensor = np.array(data['sensor_deg'])
    leap = np.array(data['leap_deg'])
    
    # Detect transitions
    sensor_trans = detect_transitions(sensor, threshold)
    leap_trans = detect_transitions(leap, threshold)
    
    delays = []
    matched_events = []
    
    # Match each sensor transition to nearest leap transition
    for s_idx in sensor_trans:
        s_time = t[s_idx]
        
        # Find closest leap transition that occurs after sensor
        for l_idx in leap_trans:
            l_time = t[l_idx]
            delay = l_time - s_time
            
            # Only consider delays between 0 and 2 seconds
            if 0 <= delay <= 2.0:
                delays.append(delay)
                matched_events.append((s_time, l_time, s_idx, l_idx))
                break
    
    return delays, matched_events

def plot_delay_analysis(data, delays, matched_events, output_file):
    """Plot delay analysis results"""
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(8, 6))
    
    t = np.array(data['t_s'])
    t_norm = t - t[0]
    sensor = np.array(data['sensor_deg'])
    leap = np.array(data['leap_deg'])
    
    # Plot 1: Sensor and LEAP with matched events
    ax1.plot(t_norm, sensor, label='Contact Sensor', linewidth=1.2, 
             color='#1f77b4', alpha=0.9)
    ax1.plot(t_norm, leap, label='LEAP Hand', linewidth=1.2, 
             color='#ff7f0e', alpha=0.9)
    
    # Mark matched events
    for s_time, l_time, s_idx, l_idx in matched_events:
        s_time_norm = s_time - t[0]
        l_time_norm = l_time - t[0]
        ax1.plot([s_time_norm, l_time_norm], [sensor[s_idx], leap[l_idx]], 
                'r--', linewidth=0.8, alpha=0.5)
        ax1.plot(s_time_norm, sensor[s_idx], 'go', markersize=4)
        ax1.plot(l_time_norm, leap[l_idx], 'ro', markersize=4)
    
    ax1.set_xlabel('Time (s)')
    ax1.set_ylabel('Angle (degrees)')
    ax1.set_title('Sensor Response Delay Analysis')
    ax1.legend(loc='best')
    ax1.grid(True, alpha=0.3, linestyle='--', linewidth=0.5)
    
    # Plot 2: Delay histogram
    if len(delays) > 0:
        ax2.hist(delays, bins=20, color='#2ca02c', alpha=0.7, edgecolor='black')
        mean_delay = np.mean(delays)
        std_delay = np.std(delays)
        
        ax2.axvline(mean_delay, color='red', linestyle='--', linewidth=2, 
                   label=f'Mean: {mean_delay*1000:.1f} ms')
        ax2.set_xlabel('Delay (s)')
        ax2.set_ylabel('Frequency')
        ax2.set_title('LEAP Hand Response Delay Distribution')
        ax2.legend(loc='best')
        ax2.grid(True, alpha=0.3, linestyle='--', linewidth=0.5)
        
        # Add statistics text
        textstr = f'μ = {mean_delay*1000:.2f} ms\nσ = {std_delay*1000:.2f} ms\nn = {len(delays)}'
        props = dict(boxstyle='round', facecolor='wheat', alpha=0.5)
        ax2.text(0.98, 0.98, textstr, transform=ax2.transAxes, fontsize=9,
                verticalalignment='top', horizontalalignment='right', bbox=props)
    
    plt.tight_layout()
    plt.savefig(output_file, bbox_inches='tight')
    print(f"Saved: {output_file}")
    plt.close()

def plot_cross_correlation(lags, correlation, sample_rate, delay, output_file):
    """Plot cross-correlation function"""
    fig, ax = plt.subplots(figsize=(7, 4))
    
    # Convert lags to time
    time_lags = lags / sample_rate
    
    # Only plot relevant range (-1 to 3 seconds)
    mask = (time_lags >= -1) & (time_lags <= 3)
    
    ax.plot(time_lags[mask], correlation[mask], linewidth=1.2, color='#1f77b4')
    ax.axvline(delay, color='red', linestyle='--', linewidth=2, 
              label=f'Peak at {delay*1000:.1f} ms')
    ax.axvline(0, color='gray', linestyle='-', linewidth=0.5, alpha=0.5)
    
    ax.set_xlabel('Time Lag (s)')
    ax.set_ylabel('Cross-Correlation')
    ax.set_title('Cross-Correlation: LEAP Hand vs Contact Sensor')
    ax.legend(loc='best')
    ax.grid(True, alpha=0.3, linestyle='--', linewidth=0.5)
    
    plt.tight_layout()
    plt.savefig(output_file, bbox_inches='tight')
    print(f"Saved: {output_file}")
    plt.close()

def main():
    # File paths
    adjusted_file = '/home/hikikomori/Project/Robotic_work/LeapHandAPI_ws/src/ros2_module/scripts/adjusted_arducam_data.csv'
    extended_file = '/home/hikikomori/Project/Robotic_work/LeapHandAPI_ws/src/ros2_module/scripts/extended_arducam_data.csv'
    output_dir = '/home/hikikomori/Project/Robotic_work/LeapHandAPI_ws/src/ros2_module/scripts/'
    
    # Analyze both datasets
    for filename, label in [(adjusted_file, 'adjusted'), (extended_file, 'extended')]:
        print(f"\n{'='*60}")
        print(f"Analyzing {label} dataset...")
        print('='*60)
        
        # Load data
        data = load_csv_data(filename)
        t = np.array(data['t_s'])
        sensor = np.array(data['sensor_deg'])
        leap = np.array(data['leap_deg'])
        
        # Calculate sample rate
        time_diffs = np.diff(t)
        avg_sample_rate = 1.0 / np.mean(time_diffs)
        print(f"Average sample rate: {avg_sample_rate:.1f} Hz")
        
        # Method 1: Event-based delay detection
        print("\n--- Event-Based Delay Analysis ---")
        delays, matched_events = event_based_delay(data, threshold=5.0)
        
        if len(delays) > 0:
            mean_delay = np.mean(delays)
            std_delay = np.std(delays)
            min_delay = np.min(delays)
            max_delay = np.max(delays)
            
            print(f"Number of matched events: {len(delays)}")
            print(f"Mean delay: {mean_delay*1000:.2f} ms")
            print(f"Std deviation: {std_delay*1000:.2f} ms")
            print(f"Min delay: {min_delay*1000:.2f} ms")
            print(f"Max delay: {max_delay*1000:.2f} ms")
            
            # Plot event-based analysis
            plot_delay_analysis(data, delays, matched_events, 
                              output_dir + f'{label}_delay_analysis.png')
        else:
            print("No matching events found with current threshold")
        
        # Method 2: Cross-correlation
        print("\n--- Cross-Correlation Analysis ---")
        delay_corr, peak_corr, lags, correlation = cross_correlation_delay(
            sensor, leap, avg_sample_rate)
        
        print(f"Cross-correlation delay: {delay_corr*1000:.2f} ms")
        print(f"Peak correlation coefficient: {peak_corr:.3f}")
        
        # Plot cross-correlation
        plot_cross_correlation(lags, correlation, avg_sample_rate, delay_corr,
                              output_dir + f'{label}_cross_correlation.png')
    
    print("\n" + "="*60)
    print("Analysis complete! All plots saved.")
    print("="*60)

if __name__ == "__main__":
    main()