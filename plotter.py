"""
plotter.py
----------
XYPlotter — a reusable, thread-safe live XY plotting widget built on
matplotlib FuncAnimation.

Design pattern (mirrors LabVIEW QMH + Producer/Consumer):
  • _event_loop thread  → Producer.  Handles discrete UI commands via
    event_queue; performs cyclic data polling on queue.Empty timeout
    (equivalent to a LabVIEW Event Structure Timeout case).
  • update_plot()       → Consumer.  Called by FuncAnimation on the GUI
    thread; drains data_queue and repaints the canvas without blocking.

This class knows nothing about valve modes, pass/fail criteria, or part
numbers.  All test-specific logic lives in TPI (tpi.py).
"""

from __future__ import annotations

import queue
import threading
import time
from typing import Dict, List, Optional, Tuple

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.animation import FuncAnimation
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from matplotlib.widgets import Button

from config import FLOW_LIMIT, STROKE, SUPPLY_PRESSURE

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
# Series IDs routed to the primary (pressure) axis rather than the flow axis.
# Override by passing pressure_series_ids to XYPlotter.__init__().
_DEFAULT_PRESSURE_IDS: frozenset = frozenset({3, 4})

# ---------------------------------------------------------------------------
# Internal type aliases
# ---------------------------------------------------------------------------
SeriesKey = int | str          # raw int for live data; str for overlay artists
DataPoint = Tuple[SeriesKey, float, float]


