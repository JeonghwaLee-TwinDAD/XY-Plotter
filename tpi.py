"""
tpi.py
------
TPI — test program interface / orchestrator.

Responsibilities:
  • Own the test sequence (which IDs run in which window).
  • Drive XYPlotter: load data, wait for acquisition, call sweep analysis.
  • Render analysis results back onto the plotter (annotations, text).
  • Log results to CSV via DataLogger.

TPI does NOT reach into XYPlotter's internals; it uses the plotter's
public API exclusively (get_series_xy, add_overlay_series, add_annotation).
"""

from __future__ import annotations

import time
from typing import Dict, Optional

import matplotlib.pyplot as plt
import numpy as np

import analysis as an
from config import (
    LAP_CONDITION,
    PART_NUMBER,
    SCALE_FACTOR,
    SIMULATION,
    SUPPLY_PRESSURE,
    TEST_SEQUENCE,
    TEST_STAND_NUMBER,
    WINDOW_1_IDS,
    WINDOW_2_IDS,
)
from datalogger import DataLogger
from plotter import XYPlotter
from hardware import HardwareInterface


class TPI:
    """Test orchestrator for the FlowGrind spool-valve test system."""

    def __init__(self) -> None:
        self.supply_press: float = SUPPLY_PRESSURE
        self.serial_number: str  = ""           # set by operator before postUUT()
        self._x_intercepts: Dict[str, float]    = {}
        self._active_window: int                 = 1   # 1 or 2; tracks current window
        self._is_switching_windows: bool         = False
        self._is_executing: bool                 = False
        self._test_idx: int                      = 0

        # Running text for the info box; accumulates across all tests
        self._result_text: str = ""

        self.plotter = self._make_plotter(update_interval=10)
        self.hw = HardwareInterface()

    # ------------------------------------------------------------------
    # Plotter lifecycle helpers
    # ------------------------------------------------------------------

    def _make_plotter(self, update_interval: int) -> XYPlotter:
        p = XYPlotter(update_interval=update_interval)
        p.btn_run.on_clicked(self._on_restart)
        p.fig.canvas.mpl_connect("close_event", self._on_window_close)
        p.fig.canvas.mpl_connect("key_press_event", self._on_key)
        
        p.set_window_title(f"FlowGrind | P/N: {PART_NUMBER} | S/N: {self.serial_number} | Test Stand: {TEST_STAND_NUMBER}")
        p.part_text.set_text(self._result_text)
        return p

    def _on_window_close(self, _event) -> None:
        if not self._is_switching_windows:
            self.postUUT()

    def _on_key(self, event) -> None:
        """Handle keyboard shortcuts mirroring button clicks."""
        key = str(getattr(event, "key", "") or "").lower()
        if key == "f8":
            self._on_restart(event)

    def _on_restart(self, _event) -> None:
        """Run the next test in the sequence when the operator clicks Start."""
        if not self.plotter.is_running or self._is_executing:
            return
            
        group = WINDOW_2_IDS if self._active_window == 2 else WINDOW_1_IDS
            
        if self._test_idx >= len(group):
            self._test_idx = 0
            
        if self._test_idx == 0:
            self.plotter.clear()
            self._result_text = ""
            self._x_intercepts.clear()
            self.plotter.part_text.set_text("")
            
        if not self.plotter.is_running:
            self.plotter.start()
            
        tid = group[self._test_idx]
        self.execute(tid)
            
        if self.plotter.is_running:
            self._test_idx += 1
            self.plotter.set_ready()

    # ------------------------------------------------------------------
    # Test lifecycle (matches original LabVIEW convention)
    # ------------------------------------------------------------------

    def startup(self) -> None:
        """System-level initialisation (hardware power-on, self-test, etc.)."""
        self.hw.connect_daq()

    def preUUT(self) -> None:
        """Part-level setup before the first test run."""
        pass  # extend for operator prompt, barcode scan, fixture check, etc.

    def switch_to_window_2(self) -> None:
        """
        Block until the operator closes Window 1, then open a fresh plotter
        for the Window-2 test group.

        Call this between the Window-1 and Window-2 execute() loops so that
        main.py never needs to touch private attributes.
        """
        self._is_switching_windows = True
        plt.show()                          # blocks until Window 1 is closed
        self._is_switching_windows = False
        self._active_window = 2
        self._test_idx = 0
        self.plotter = self._make_plotter(update_interval=10)

    def execute(self, test_id: int) -> None:
        """
        Run a single test point identified by *test_id*.

        Loads data, waits for acquisition to complete, then runs the
        appropriate analysis and renders annotations on the plotter.
        """
        if test_id not in TEST_SEQUENCE:
            return

        cfg = TEST_SEQUENCE[test_id]
        self._is_executing = True
        try:
            title = f"{cfg.title} | P/N: {PART_NUMBER} | S/N: {self.serial_number} | Test Stand: {TEST_STAND_NUMBER}"
            self.plotter.set_window_title(title)
            self._acquire(test_id, cfg.mode)
            if self.plotter.is_running:
                self._analyse_and_annotate(test_id, cfg.mode)
        finally:
            self._is_executing = False

    def postUUT(self) -> None:
        """Post-test teardown: save data, prompt operator, release fixture."""
        DataLogger().save(
            series_data=self.plotter.series_data,
            part_number=PART_NUMBER,
            serial_number=self.serial_number,
        )
        self.hw.disconnect_daq()

    # ------------------------------------------------------------------
    # Acquisition
    # ------------------------------------------------------------------

    def _acquire(self, test_id: int, mode: str) -> None:
        """Wait until acquisition is complete."""
        self.plotter.start()
        sweep_thread = self.hw.sweep_spool(test_id, mode, self.plotter.data_queue, self.plotter.abort_event)
        
        while sweep_thread.is_alive() or not self.plotter.data_queue.empty():
            if not self.plotter.is_running or self.plotter.abort_event.is_set():
                break
            plt.pause(0.01)

    # ------------------------------------------------------------------
    # Analysis dispatch and annotation
    # ------------------------------------------------------------------

    def _analyse_and_annotate(self, test_id: int, mode: str) -> None:
        """Run the correct analysis for *mode* and push results to the plotter."""
        data_xy = self.plotter.get_series_xy(test_id)
        if data_xy is None:
            return

        result_text = ""

        if mode in ("3way-C1", "3way-C2", "4wayLap"):
            result_text = self._handle_lap(test_id, mode, data_xy)

        elif mode == "NoLoad":
            result_text = self._handle_no_load(test_id, data_xy)

        elif mode == "PG":
            result_text = self._handle_pressure_gain(test_id, data_xy)

        elif mode == "Leak":
            result_text = self._handle_leakage(test_id, data_xy)

        self._append_result_text(result_text, mode)

    # ------------------------------------------------------------------
    # Per-mode analysis + annotation helpers
    # ------------------------------------------------------------------

    def _handle_lap(self, test_id: int, mode: str, data_xy: np.ndarray) -> str:
        result = an.analyse_lap(data_xy)

        for direction, reg, color, marker in (
            ("up",   result.up,   "blue", "o"),
            ("down", result.down, "red",  "s"),
        ):
            if reg is None:
                continue

            # Masked points
            pts = reg.masked_xy
            ax  = self.plotter.flow_ax
            line, = ax.plot(
                pts[:, 0], pts[:, 1],
                marker=marker, markersize=5, color=color,
                linewidth=0, markerfacecolor="white", markeredgecolor=color,
            )
            self.plotter.add_overlay_series(
                f"mask_{direction}_{test_id}",
                pts[:, 0].tolist(), pts[:, 1].tolist(), line,
            )

            # Regression line
            m, b   = reg.slope, reg.intercept
            x_int  = reg.x_intercept_raw
            x_vals = np.array([min(pts[:, 0].min(), x_int), max(pts[:, 0].max(), x_int)])
            y_vals = m * x_vals + b
            fit_line, = ax.plot(x_vals, y_vals, color="black", linestyle="--")
            self.plotter.add_overlay_series(
                f"fit_{direction}_{test_id}",
                x_vals.tolist(), y_vals.tolist(), fit_line,
            )

            # X-intercept marker
            pt, = ax.plot([x_int], [0], marker=marker, color=color, markersize=8, linestyle="None")
            self.plotter.add_overlay_series(
                f"int_{direction}_{test_id}", [x_int], [0.0], pt,
            )

            # Store scaled intercept for cross-sweep calculations
            self._x_intercepts[f"{test_id}_{direction}"] = reg.x_intercept_inch

        # Summary text (only after both 3-way sweeps or the 4-way sweep)
        if mode == "3way-C2":
            required = {"0_up", "0_down", "1_up", "1_down"}
            if required.issubset(self._x_intercepts):
                summary = an.summarise_3way(self._x_intercepts)
                return summary.summary_text

        elif mode == "4wayLap":
            if {"2_up", "2_down"}.issubset(self._x_intercepts):
                summary = an.summarise_4way(self._x_intercepts)
                ann = self.plotter.flow_ax.annotate(
                    f"4Way Lap Distance: {summary.distance:.3g} in",
                    xy=(summary.mid_x_raw, 0), xytext=(-60, 60),
                    textcoords="offset points", ha="right", va="bottom", color="black",
                    arrowprops=dict(arrowstyle="->", color="black"),
                )
                ann.series_id = test_id
                self.plotter.add_annotation(ann)
                return summary.summary_text

        return ""

    def _handle_no_load(self, test_id: int, data_xy: np.ndarray) -> str:
        r = an.analyse_no_load(data_xy, self.supply_press)

        for label, x, y, color, dy in (
            (f"Max. No Load Drift: {int(r.max_pressure)} psi, {'PASS' if r.max_passed else 'FAIL'}",
             r.x_max, r.max_pressure - self.supply_press * 0.5, "red",  40),
            (f"Min. No Load Drift: {int(r.min_pressure)} psi, {'PASS' if r.min_passed else 'FAIL'}",
             r.x_min, r.min_pressure - self.supply_press * 0.5, "blue", -40),
        ):
            ha = "center"
            dx = 0
            if x > 5.0:
                ha, dx = "right", -20
            elif x < -5.0:
                ha, dx = "left", 20

            ann = self.plotter.ax.annotate(
                label, xy=(x, y), xytext=(dx, dy),
                textcoords="offset points", ha=ha,
                va="bottom" if dy > 0 else "top", color=color,
                arrowprops=dict(arrowstyle="->", color=color),
            )
            ann.series_id = test_id
            self.plotter.add_annotation(ann)

        return r.summary_text

    def _handle_pressure_gain(self, test_id: int, data_xy: np.ndarray) -> str:
        r = an.analyse_pressure_gain(data_xy, self.supply_press)

        pg_line, = self.plotter.ax.plot(
            [r.x_raw_lo, r.x_raw_hi], [r.y_lo, r.y_hi],
            color="green", linestyle="-", linewidth=3,
        )
        self.plotter.add_overlay_series(
            f"pg_slope_{test_id}",
            [float(r.x_raw_lo), float(r.x_raw_hi)],
            [float(r.y_lo),     float(r.y_hi)],
            pg_line,
        )

        ann = self.plotter.ax.annotate(
            f"PG Slope: {abs(r.slope_psi_per_thou):.2g} psi/thou",
            xy=(r.mid_x_raw, r.mid_y), xytext=(60, -60),
            textcoords="offset points", ha="left", va="top", color="green",
            arrowprops=dict(arrowstyle="->", color="green"),
        )
        ann.series_id = test_id
        self.plotter.add_annotation(ann)

        return r.summary_text

    def _handle_leakage(self, test_id: int, data_xy: np.ndarray) -> str:
        r = an.analyse_leakage(data_xy)

        ann = self.plotter.flow_ax.annotate(
            f"Max Leakage: {r.max_leak:g} gpm",
            xy=(r.x_peak, r.y_peak), xytext=(60, 60),
            textcoords="offset points", ha="left", va="bottom", color="purple",
            arrowprops=dict(arrowstyle="->", color="purple"),
        )
        ann.series_id = test_id
        self.plotter.add_annotation(ann)

        return r.summary_text

    # ------------------------------------------------------------------
    # Result text management
    # ------------------------------------------------------------------

    def _append_result_text(self, new_text: str, mode: str) -> None:
        if not new_text:
            return
        line = new_text.strip() + "\n"
        # 3-way results are shown temporarily (not persisted) so they don't
        # clutter the second window
        if mode in ("3way-C1", "3way-C2"):
            self.plotter.part_text.set_text(self._result_text + line)
        else:
            self._result_text += line
            display = self._result_text + f"Test Stand: {TEST_STAND_NUMBER}, Operator:          "
            self.plotter.part_text.set_text(display)
