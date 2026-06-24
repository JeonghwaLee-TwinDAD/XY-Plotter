"""
mcp_server.py
--------------
Headless MCP server for the FlowGrind XY-Plotter test system.

Exposes the test sequence defined in config.TEST_SEQUENCE as MCP tools so
an LLM client can drive the test stand (run individual tests or named
sequences, abort, check status) and read back live data and analysis
results -- without the matplotlib GUI.

Reuses HardwareInterface (hardware.py), the analysis functions
(analysis.py), and DataLogger (datalogger.py) exactly as the GUI app does;
only the plotting/annotation layer (plotter.py, tpi.py) is bypassed.

Run with:
    py mcp_server.py
"""

from __future__ import annotations

import queue
import threading
from typing import Optional

import numpy as np
from mcp.server.fastmcp import FastMCP

import analysis as an
from config import (
    PART_NUMBER,
    TEST_SEQUENCE,
    TEST_STAND_NUMBER,
    WINDOW_1_IDS,
    WINDOW_2_IDS,
)
from datalogger import DataLogger
from hardware import HardwareInterface

# ---------------------------------------------------------------------------
# Named test groups for run_sequence()
# ---------------------------------------------------------------------------
_TEST_GROUPS: dict[str, tuple[int, ...]] = {
    "window1": WINDOW_1_IDS,
    "window2": WINDOW_2_IDS,
    "3way": WINDOW_1_IDS,
    "4wayLap": (2,),
    "NoLoad": (3,),
    "PG": (4,),
    "Leak": (5,),
    "all": WINDOW_1_IDS + WINDOW_2_IDS,
}


class TestRunner:
    """Headless test orchestrator -- mirrors TPI's lifecycle without a GUI."""

    def __init__(self) -> None:
        self.hw = HardwareInterface()
        self.series_data: dict[int, dict[str, list]] = {}
        self.results: dict[int, dict] = {}
        self._x_intercepts: dict[str, float] = {}
        self.serial_number: str = ""
        self.current_test_id: Optional[int] = None
        self.abort_event = threading.Event()
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def connect(self) -> None:
        self.hw.connect_daq()

    def disconnect(self) -> None:
        self.hw.disconnect_daq()

    def reset(self, serial_number: str = "") -> None:
        self.series_data.clear()
        self.results.clear()
        self._x_intercepts.clear()
        self.abort_event.clear()
        self.serial_number = serial_number

    def status(self) -> dict:
        return {
            "connected": self.hw.is_connected,
            "running": self._lock.locked(),
            "current_test_id": self.current_test_id,
            "serial_number": self.serial_number,
            "completed_test_ids": sorted(self.results.keys()),
        }

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------
    def run_test(self, test_id: int) -> dict:
        if test_id not in TEST_SEQUENCE:
            raise ValueError(f"Unknown test_id {test_id}. Valid: {sorted(TEST_SEQUENCE)}")

        cfg = TEST_SEQUENCE[test_id]
        with self._lock:
            self.current_test_id = test_id
            self.abort_event.clear()
            try:
                self._acquire(test_id, cfg.mode)
                if self.abort_event.is_set():
                    result = {"test_id": test_id, "mode": cfg.mode, "aborted": True}
                else:
                    result = self._analyse(test_id, cfg.mode)
                self.results[test_id] = result
                return result
            finally:
                self.current_test_id = None

    def run_sequence(self, test_ids: tuple[int, ...]) -> list[dict]:
        out = []
        for tid in test_ids:
            if self.abort_event.is_set():
                break
            out.append(self.run_test(tid))
        return out

    def abort(self) -> None:
        self.abort_event.set()

    # ------------------------------------------------------------------
    # Acquisition
    # ------------------------------------------------------------------
    def _acquire(self, test_id: int, mode: str) -> None:
        data_queue: queue.Queue = queue.Queue()
        thread = self.hw.sweep_spool(test_id, mode, data_queue, self.abort_event)
        entry = self.series_data.setdefault(test_id, {"X": [], "Y": []})

        while thread.is_alive() or not data_queue.empty():
            try:
                _, x, y, *_extra = data_queue.get(timeout=0.05)
            except queue.Empty:
                continue
            entry["X"].append(x)
            entry["Y"].append(y)

    # ------------------------------------------------------------------
    # Analysis dispatch (mirrors TPI._analyse_and_annotate, minus plotting)
    # ------------------------------------------------------------------
    def _analyse(self, test_id: int, mode: str) -> dict:
        entry = self.series_data.get(test_id)
        if not entry or not entry["X"]:
            return {"test_id": test_id, "mode": mode, "error": "no data acquired"}

        data_xy = np.column_stack((entry["X"], entry["Y"]))
        data_xy = data_xy[~np.isnan(data_xy).any(axis=1)]

        if mode in ("3way-C1", "3way-C2", "4wayLap"):
            extra = self._analyse_lap(test_id, mode, data_xy)
        elif mode == "NoLoad":
            r = an.analyse_no_load(data_xy)
            extra = {
                "summary": r.summary_text, "passed": r.passed,
                "max_pressure_psi": r.max_pressure, "min_pressure_psi": r.min_pressure,
            }
        elif mode == "PG":
            r = an.analyse_pressure_gain(data_xy)
            extra = {
                "summary": r.summary_text, "passed": r.passed,
                "slope_psi_per_thou": r.slope_psi_per_thou,
            }
        elif mode == "Leak":
            r = an.analyse_leakage(data_xy)
            extra = {
                "summary": r.summary_text, "passed": r.passed,
                "max_leak_gpm": r.max_leak,
            }
        else:
            extra = {}

        return {"test_id": test_id, "mode": mode, "samples": len(data_xy), **extra}

    def _analyse_lap(self, test_id: int, mode: str, data_xy: np.ndarray) -> dict:
        lap = an.analyse_lap(data_xy)
        for direction, reg in (("up", lap.up), ("down", lap.down)):
            if reg is not None:
                self._x_intercepts[f"{test_id}_{direction}"] = reg.x_intercept_inch

        extra: dict = {}
        if mode == "3way-C2" and {"0_up", "0_down", "1_up", "1_down"}.issubset(self._x_intercepts):
            s = an.summarise_3way(self._x_intercepts)
            extra = {"summary": s.summary_text, "dist_up_in": float(s.dist_up), "dist_down_in": float(s.dist_down)}
        elif mode == "4wayLap" and {"2_up", "2_down"}.issubset(self._x_intercepts):
            s = an.summarise_4way(self._x_intercepts)
            extra = {"summary": s.summary_text, "passed": bool(s.passed), "distance_in": float(s.distance)}

        return extra