class XYPlotter:
    """Live XY plotter with a QMH-style background event/poll loop."""

    # ------------------------------------------------------------------
    # Construction / layout
    # ------------------------------------------------------------------

    def __init__(
        self,
        update_interval: int = 10,
        pressure_series_ids: frozenset = _DEFAULT_PRESSURE_IDS,
    ) -> None:
        """
        Args:
            update_interval:     FuncAnimation frame interval in milliseconds.
                                 Use ~10 ms for fast sweeps, ~50 ms for slow ones.
            pressure_series_ids: Series IDs that belong on the primary pressure
                                 axis.  All other integer IDs go to flow_ax.
        """
        self._interval = update_interval
        self._pressure_ids = pressure_series_ids

        self._build_figure()
        self._build_layout()
        self._init_state()
        self._start_background_thread()
        self._start_animation()

    def _build_figure(self) -> None:
        self.fig: Figure
        self.ax:  Axes
        self.fig, self.ax = plt.subplots(figsize=(10, 5), dpi=100)

        plt.subplots_adjust(top=0.92, bottom=0.1, left=0.1, right=0.92)
        self.ax.grid(False)

        # Connect canvas events
        self.fig.canvas.mpl_connect("close_event", self._on_close)
        self.fig.canvas.mpl_connect("key_press_event", self._on_key)

    def _build_layout(self) -> None:
        """Axes labels, ticks, secondary axis, reference lines, buttons."""
        self.fig.canvas.manager.set_window_title("FlowGrind - XY Plotter")

        # Primary axis  (pressure / position)
        self.ax.set_xlabel("Spool Position (in)")
        self.ax.set_xlim(-STROKE, STROKE)
        self.ax.set_xticks(np.arange(-STROKE, STROKE, STROKE / 4))
        self.ax.set_ylabel("Pressure (psi)")
        self.ax.set_ylim(-SUPPLY_PRESSURE, SUPPLY_PRESSURE)
        self.ax.set_yticks(np.arange(-SUPPLY_PRESSURE, SUPPLY_PRESSURE, SUPPLY_PRESSURE / 3))

        # Secondary axis  (flow)
        self.flow_ax: Axes = self.ax.twinx()
        self.flow_ax.set_ylabel("Flow (gpm)")
        self.flow_ax.set_ylim(-FLOW_LIMIT, FLOW_LIMIT)
        self.flow_ax.set_yticks(np.linspace(-FLOW_LIMIT, FLOW_LIMIT, 7))

        # Quadrant labels
        for label, (x, y) in {"D": (0.95, 0.9), "B": (0.05, 0.9),
                               "A": (0.95, 0.1), "C": (0.05, 0.1)}.items():
            self.ax.annotate(label, xy=(x, y), xycoords="axes fraction",
                             fontsize=14, fontweight="bold", color="lightgray",
                             ha="center", va="center")

        # Horizontal reference lines on flow axis
        for frac in (0.1, 0.3):
            self.flow_ax.axhline(y= FLOW_LIMIT * frac, color="lightgray", linestyle="--", linewidth=1)
            self.flow_ax.axhline(y=-FLOW_LIMIT * frac, color="lightgray", linestyle="--", linewidth=1)

        # Info text box (upper-right quadrant of axes)
        self.part_text = self.ax.text(
            0.52, 0.98, "",
            transform=self.ax.transAxes,
            fontsize=10, family="monospace",
            verticalalignment="top",
            bbox=dict(boxstyle="square, pad=0.5",
                      facecolor="white", edgecolor="white", linewidth=1),
        )

        # Timing diagnostic (upper-left)
        self.timing_text = self.ax.text(
            0.01, 0.99, "Plot Loop: -- ms",
            transform=self.ax.transAxes,
            fontsize=8, family="monospace",
            verticalalignment="top", color="gray",
        )

        # Live value diagnostic (below timing)
        self.live_val_text = self.ax.text(
            0.01, 0.96, "",
            transform=self.ax.transAxes,
            fontsize=8, family="monospace",
            verticalalignment="top", color="tab:red",
        )

        # Buttons
        ax_run   = plt.axes([0.66, 0.93, 0.12, 0.05])
        ax_clear = plt.axes([0.80, 0.93, 0.12, 0.05])
        self.btn_run   = Button(ax_run,   "Start")
        self.btn_clear = Button(ax_clear, "Clear")
        self.btn_run.on_clicked(self._toggle_run)
        self.btn_clear.on_clicked(self.clear)

    def _init_state(self) -> None:
        """Initialise all mutable state containers."""
        # series_data: persistent store for every plotted series
        self.series_data: Dict[SeriesKey, Dict[str, list]] = {}
        # lines: matplotlib Line2D objects keyed by series_id
        self.lines: Dict[SeriesKey, plt.Line2D] = {}
        # dynamic_annotations: post-sweep artist list (cleared on reset)
        self.dynamic_annotations: List[plt.Annotation] = []

        self.is_running: bool = False
        self._last_frame_time: float = time.time()

        self._base_window_title: str = "FlowGrind - XY Plotter"
        self._last_timestamp: str = ""

        # Thread-safe queues
        self.data_queue:  queue.Queue[DataPoint] = queue.Queue()
        self.event_queue: queue.Queue[dict]      = queue.Queue()

        # Live tracking dots for the active sweep
        self.live_point_ax, = self.ax.plot([], [], marker="o", color="red", markersize=6, zorder=10)
        self.live_point_flow, = self.flow_ax.plot([], [], marker="o", color="red", markersize=6, zorder=10)

        # Thread lifecycle
        self._stop_event = threading.Event()
        self.abort_event = threading.Event()

    @property
    def stop_event(self) -> threading.Event:
        """Public handle so callers can check/wait without touching internals."""
        return self._stop_event

    # ------------------------------------------------------------------
    # Background thread (Producer / QMH event loop)
    # ------------------------------------------------------------------

    def _start_background_thread(self) -> None:
        self._event_thread = threading.Thread(
            target=self._event_loop, daemon=True
        )
        self._event_thread.start()

    def _event_loop(self) -> None:
        """
        LabVIEW-style QMH event loop.

        • Blocking get(timeout=...) handles discrete commands immediately.
        • queue.Empty branch == Timeout case: perform cyclic simulation poll.
        """
        while not self._stop_event.is_set():
            try:
                cmd_dict = self.event_queue.get(timeout=self._interval / 1000.0)
                self._handle_command(cmd_dict)
            except queue.Empty:
                pass

    def _handle_command(self, cmd_dict: dict) -> None:
        cmd = cmd_dict.get("cmd", "")
        if cmd == "START":
            with self.data_queue.mutex:
                self.data_queue.queue.clear()
        elif cmd == "EXIT":
            self._stop_event.set()

    # ------------------------------------------------------------------
    # FuncAnimation consumer
    # ------------------------------------------------------------------

    def _start_animation(self) -> None:
        self.anim = FuncAnimation(
            self.fig,
            self._update_plot,
            interval=self._interval,
            blit=False,
            cache_frame_data=False,
        )

    def _update_plot(self, _frame) -> list:
        """Drain data_queue, update line data, refresh timing display."""
        now = time.time()
        loop_ms = (now - self._last_frame_time) * 1000
        self._last_frame_time = now
        self.timing_text.set_text(f"Plot Loop: {loop_ms:.1f} ms")

        current_timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        if current_timestamp != self._last_timestamp:
            self._last_timestamp = current_timestamp
            self.fig.canvas.manager.set_window_title(f"{self._base_window_title} | {current_timestamp}")

        has_new = False
        last_x, last_y = None, None
        last_sid = None
        while True:
            try:
                series_id, x, y = self.data_queue.get_nowait()
                self._ensure_series(series_id)
                self.series_data[series_id]["X"].append(x)
                self.series_data[series_id]["Y"].append(y)
                has_new = True
                last_x, last_y = x, y
                last_sid = series_id
            except queue.Empty:
                break

        if has_new:
            for sid, line in self.lines.items():
                d = self.series_data[sid]
                line.set_data(d["X"], d["Y"])
            
            if last_x is not None and last_y is not None and last_sid is not None:
                if last_sid in self._pressure_ids:
                    self.live_val_text.set_text(f"X: {last_x:.3f} | Press: {last_y:.1f}")
                    self.live_point_ax.set_data([last_x], [last_y])
                    self.live_point_flow.set_data([], [])
                else:
                    self.live_val_text.set_text(f"X: {last_x:.3f} | Flow: {last_y:.1f}")
                    self.live_point_flow.set_data([last_x], [last_y])
                    self.live_point_ax.set_data([], [])

        return list(self.lines.values()) + [self.part_text, self.timing_text, self.live_val_text, self.live_point_ax, self.live_point_flow] + self.dynamic_annotations

    def _ensure_series(self, series_id: SeriesKey) -> None:
        """Create series_data entry and a blank Line2D on first encounter."""
        if series_id in self.series_data:
            return
        self.series_data[series_id] = {"X": [], "Y": []}
        color = "grey"
        ax = self.ax if series_id in self._pressure_ids else self.flow_ax
        line, = ax.plot(
            [], [], marker="s", markersize=5, color=color,
            linewidth=0, markerfacecolor="white", markeredgecolor=color,
        )
        self.lines[series_id] = line

    # ------------------------------------------------------------------
    # Public control API
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start (or resume) data acquisition."""
        self.is_running = True
        self.abort_event.clear()
        self.btn_run.label.set_text("Stop")
        self.event_queue.put({"cmd": "START"})

    def stop(self) -> None:
        """Pause data acquisition without resetting state."""
        self.is_running = False
        self.abort_event.set()
        self.btn_run.label.set_text("Start")
        self.live_val_text.set_text("")
        self.live_point_ax.set_data([], [])
        self.live_point_flow.set_data([], [])
        self.event_queue.put({"cmd": "STOP"})

    def _set_btn_run_state(self, *, active: bool) -> None:
        """Configure the Run button's active state and matching label colour."""
        self.btn_run.label.set_text("Start")
        self.btn_run.set_active(active)
        self.btn_run.label.set_color("black" if active else "grey")
        self.fig.canvas.draw_idle()

    def set_idle(self) -> None:
        """Disable the run button after a test completes."""
        self.is_running = False
        self._set_btn_run_state(active=False)
        self.live_point_ax.set_data([], [])
        self.live_point_flow.set_data([], [])
        self.live_val_text.set_text("")

    def set_ready(self) -> None:
        """Re-enable the run button (e.g. after loading new data)."""
        self.is_running = False
        self._set_btn_run_state(active=True)
        self.live_point_ax.set_data([], [])
        self.live_point_flow.set_data([], [])
        self.live_val_text.set_text("")

    def clear(self, _event=None) -> None:
        """Reset all plotted data, annotations, and result text."""
        self.set_ready()

        for k in self.series_data:
            self.series_data[k] = {"X": [], "Y": []}
            if k in self.lines:
                self.lines[k].set_data([], [])

        for ann in self.dynamic_annotations:
            try:
                ann.remove()
            except ValueError:
                pass
        self.dynamic_annotations.clear()

        with self.data_queue.mutex:
            self.data_queue.queue.clear()

        # Preserve only header lines (up to and including "Supply Press:")
        text = self.part_text.get_text()
        header_lines = []
        for line in text.split("\n"):
            header_lines.append(line)
            if "Supply Press:" in line:
                break
        self.part_text.set_text("\n".join(header_lines) + "\n")
        self.live_val_text.set_text("")
        self.live_point_ax.set_data([], [])
        self.live_point_flow.set_data([], [])
        self.fig.canvas.draw_idle()

    def get_series_xy(self, series_id: SeriesKey) -> Optional[np.ndarray]:
        """
        Return a clean (N, 2) float array for *series_id*, or None.

        Rows containing NaN are removed.  Returns None when no data exists
        or all rows are invalid.
        """
        entry = self.series_data.get(series_id)
        if not entry or not entry["X"]:
            return None
        arr = np.column_stack((entry["X"], entry["Y"]))
        arr = arr[~np.isnan(arr).any(axis=1)]
        return arr if len(arr) > 0 else None

    def add_overlay_series(
        self,
        key: str,
        x: list,
        y: list,
        artist: plt.Artist,
    ) -> None:
        """Register an overlay line (fit, mask, intercept) so it is tracked."""
        self.series_data[key] = {"X": x, "Y": y}
        self.lines[key] = artist

    def add_annotation(self, ann: plt.Annotation) -> None:
        """Register a dynamic annotation for lifecycle management."""
        self.dynamic_annotations.append(ann)

    def set_window_title(self, title: str) -> None:
        self._base_window_title = title
        self._last_timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        self.fig.canvas.manager.set_window_title(f"{self._base_window_title} | {self._last_timestamp}")

    # ------------------------------------------------------------------
    # Internal event handlers
    # ------------------------------------------------------------------

    def _toggle_run(self, _event) -> None:
        if self.is_running:
            self.stop()
        else:
            self.start()

    def _on_close(self, _event) -> None:
        self._stop_event.set()
        self.abort_event.set()
        self.event_queue.put({"cmd": "EXIT"})
        self.is_running = False
        if getattr(self.anim, "event_source", None) is not None:
            self.anim.event_source.stop()

    def _on_key(self, event) -> None:
        key = str(getattr(event, "key", "") or "").lower()
        if key == "f8":
            self._toggle_run(event)
        elif key == "f4":
            try:
                plt.close(self.fig)
            except Exception:
                pass
