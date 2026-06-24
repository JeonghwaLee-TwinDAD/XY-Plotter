"""
hardware.py
-----------
Hardware abstraction layer for the FlowGrind test system.

Responsible for setting up test stand valves, sweeping the spool, and
reading back live sensors (Encoder, Flow Meter, Pressure Transducers).

DAQ channel mapping — named aliases on Dev1 (configured in NI MAX)
--------------------------------------------------------------------
  Position — Dev1/ai0  (linear pot / encoder voltage → X axis)
  Flow     — Dev1/ai1  (flow transducer voltage     → Y axis, flow tests)
  Pressure — Dev1/ai2  (pressure transducer voltage → Y axis, PG/NoLoad tests)
"""

import queue
import threading
import time
from typing import Tuple
import numpy as np
import nidaqmx
from nidaqmx.constants import AcquisitionType

from config import STROKE, SUPPLY_PRESSURE, FLOW_LIMIT, SIMULATION, SIMULATE_SWEEPS

# ---------------------------------------------------------------------------
# DAQ timing constants
# ---------------------------------------------------------------------------
DAQ_DEVICE       = "Dev1"
SAMPLE_RATE      = 1000   # Hz
SAMPLES_PER_READ = 10     # samples per channel per read (= 10 ms per chunk)

NUM_AI_CHANNELS  = 3

# Channel aliases (name_to_assign_to_channel), added to the task in this
# order — index in the averaged read matches the add order below.
_CH_POSITION = 0   # "Position" — Dev1/ai0
_CH_FLOW     = 1   # "Flow"     — Dev1/ai1
_CH_PRESSURE = 2   # "Pressure" — Dev1/ai2

# ---------------------------------------------------------------------------
# Stub sweep parameters (used only when real DAQ reads return zeros)
# Replace with real DAQ reads in production — see the REPLACE comment below.
# ---------------------------------------------------------------------------
_SWEEP_STEPS        = 200        # position increments per sweep pass
_SWEEP_STEP_DELAY   = 0.010      # seconds between steps (controls sweep speed)
_LAP_PROFILE_DT     = 0.04       # position resolution for 3way/4way lap profiles
                                 # (coarser than _SWEEP_STEP_DELAY so the lap
                                 # sweep — which ramps over a wider span — doesn't
                                 # generate ~6x more points/redraws than other tests)
_SIM_PG_SLOPE       = 1300_000.0  # psi/inch  — theoretical pressure-gain slope
_SIM_FLOW_OVERLAP   = 0.0003     # inches    — lap deadband for flow tests
_SIM_FLOW_GAIN      = 35_000.0   # gpm/inch  — flow gain outside the lap