runner = TestRunner()
mcp = FastMCP("flowgrind-xy-plotter")


@mcp.tool()
def list_tests() -> dict:
    """List all configured test points, their modes/titles, and named test groups."""
    return {
        "part_number": PART_NUMBER,
        "test_stand": TEST_STAND_NUMBER,
        "tests": {tid: {"mode": cfg.mode, "title": cfg.title} for tid, cfg in TEST_SEQUENCE.items()},
        "groups": {name: list(ids) for name, ids in _TEST_GROUPS.items()},
    }


@mcp.tool()
def startup() -> str:
    """Connect to the DAQ (or enable simulation mode per config.SIMULATION)."""
    runner.connect()
    return "connected" if runner.hw.is_connected else "connection failed"


@mcp.tool()
def shutdown() -> str:
    """Disconnect from the DAQ."""
    runner.disconnect()
    return "disconnected"


@mcp.tool()
def reset_uut(serial_number: str = "") -> dict:
    """Clear all collected data/results and set the serial number for a new unit under test."""
    runner.reset(serial_number)
    return runner.status()


@mcp.tool()
def run_test(test_id: int) -> dict:
    """
    Run a single test point and return its analysis result.

    test_id: one of the IDs returned by list_tests() (0-5).
    """
    return runner.run_test(test_id)


@mcp.tool()
def run_sequence(group: str) -> list[dict]:
    """
    Run a named group of tests in order and return each result.

    group: one of "window1", "window2", "3way", "4wayLap", "NoLoad", "PG", "Leak", "all".
    """
    if group not in _TEST_GROUPS:
        raise ValueError(f"Unknown group '{group}'. Valid: {sorted(_TEST_GROUPS)}")
    return runner.run_sequence(_TEST_GROUPS[group])


@mcp.tool()
def abort() -> str:
    """Abort the currently running sweep/sequence."""
    runner.abort()
    return "abort requested"


@mcp.tool()
def get_status() -> dict:
    """Get the current connection/run state."""
    return runner.status()


@mcp.tool()
def get_results(test_id: Optional[int] = None) -> dict:
    """Get analysis results. Omit test_id to return all results collected so far."""
    if test_id is not None:
        return runner.results.get(test_id, {})
    return runner.results


@mcp.tool()
def get_series_data(test_id: int) -> dict:
    """Get the raw acquired (X, Y) sample arrays for a test point."""
    return runner.series_data.get(test_id, {"X": [], "Y": []})


@mcp.tool()
def save_datalog() -> Optional[str]:
    """Save all acquired series data to a timestamped CSV in config.DATALOG_PATH."""
    return DataLogger().save(
        series_data=runner.series_data,
        part_number=PART_NUMBER,
        serial_number=runner.serial_number,
    )


if __name__ == "__main__":
    mcp.run()
