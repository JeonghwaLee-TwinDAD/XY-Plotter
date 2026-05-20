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

from config import STROKE, SUPPLY_PRESSURE, FLOW_LIMIT


class HardwareInterface:
    def __init__(self) -> None:
        self.is_connected = False
        # Initialize physical DAQ/PLC connections or serial ports here

    def connect(self) -> None:
        """Establish connection to DAQ/PLC hardware."""
        self.is_connected = True
        print("[Hardware] Connected to Test Stand DAQ/PLC.")

    def disconnect(self) -> None:
        """Safely close hardware connections."""
        self.is_connected = False
        print("[Hardware] Disconnected from Test Stand.")

    def set_valve_mode(self, mode: str) -> None:
        """Configure test stand valves/solenoids for the requested test mode."""
        print(f"[Hardware] Setting valve configuration to: {mode}")
        # Replace with actual I/O writes (e.g., setting PLC relays)
        time.sleep(0.5)

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
