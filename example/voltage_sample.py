"""Example of analog input voltage acquisition.

This example demonstrates how to acquire a voltage measurement using software timing.
"""

import nidaqmx
from nidaqmx.constants import AcquisitionType
import numpy as np

SAMPLE_RATE = 1000      # Hz
SAMPLES_PER_READ = 100  # Read every 100ms

with nidaqmx.Task() as task:
    task.ai_channels.add_ai_voltage_chan("Dev1/ai0", min_val=-10.0, max_val=10.0)

    task.timing.cfg_samp_clk_timing(
        rate=SAMPLE_RATE,
        sample_mode=AcquisitionType.CONTINUOUS,
        samps_per_chan=SAMPLES_PER_READ * 10  # Buffer = 10x read chunk
    )
    
    task.start()

    try:
        while True:
            data = task.in_stream.read(number_of_samples_per_channel=SAMPLES_PER_READ)
            arr = np.array(data)
            print(f"Mean: {arr.mean():.4f} V, Std: {arr.std():.4f} V")
    except KeyboardInterrupt:
        pass

    task.stop()
    task.close()    