class HardwareInterface:

    def __init__(self) -> None:
        self.is_connected = False
        self.daq_task: nidaqmx.Task | None = None

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    def connect_daq(self) -> None:
        """Open a 3-channel continuous acquisition task (real NI-DAQmx —
        physical or simulated/virtual device, as configured in NI MAX),
        with each physical channel given a friendly alias name."""
        if SIMULATION:
            print("[Hardware] Running in SIMULATION mode.")
            self.is_connected = True
            self.daq_task = None
            return

        self.is_connected = True
        try:
            self.daq_task = nidaqmx.Task("FlowGrindDAQ")

            # ai0 = Position | ai1 = Flow | ai2 = Pressure — aliased so the
            # task's channels read back by name, matching NI MAX.
            for ai_line, alias in (("ai0", "Position"), ("ai1", "Flow"), ("ai2", "Pressure")):
                self.daq_task.ai_channels.add_ai_voltage_chan(
                    f"{DAQ_DEVICE}/{ai_line}", name_to_assign_to_channel=alias,
                    min_val=-10.0, max_val=10.0,
                )
            self.daq_task.timing.cfg_samp_clk_timing(
                rate=SAMPLE_RATE,
                sample_mode=AcquisitionType.CONTINUOUS,
                # Buffer sized for ~30s, not just one read chunk: when
                # SIMULATE_SWEEPS is on, sweeps don't drain this task at all
                # (they run on software-simulated data instead), so the
                # buffer must outlast the longest sweep or it overflows —
                # which would otherwise leave idle reads broken afterward.
                samps_per_chan=SAMPLE_RATE * 30,
            )
            self.daq_task.start()
            print("[Hardware] DAQ task started — Position, Flow, Pressure (Dev1/ai0:2).")

        except nidaqmx.DaqError as e:
            print(f"[Hardware] DAQmx task failed to start: {e}")
            self.daq_task = None

        print("[Hardware] Connected to Test Stand DAQ/PLC.")

    def disconnect_daq(self) -> None:
        """Safely stop and close the DAQ task."""
        self.is_connected = False
        if self.daq_task is not None:
            try:
                self.daq_task.stop()
            except nidaqmx.DaqError:
                pass
            self.daq_task.close()
            self.daq_task = None
        print("[Hardware] Disconnected from Test Stand.")

    # ------------------------------------------------------------------
    # Sensor reads
    # ------------------------------------------------------------------

    def read_voltages(self) -> np.ndarray:
        """
        Read one chunk of SAMPLES_PER_READ samples from all three aliased
        channels (Position, Flow, Pressure) and return per-channel mean
        voltages.

        Returns:
            np.ndarray shape (3,): [position_V, flow_V, pressure_V]
            Returns zeros if the DAQ task is unavailable.

        Pattern follows the voltage_sample.py example:
          • task.read() returns a list-of-lists for multi-channel tasks.
          • Reshape to (channels, samples) when ndim == 1 (single-sample edge case).
          • Average across the sample dimension for noise reduction.
        """
        if self.daq_task is None:
            return np.zeros(NUM_AI_CHANNELS)

        try:
            data = self.daq_task.read(number_of_samples_per_channel=SAMPLES_PER_READ)
        except nidaqmx.DaqError as e:
            # A buffer overflow (or similar) leaves the task unable to read
            # again until it's restarted — without this, idle reads would
            # stay broken for the rest of the run instead of recovering on
            # the next poll.
            print(f"[Hardware] DAQ read failed, restarting task: {e}")
            try:
                self.daq_task.stop()
                self.daq_task.start()
            except nidaqmx.DaqError:
                pass
            return np.zeros(NUM_AI_CHANNELS)

        arr = np.array(data)                  # shape: (3, SAMPLES_PER_READ)

        if arr.ndim == 1:                     # safety: single-sample edge case
            arr = arr.reshape(NUM_AI_CHANNELS, SAMPLES_PER_READ)

        return arr.mean(axis=1)               # (3,)  one mean voltage per channel

    def read_all_channels(self) -> Tuple[float, float, float]:
        """Return the mean voltages for all channels: (position, flow, pressure)."""
        v = self.read_voltages()
        return float(v[_CH_POSITION]), float(v[_CH_FLOW]), float(v[_CH_PRESSURE])

    # ------------------------------------------------------------------
    # Valve / actuator control
    # ------------------------------------------------------------------

    def _build_profile(
        self,
        ramp_start: float,
        null_upper: float,
        null_lower: float,
        ramp_end: float,
        rate_far: float,
        rate_close: float,
        mode: str = "increasing",
        dt: float = 0.015,
    ) -> np.ndarray:
        """Generate a position profile with varying sweep rates for the actuator."""
        values = [ramp_start]
        current = ramp_start

        def step(target: float, rate: float):
            nonlocal current
            diff = target - current
            if abs(diff) < 1e-6:
                return
            direction = np.sign(diff)
            num_steps = int(np.ceil(abs(diff) / (rate * dt)))
            if num_steps > 0:
                step_vals = current + direction * rate * dt * np.arange(1, num_steps + 1)
                step_vals[-1] = target
                values.extend(step_vals.tolist())
                current = target

        if mode.lower() == "increasing":
            step(null_lower, rate_far)
            step(null_upper, rate_close)
            step(ramp_end, rate_far)
        elif mode.lower() == "decreasing":
            step(null_upper, rate_far)
            step(null_lower, rate_close)
            step(ramp_end, rate_far)

        return np.array(values)

    def set_valve_mode(self, mode: str) -> None:
        """Configure test stand valves/solenoids for the requested test mode."""
        print(f"[Hardware] Setting valve configuration to: {mode}")
        # Replace with actual I/O writes (e.g., NI-DAQ digital output, PLC register)
        time.sleep(0.05)

    # ------------------------------------------------------------------
    # Sweep
    # ------------------------------------------------------------------

    def sweep_spool(
        self,
        test_id: int,
        mode: str,
        data_queue: queue.Queue,
        abort_event: threading.Event,
    ) -> threading.Thread:
        """
        Perform a full stroke sweep on a background thread.

        On each step the motion controller commands a target position; the
        actual position and the appropriate sensor channel are then read back
        via read_voltages() and pushed to data_queue as (test_id, x, y) tuples.

        Args:
            test_id:    Series ID forwarded to the plotter.
            mode:       Test mode string — selects which sensor channel is Y.
            data_queue: Thread-safe queue consumed by XYPlotter.
            abort_event: Set by the plotter when the operator clicks Stop.

        Returns:
            The running background Thread (caller blocks until it is alive).
        """
        def _sweep_task() -> None:
            self.set_valve_mode(mode)
            print(f"[Hardware] Starting sweep for {mode}...")

            # Generate target profile based on test mode
            if mode in ("3way-C1", "3way-C2", "4wayLap"):
                targets = self._build_profile(
                    STROKE, 1.0, -1.0, -STROKE, 2.0, 0.5, "decreasing", _LAP_PROFILE_DT
                )
            else:
                # Standard linear sweep for other tests
                targets = np.linspace(STROKE, -STROKE, _SWEEP_STEPS + 1)

            for target_x in targets:
                if abort_event.is_set():
                    break

                # --- REPLACE BELOW: command motion controller to target position ---
                # motion_controller.move_to(target_x)
                # time.sleep(_SWEEP_STEP_DELAY)   # wait for settle

                # SIMULATE_SWEEPS forces every test sweep through the
                # software-simulated profile below, regardless of whether a
                # live DAQ task is connected — the live task is still used
                # for idle indicator reads between tests (see read_all_channels
                # via XYPlotter.idle_reader). Only read real channels here
                # when sweeps aren't simulated.
                if not SIMULATE_SWEEPS:
                    x, flow, pressure = self.read_all_channels()

                if SIMULATE_SWEEPS or self.daq_task is None:
                    x = target_x
                    x_in = x / 1000.0  # Convert thou to inches for realistic simulated physics
                    
                    # Clean deterministic simulation profiles following realistic simulation data
                    if mode == "NoLoad":
                        pressure = -700.0 - 600.0 * (x_in / 0.01)**2  # Parabolic drift from 800 PSI down to 200 PSI
                        flow = 0.0
                    elif mode == "Leak":
                        pressure = 0.0
                        flow = max(0.0, 0.035 * (1.0 - abs(x_in) / 0.01))  # Leakage peak of ~0.035 GPM at null
                    else:
                        # Map tests to the correct physical valve quadrants:
                        # 3way-C1, 4wayLap, PG -> Region A to B (negative slope)
                        # 3way-C2 -> Region D to C (positive slope)
                        slope_dir = 1.0 if mode == "3way-C2" else -1.0

                        pressure = float(np.clip(slope_dir * x_in * _SIM_PG_SLOPE, -SUPPLY_PRESSURE * 0.5, SUPPLY_PRESSURE * 0.5))
                        flow = slope_dir * np.sign(x_in) * max(0.0, abs(x_in) - _SIM_FLOW_OVERLAP) * _SIM_FLOW_GAIN
                        flow = float(np.clip(flow, -FLOW_LIMIT, FLOW_LIMIT))
                    
                    time.sleep(_SWEEP_STEP_DELAY)

                if mode in ("PG", "NoLoad"):
                    y = pressure                        # ai2 — pressure transducer
                else:
                    y = flow                            # ai1 — flow meter

                data_queue.put((test_id, float(x), float(y), float(flow), float(pressure)))

            print(f"[Hardware] Sweep for {mode} complete.")

        thread = threading.Thread(target=_sweep_task, daemon=True)
        thread.start()
        return thread
