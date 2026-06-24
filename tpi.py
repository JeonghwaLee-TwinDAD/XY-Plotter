"""
tpi.py
------
TPI — test program interface / orchestrator.

Responsibilities:
  • Own the test sequence (which IDs run under each cycle-menu selection).
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
from matplotlib.widgets import Button

import analysis as an
import style
from config import (
    PART_NUMBER,
    SUPPLY_PRESSURE,
    TEST_SEQUENCE,
    TEST_STAND_NUMBER,
    WINDOW_1_IDS,
    WINDOW_2_IDS,
)
from datalogger import DataLogger
from plotter import XYPlotter
from hardware import HardwareInterface


# ---------------------------------------------------------------------------
# Custom Matplotlib Cycle Button Widget
# ---------------------------------------------------------------------------
# Tag colors matching the design-system TestTag.jsx mapping (ui_qt/theme.py's
# MODE_STYLE): (ink color, soft tint background).
_TAG_STYLE: dict[str, tuple[str, str]] = {
    "3-Way Lap":     (style.BLUE,   style.BLUE_SOFT),
    "All Sequence":  (style.GREY,   style.PANEL),
    "4-Way Lap":     (style.RED,    style.RED_SOFT),
    "No Load Drift": (style.GREY,   style.PANEL_2),
    "Pressure Gain": (style.GREEN,  style.GREEN_SOFT),
    "Leakage":       (style.PURPLE, style.PURPLE_SOFT),
}


class CycleButton:
    """Cycles through test-sequence options, rendered as a colored tag chip
    (dot + colored label) matching the design-system TestTag.jsx look."""

    def __init__(self, ax: plt.Axes, options: tuple, initial: int = 0):
        self.options = options
        self.index = initial
        self.val = self.options[self.index]
        self.btn = Button(ax, self.val)
        self.btn.on_clicked(self._cycle)
        style.style_button(self.btn, fill=style.PANEL, text_color=style.INK)

        self.btn.label.set_ha("left")
        self.btn.label.set_position((0.18, 0.5))
        self.dot, = ax.plot([0.08], [0.5], marker="o", markersize=7,
                             transform=ax.transAxes, clip_on=False)

        self._apply_tag_style()

    def _apply_tag_style(self) -> None:
        ink, soft = _TAG_STYLE.get(self.val, (style.INK, style.PANEL))
        style.recolor_button(self.btn, fill=soft, text_color=ink)
        self.dot.set_color(ink)

    def _cycle(self, _event) -> None:
        self.index = (self.index + 1) % len(self.options)
        self.val = self.options[self.index]
        self.btn.label.set_text(self.val)
        self._apply_tag_style()
        self.btn.ax.figure.canvas.draw_idle()


class TPI:
    """Test orchestrator for the FlowGrind spool-valve test system."""

    def __init__(self, embedded: bool = False) -> None:
        """
        Args:
            embedded: True when hosted inside the PyQt6 Test Station window
                      (ui_qt/main_window.py) rather than driving its own
                      matplotlib Button/RadioButtons UI. The Qt window owns
                      Start/Stop/test-pick controls and calls start_test()/
                      finish_test() instead of execute().
        """
        self._embedded: bool = embedded
        self.supply_press: float = SUPPLY_PRESSURE
        self.part_number: str   = PART_NUMBER   # editable via the plotter's P/N field
        self.serial_number: str  = ""           # set by operator before postUUT()
        self._x_intercepts: Dict[str, float]    = {}
        self._is_executing: bool                 = False
        self._test_selector: Optional[CycleButton] = None

        # Running text for the info box; accumulates across all tests
        self._result_text: str = ""

        # Non-blocking (Qt) acquisition state — see start_test()/finish_test().
        self._sweep_thread = None
        self._pending_test_id: Optional[int] = None
        self._pending_mode: Optional[str] = None
        self._last_result_text: str = ""
        self._last_passed: Optional[bool] = None

        self.plotter = self._make_plotter(update_interval=50)
        self.hw = HardwareInterface()
        # Indicators stay live (read straight from the DAQ) whenever no
        # sweep is running, instead of sitting at "--" between tests.
        self.plotter.idle_reader = self.hw.read_all_channels
        # Panel lamp: "DAQ Ready" once the channels are connected, "Out of
        # Tol" until then; "Acquiring" takes over automatically while a
        # sweep is running (see XYPlotter.start()).
        self.plotter.is_channels_ready = lambda: self.hw.daq_task is not None

    # ------------------------------------------------------------------
    # Plotter lifecycle helpers
    # ------------------------------------------------------------------

    def _make_plotter(self, update_interval: int) -> XYPlotter:
        p = XYPlotter(update_interval=update_interval, embedded=self._embedded)
        p.set_window_title(f"FlowGrind | Test Stand: {TEST_STAND_NUMBER}")
        p.set_part_info(self.part_number, self.serial_number)
        p.on_part_number_change = self._on_part_number_change
        p.part_text.set_text(self._result_text)

        if self._embedded:
            # The Qt MainWindow owns Start/Stop, the test-sequence picker,
            # and the window close/key handlers — nothing further to wire up.
            self._test_selector = None
            return p

        p.btn_run.on_clicked(self._on_restart)
        p.fig.canvas.mpl_connect("close_event", self._on_window_close)
        p.fig.canvas.mpl_connect("key_press_event", self._on_key)

        # Adjust top margin to make room above the plot.
        p.fig.subplots_adjust(top=0.9)
        # Align both buttons with the graph outline — right edge flush with
        # the axes' right spine, bottom edge a fixed gap above its top spine —
        # recomputed from the axes' own (fraction-based) position on every
        # resize, so the alignment holds at any window size. Same height as
        # the Spool Pos./Zero/P-N row so everything reads as one toolbar strip.
        style.pin_axes_flush(p.fig, p.btn_run.ax, width_px=90, height_px=34,
                              above=p.ax, gap_top_px=8)

        ax_cycle_btn = p.fig.add_axes([0.60, 0.86, 0.18, 0.05])
        style.pin_axes_flush(p.fig, ax_cycle_btn, width_px=180, height_px=34,
                              right_of=p.btn_run.ax, gap_right_px=8,
                              above=p.ax, gap_top_px=8)

        self._test_selector = CycleButton(
            ax_cycle_btn,
            ("3-Way Lap", "All Sequence", "4-Way Lap", "No Load Drift", "Pressure Gain", "Leakage")
        )

        return p

    def _on_window_close(self, _event) -> None:
        self.postUUT()

    def _on_key(self, event) -> None:
        """Handle keyboard shortcuts mirroring button clicks."""
        key = str(getattr(event, "key", "") or "").lower()
        if key == "f8":
            self._on_restart(event)

    def _on_restart(self, _event) -> None:
        """Run all tests in the sequence when the operator clicks Start."""
        if not self.plotter.is_running or self._is_executing:
            return

        selection = self._test_selector.val if self._test_selector else "All Sequence"
        if selection == "3-Way Lap":
            group = WINDOW_1_IDS
        elif selection == "4-Way Lap":
            group = (2,)
        elif selection == "No Load Drift":
            group = (3,)
        elif selection == "Pressure Gain":
            group = (4,)
        elif selection == "Leakage":
            group = (5,)
        else:
            group = WINDOW_2_IDS

        self.plotter.clear()
        self._result_text = ""
        self._x_intercepts.clear()
        self.plotter.part_text.set_text("")

        if not self.plotter.is_running:
            self.plotter.start()

        for tid in group:
            if not self.plotter.is_running or self.plotter.abort_event.is_set():
                break
            self.execute(tid)
            
        if self.plotter.is_running:
            self.plotter.set_ready()

    # ------------------------------------------------------------------
    # Test lifecycle (matches original LabVIEW convention)
    # ------------------------------------------------------------------

    def startup(self) -> None:
        """System-level initialisation (hardware power-on, self-test, etc.)."""
        self.hw.connect_daq()

    def preUUT(self) -> None:
        """Part-level setup before the first test run."""
        print(f"\n--- FlowGrind Setup | P/N: {self.part_number} ---")
        self.serial_number = input("Enter Serial Number: ").strip()
        self.plotter.set_part_info(self.part_number, self.serial_number)

    def _on_part_number_change(self, value: str) -> None:
        """Called when the operator edits P/N in the plotter's TextBox."""
        if value:
            self.part_number = value

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
            title = f"{cfg.title} | Test Stand: {TEST_STAND_NUMBER}"
            self.plotter.set_window_title(title)
            self._acquire(test_id, cfg.mode)
            if self.plotter.is_running:
                self._analyse_and_annotate(test_id, cfg.mode)
        finally:
            self._is_executing = False

    # ------------------------------------------------------------------
    # Non-blocking acquisition (Qt host) — start_test() / is_test_acquiring()
    # / finish_test() replace execute()'s plt.pause()-driven busy-wait so the
    # PyQt6 Test Station can poll on its own QTimer instead of pumping
    # matplotlib's event loop from a background thread.
    # ------------------------------------------------------------------

    def start_test(self, test_id: int) -> None:
        """Begin acquisition for *test_id*; non-blocking. Poll with
        is_test_acquiring() and collect results with finish_test()."""
        cfg = TEST_SEQUENCE[test_id]
        title = f"{cfg.title} | Test Stand: {TEST_STAND_NUMBER}"
        self.plotter.set_window_title(title)
        if not self.plotter.is_running:
            self.plotter.start()
        self._pending_test_id = test_id
        self._pending_mode = cfg.mode
        self._sweep_thread = self.hw.sweep_spool(
            test_id, cfg.mode, self.plotter.data_queue, self.plotter.abort_event,
        )

    def is_test_acquiring(self) -> bool:
        """True while the test started by start_test() is still producing data."""
        if self._sweep_thread is None:
            return False
        return self._sweep_thread.is_alive() or not self.plotter.data_queue.empty()

    def finish_test(self) -> tuple[str, Optional[bool]]:
        """
        Call once is_test_acquiring() returns False. Runs analysis/annotation
        for the test started by start_test() and returns (result_text, passed).
        passed is None for tests with no single pass/fail judgement (3-way laps).
        """
        test_id, mode = self._pending_test_id, self._pending_mode
        self._sweep_thread = None
        self._pending_test_id = None
        self._pending_mode = None
        if test_id is None or not self.plotter.is_running:
            return "", None
        self._analyse_and_annotate(test_id, mode)
        return self._last_result_text, self._last_passed

    def postUUT(self) -> None:
        """Post-test teardown: save data, prompt operator, release fixture."""
        DataLogger().save(
            series_data=self.plotter.series_data,
            part_number=self.part_number,
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

    def _annotate(self, ann: plt.Annotation, test_id: int) -> None:
        """Tag a freshly-created annotation with its series and register it."""
        ann.series_id = test_id
        self.plotter.add_annotation(ann)

    # ------------------------------------------------------------------
    # Analysis dispatch and annotation
    # ------------------------------------------------------------------

    def _analyse_and_annotate(self, test_id: int, mode: str) -> None:
        """Run the correct analysis for *mode* and push results to the plotter."""
        self._last_passed = None
        data_xy = self.plotter.get_series_xy(test_id)
        if data_xy is None:
            self._last_result_text = ""
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

        self._last_result_text = result_text
        self._append_result_text(result_text, mode)

    # ------------------------------------------------------------------
    # Per-mode analysis + annotation helpers
    # ------------------------------------------------------------------

    def _handle_lap(self, test_id: int, mode: str, data_xy: np.ndarray) -> str:
        result = an.analyse_lap(data_xy)

        for direction, reg, color, marker in (
            ("up",   result.up,   style.BLUE, "o"),
            ("down", result.down, style.RED,  "s"),
        ):
            if reg is None:
                continue

            # Masked points
            pts = reg.masked_xy
            ax  = self.plotter.flow_ax
            line, = ax.plot(
                pts[:, 0], pts[:, 1],
                marker=marker, markersize=4, color=color,
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
            fit_line, = ax.plot(x_vals, y_vals, color=style.INK, linestyle="--")
            self.plotter.add_overlay_series(
                f"fit_{direction}_{test_id}",
                x_vals.tolist(), y_vals.tolist(), fit_line,
            )

            # X-intercept marker
            pt, = ax.plot([x_int], [0], marker=marker, color=color, markersize=6, linestyle="None")
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
                self._last_passed = summary.passed
                ann = self.plotter.flow_ax.annotate(
                    f"4Way Lap Distance: {summary.distance:.3g} in",
                    xy=(summary.mid_x_raw, 0), xytext=(-90, 70),
                    textcoords="offset points", ha="right", va="bottom", color=style.INK,
                    arrowprops=dict(arrowstyle="->", color=style.INK),
                )
                self._annotate(ann, test_id)
                return summary.summary_text

        return ""

    def _handle_no_load(self, test_id: int, data_xy: np.ndarray) -> str:
        r = an.analyse_no_load(data_xy, self.supply_press)
        self._last_passed = r.passed

        for label, x, y, color, dx, dy in (
            (f"Max. No Load Drift: {int(r.max_pressure)} psi, {'PASS' if r.max_passed else 'FAIL'}",
             r.x_max, r.max_pressure - self.supply_press * 0.5, style.RED, -90, -60),
            (f"Min. No Load Drift: {int(r.min_pressure)} psi, {'PASS' if r.min_passed else 'FAIL'}",
             r.x_min, r.min_pressure - self.supply_press * 0.5, style.BLUE, -80, -20),
        ):
            ha = "left" if dx > 0 else "right"

            ann = self.plotter.ax.annotate(
                label, xy=(x, y), xytext=(dx, dy),
                textcoords="offset points", ha=ha,
                va="bottom" if dy > 0 else "top", color=color,
                arrowprops=dict(arrowstyle="->", color=color),
            )
            self._annotate(ann, test_id)

        return r.summary_text

    def _handle_pressure_gain(self, test_id: int, data_xy: np.ndarray) -> str:
        r = an.analyse_pressure_gain(data_xy, self.supply_press)
        self._last_passed = r.passed

        pg_line, = self.plotter.ax.plot(
            [r.x_raw_lo, r.x_raw_hi], [r.y_lo, r.y_hi],
            color=style.GREEN, linestyle="-", linewidth=3,
        )
        self.plotter.add_overlay_series(
            f"pg_slope_{test_id}",
            [float(r.x_raw_lo), float(r.x_raw_hi)],
            [float(r.y_lo),     float(r.y_hi)],
            pg_line,
        )

        ann = self.plotter.ax.annotate(
            f"PG Slope: {abs(r.slope_psi_per_thou):.2g} psi/thou",
            xy=(r.mid_x_raw, r.mid_y), xytext=(-65, -40),
            textcoords="offset points", ha="right", va="top", color=style.GREEN,
            arrowprops=dict(arrowstyle="->", color=style.GREEN),
        )
        self._annotate(ann, test_id)

        return r.summary_text

    def _handle_leakage(self, test_id: int, data_xy: np.ndarray) -> str:
        r = an.analyse_leakage(data_xy)
        self._last_passed = r.passed

        ann = self.plotter.flow_ax.annotate(
            f"Max Leakage: {r.max_leak:g} gpm",
            xy=(r.x_peak, r.y_peak), xytext=(60, 20),
            textcoords="offset points", ha="left", va="bottom", color=style.PURPLE,
            arrowprops=dict(arrowstyle="->", color=style.PURPLE),
        )
        self._annotate(ann, test_id)

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
