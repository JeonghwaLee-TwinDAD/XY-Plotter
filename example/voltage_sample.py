"""Example of analog input voltage acquisition.

This example demonstrates how to acquire a voltage measurement using software timing.
"""

import os
import time
import nidaqmx
from nidaqmx.constants import AcquisitionType
import numpy as np
import pandas as pd

SAMPLE_RATE = 1000      # Hz
SAMPLES_PER_READ = 100  # Read every 100ms
DATALOG_PATH = r"C:\_Data_Log"

os.makedirs(DATALOG_PATH, exist_ok=True)

timestamp = time.strftime("%Y%m%d_%H%M%S")
filepath = os.path.join(DATALOG_PATH, f"voltage_data_{timestamp}.csv")

with nidaqmx.Task() as task:
    # Add 4 analog input channels (ai0 through ai3)
    task.ai_channels.add_ai_voltage_chan("Dev1/ai0:3", min_val=-10.0, max_val=10.0)

    task.timing.cfg_samp_clk_timing(
        rate=SAMPLE_RATE,
        sample_mode=AcquisitionType.CONTINUOUS,
        samps_per_chan=SAMPLES_PER_READ * 10  # Buffer = 10x read chunk
    )
    
    task.start()
    print(f"Acquiring data and saving to {filepath}...")
    
    # Initialize the CSV file with headers
    headers = ["Time", "Channel_0", "Channel_1", "Channel_2", "Channel_3"]
    pd.DataFrame(columns=headers).to_csv(filepath, index=False)
    
    start_time = time.time()

    try:
        while True:
            # Use task.read() to get a list of lists for multi-channel tasks
            data = task.read(number_of_samples_per_channel=SAMPLES_PER_READ)
            arr = np.array(data)
            
            # Safely ensure shape is (Channels, Samples) before transposing
            if arr.ndim == 1:
                arr = arr.reshape(4, SAMPLES_PER_READ)
                
            arr = arr.T  # Transpose to (100, 4) so each row is a sample across channels
            
            current_time = time.time() - start_time
            time_arr = np.linspace(current_time - (SAMPLES_PER_READ/SAMPLE_RATE), current_time, SAMPLES_PER_READ, endpoint=False)
            
            df = pd.DataFrame(arr, columns=["Channel_0", "Channel_1", "Channel_2", "Channel_3"])
            df.insert(0, "Time", time_arr)
            
            # Append data chunk to the CSV
            df.to_csv(filepath, mode='a', header=False, index=False)
            
            print(f"Saved {SAMPLES_PER_READ} samples. Ch0 Mean: {arr[:, 0].mean():.4f} V")
    except KeyboardInterrupt:
        print("Acquisition stopped by user.")

    task.stop()
    task.close()    
