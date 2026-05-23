"""
hardware.py
-----------
Hardware abstraction layer for the FlowGrind test system.

Responsible for setting up test stand valves, sweeping the spool, and
reading back live sensors (Encoder, Flow Meter, Pressure Transducers).
"""

import queue
import threading
import time
import numpy as np
import nidaqmx
from nidaqmx.constants import EncoderType, LengthUnits, AcquisitionType

from config import STROKE, SUPPLY_PRESSURE, FLOW_LIMIT

SAMPLE_RATE = 1000      # Hz
SAMPLES_PER_READ = 100  # Read every 100ms

class HardwareInterface:
    def __init__(self) -> None:
        self.is_connected = False
        self.position_task = None
        # Initialize physical DAQ/PLC connections or serial ports here

    def connect(self) -> None:
        """Establish connection to DAQ/PLC hardware."""
        self.is_connected = True
        
        try:
            self.position_task = nidaqmx.Task("SpoolPosition")
            self.position_task.ai_channels.add_ai_voltage_chan("Dev1/ai0", min_val=-10.0, max_val=10.0)
            self.position_task.timing.cfg_samp_clk_timing(
                rate=SAMPLE_RATE,
                sample_mode=AcquisitionType.CONTINUOUS,
                samps_per_chan=SAMPLES_PER_READ * 10
            )
            self.position_task.start()

        except nidaqmx.DaqError as e:
            print(f"[Hardware] DAQmx spool position channel failed: {e}")
            self.position_task = None

        print("[Hardware] Connected to Test Stand DAQ/PLC.")

    def disconnect(self) -> None:
        """Safely close hardware connections."""
        self.is_connected = False
        if self.position_task:
            try:
                self.position_task.stop()
            except nidaqmx.DaqError:
                pass
            self.position_task.close()
        print("[Hardware] Disconnected from Test Stand.")

    def set_valve_mode(self, mode: str) -> None:
        """Configure test stand valves/solenoids for the requested test mode."""
        print(f"[Hardware] Setting valve configuration to: {mode}")
        # Replace with actual I/O writes (e.g., setting PLC relays)
        time.sleep(0.5)

    def read_spool_position(self) -> float:
        """Read the live spool position from the DAQ in raw counts."""
        if self.position_task:
            data = self.position_task.in_stream.read(number_of_samples_per_channel=SAMPLES_PER_READ)
            return float(np.mean(data))
        return 0.0

    def sweep_spool(
        self, test_id: int, mode: str, data_queue: queue.Queue, stop_event: threading.Event
    ) -> threading.Thread:
        """
        Perform a stroke sweep on a background thread.
        Commands the motion controller, reads sensors, and pushes live (X, Y) pairs.
        """
        def _sweep_task():
            print(f"[Hardware] Starting sweep for {mode}...")
            
            start_pos = -STROKE
            end_pos = STROKE
            steps = 200
            
            for i in range(steps + 1):
                if stop_event.is_set():
                    break
                    
                # Physical position (X) and Delay (Sweep rate)
                x = start_pos + (end_pos - start_pos) * (i / steps)
                
                # --- REPLACE BELOW WITH ACTUAL DAQ READS ---
                # Simulated FlowGrind theory for offline validation
                if mode in ["PG", "NoLoad"]:
                    # Pressure vs Position (High gain around null)
                    pg_slope_psi_per_inch = 100000.0
                    y = x * pg_slope_psi_per_inch
                    y = np.clip(y, -SUPPLY_PRESSURE * 0.5, SUPPLY_PRESSURE * 0.5)
                    y += np.random.normal(0, 20)  # pressure noise
                else:
                    # Flow vs Position (Linear with a lap deadband)
                    overlap = 0.0003  # inches of lap
                    flow_gain = 35000 # gpm/inch
                    y = np.sign(x) * max(0, abs(x) - overlap) * flow_gain
                    y = np.clip(y, -FLOW_LIMIT, FLOW_LIMIT)
                    y += np.random.normal(0, 0.05)  # flow noise
                
                data_queue.put((test_id, float(x), float(y)))
                time.sleep(0.015)  # Determines real-world sweep duration

            print(f"[Hardware] Sweep for {mode} complete.")

        thread = threading.Thread(target=_sweep_task, daemon=True)
        thread.start()
        return thread
