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
from typing import Callable, Dict, List, Optional, Tuple

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.animation import FuncAnimation
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from matplotlib.widgets import Button, TextBox

import style
from config import FLOW_LIMIT, STROKE, SUPPLY_PRESSURE

style.apply_theme()

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
DataPoint = Tuple[SeriesKey, float, float, float, float]   # id, x, y, flow, pressure


class _TkLabelText:
    """Adapts a Tk Label to the same `.set_text(...)` interface as a
    matplotlib Text, so callers don't need to care which one they have."""

    def __init__(self, label) -> None:
        self._label = label

    def set_text(self, s: str) -> None:
        self._label.configure(text=s)


class XYPlotter:
    """Live XY plotter with a QMH-style background event/poll loop."""

    # ------------------------------------------------------------------
    # Construction / layout
    # ------------------------------------------------------------------

    def __init__(
        self,
        update_interval: int = 10,
        pressure_series_ids: frozenset = _DEFAULT_PRESSURE_IDS,
        embedded: bool = False,
    ) -> None:
        """
        Args:
            update_interval:     FuncAnimation frame interval in milliseconds.
                                 Use ~10 ms for fast sweeps, ~50 ms for slow ones.
            pressure_series_ids: Series IDs that belong on the primary pressure
                                 axis.  All other integer IDs go to flow_ax.
            embedded:            True when the Figure is hosted inside another
                                 toolkit's window (e.g. a PyQt6 FigureCanvas).
                                 Skips the matplotlib Run button and window-title
                                 management, which the host window owns instead.
        """
        self._interval = update_interval
        self._pressure_ids = pressure_series_ids
        self._embedded = embedded

        self._build_figure()
        self._build_layout()
        self._init_state()
        self._start_background_thread()
        self._start_animation()

    def _build_figure(self) -> None:
        self.fig: Figure
        self.ax:  Axes
        self.fig, self.ax = plt.subplots(figsize=(10, 5), dpi=100)

        plt.subplots_adjust(top=0.9, bottom=0.1, left=0.1, right=0.92)
        self.ax.grid(False)

        self._lamps_frame = None
        self._toolbar_center_frame = None
        self._set_daq_status = lambda _name: None
        if not self._embedded:
            style.style_toolbar(self.fig)
            self._lamps_frame, self._set_daq_status = style.add_status_lamp(
                self.fig,
                {
                    "Acquiring":  style.BLUE,
                    "DAQ Ready":  style.GREEN,
                    "Out of Tol": style.AMBER,
                    "Standby":    style.GREY,
                },
                initial="Standby",
            )
            self._toolbar_center_frame = style.add_toolbar_center_frame(self.fig)

        # Connect canvas events
        self.fig.canvas.mpl_connect("close_event", self._on_close)
        self.fig.canvas.mpl_connect("key_press_event", self._on_key)

    def _build_layout(self) -> None:
        """Axes labels, ticks, secondary axis, reference lines, buttons."""
        if not self._embedded:
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
        self.flow_ax.set_yticks(np.linspace(-FLOW_LIMIT, FLOW_LIMIT, 5))
        self.flow_ax.grid(False)

        # Disable the toolbar's "x=... y=..." cursor coordinate readout —
        # the indicator cards/live value line cover that need.
        self.ax.format_coord = lambda x, y: ""
        self.flow_ax.format_coord = lambda x, y: ""

        # Quadrant labels
        for label, (x, y) in {"D": (0.95, 0.9), "B": (0.05, 0.9),
                               "A": (0.95, 0.1), "C": (0.05, 0.1)}.items():
            self.ax.annotate(label, xy=(x, y), xycoords="axes fraction",
                             fontsize=14, fontweight="bold", color=style.GREY,
                             ha="center", va="center")

        # Horizontal reference lines on flow axis
        for frac in (0.1, 0.3):
            self.flow_ax.axhline(y= FLOW_LIMIT * frac, color=style.GRID, linestyle="--", linewidth=1)
            self.flow_ax.axhline(y=-FLOW_LIMIT * frac, color=style.GRID, linestyle="--", linewidth=1)

        # Info text box (pinned to the upper-right corner of the axes)
        self.part_text = self.ax.text(
            0.98, 0.95, "",
            transform=self.ax.transAxes,
            fontsize=10, family="monospace",
            verticalalignment="top", horizontalalignment="right",
            multialignment="left", color=style.INK,
            bbox=dict(boxstyle="square,pad=0.5",
                      facecolor=style.PLOT_BG, edgecolor="none", linewidth=0),
        )

        # Timing diagnostic — centered in the toolbar, independent of the
        # status lamp (which sits on the toolbar's right), when available
        # (real Tk window); otherwise (embedded/no toolbar) fall back to
        # figure-level text.
        if self._toolbar_center_frame is not None:
            self.timing_text = _TkLabelText(
                style.add_toolbar_label(self._toolbar_center_frame, color=style.GREY)
            )
            self.timing_text.set_text("Plot Loop: -- ms")
        else:
            self.timing_text = self.fig.text(
                0.998, 0.03, "Plot Loop: -- ms",
                fontsize=8, family="monospace",
                verticalalignment="bottom", horizontalalignment="right", color=style.GREY,
            )

        # Part/serial identification — centered at the top of the graph.
        # P/N is an editable TextBox (operator can correct it without
        # restarting); S/N stays plain text (set via preUUT()'s prompt).
        # Skipped when embedded — the Qt host already shows P/N in its own
        # topbar — which keeps the old combined static-text display instead.
        self.on_part_number_change: Optional[Callable[[str], None]] = None
        if not self._embedded:
            self.part_id_text = None
            self.sn_text = self.fig.text(
                0.48, 0.95, "",
                fontsize=8, family="monospace", fontweight="bold",
                verticalalignment="center", horizontalalignment="left", color=style.INK,
            )
            style.pin_text_top_left(self.fig, self.sn_text, x_px=510, top_px=25)
            ax_pn = self.fig.add_axes([0.36, 0.916, 0.14, 0.068])
            self.pn_textbox = TextBox(ax_pn, "P/N: ", initial="")
            self.pn_textbox.label.set_fontsize(8)
            self.pn_textbox.label.set_color(style.GREY)
            self.pn_textbox.text_disp.set_fontsize(8)
            self.pn_textbox.text_disp.set_fontweight("bold")
            ax_pn.patch.set_edgecolor("none")
            ax_pn.patch.set_linewidth(0)
            for spine in ax_pn.spines.values():
                spine.set_visible(False)
            self.pn_textbox.on_submit(self._on_pn_submit)
            style.pin_axes_top_left(
                self.fig, ax_pn, width_px=140, height_px=34, left_px=360, top_px=8,
            )
        else:
            self.pn_textbox = None
            self.sn_text = None
            self.part_id_text = self.fig.text(
                0.998, 0.005, "",
                fontsize=8, family="monospace", fontweight="bold",
                verticalalignment="bottom", horizontalalignment="right", color=style.INK,
            )

        # Live indicators — Spool/Pressure/Flow. Pressure+Flow combine into a
        # single "2,987 psi · 0.03 gpm" readout packed into the toolbar
        # (left side, next to the default Home/Pan/Zoom/Save buttons) when
        # available (real Tk window); Spool Pos. stays as a fixed-pixel-size
        # card pinned above the graph. Embedded/no-toolbar windows fall back
        # to separate cards for all three.
        specs = (
            ("spool",    "Spool Pos.", "in",  style.INK),
            ("pressure", "Pressure",   "psi", style.RED),
            ("flow",     "Flow",       "gpm", style.BLUE),
        )
        self._indicator_values: Dict[str, object] = {}
        card_specs = specs
        if self._lamps_frame is not None:
            self._pressure_flow_text = _TkLabelText(
                style.add_toolbar_combo_readout(self.fig, color=style.INK)
            )
            card_specs = specs[:1]
        else:
            self._pressure_flow_text = None

        if card_specs:
            card_w_px, card_h_px, gap_px, left_px = 160, 34, 10, 100
            for i, (key, label, unit, color) in enumerate(card_specs):
                card_ax, value_text = style.draw_indicator_card(
                    self.fig, [0.1, 0.9, 0.1, 0.05], label, unit, color
                )
                style.pin_axes_top_left(
                    self.fig, card_ax, width_px=card_w_px, height_px=card_h_px,
                    left_px=left_px + i * (card_w_px + gap_px), top_px=8,
                )
                self._indicator_values[key] = value_text

            # "Zero" button — resets the Spool Pos. readout to 0.000, right
            # next to its card. Only when nothing else occupies that slot:
            # skipped when embedded (host owns controls) or when the
            # no-toolbar fallback shows all three cards side by side.
            if not self._embedded and len(card_specs) == 1:
                ax_zero = self.fig.add_axes([0.1, 0.9, 0.05, 0.05])
                self.btn_zero_spool = Button(ax_zero, "Zero")
                self.btn_zero_spool.on_clicked(self._zero_spool_pos)
                style.style_button(self.btn_zero_spool, fill=style.PANEL_2, text_color=style.INK,
                                    bold=False, fontsize=8)
                style.pin_axes_top_left(
                    self.fig, ax_zero, width_px=50, height_px=card_h_px,
                    left_px=left_px + card_w_px + gap_px, top_px=8,
                )

        # Buttons (skipped when embedded — the host window owns Start/Stop)
        if self._embedded:
            self.btn_run = None
        else:
            ax_run   = self.fig.add_axes([0.80, 0.93, 0.12, 0.05])
            self.btn_run   = Button(ax_run,   "Start")
            self.btn_run.on_clicked(self._toggle_run)
            style.style_button(self.btn_run, fill=style.GREEN, hover=style.GREEN_DARK, text_color="#FFFFFF", bold=False, fontsize=9)
            style.pin_axes_top_right(self.fig, ax_run, width_px=90, height_px=26, right_px=20, top_px=15)

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

        # Most recent (series_id, x, y) drained by _update_plot — lets host
        # UIs (e.g. ui_qt) show a live readout.
        self.last_point: Optional[DataPoint] = None

        # Optional callable () -> (x, flow, pressure), polled every animation
        # frame while idle (no sweep running) so the indicators show live
        # sensor values even between tests, not just "--". Set by the host
        # (e.g. TPI.hw.read_all_channels) — left None disables idle polling.
        self.idle_reader: Optional[Callable[[], Tuple[float, float, float]]] = None

        # Optional callable () -> bool reporting whether the DAQ channels
        # are connected/healthy. Drives the panel lamp's "DAQ Ready" vs.
        # "Out of Tol" state while idle. Set by the host (e.g. TPI).
        self.is_channels_ready: Optional[Callable[[], bool]] = None

        self._base_window_title: str = "FlowGrind - XY Plotter"
        self._last_timestamp: str = ""

        # Thread-safe queues
        self.data_queue:  queue.Queue[DataPoint] = queue.Queue()
        self.event_queue: queue.Queue[dict]      = queue.Queue()

        # Live tracking dots for the active sweep
        self.live_point_ax, = self.ax.plot([], [], marker="o", color=style.RED, markersize=5, zorder=10)
        self.live_point_flow, = self.flow_ax.plot([], [], marker="o", color=style.RED, markersize=5, zorder=10)

        # Thread lifecycle
        self._stop_event = threading.Event()
        self.abort_event = threading.Event()

    @property
    def pressure_ids(self) -> frozenset:
        """Series IDs routed to the pressure axis rather than the flow axis."""
        return self._pressure_ids

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

    def _update_plot(self, _frame) -> None:
        """Drain data_queue, update line data, refresh timing display."""
        try:
            self._update_plot_impl()
        except Exception as exc:
            # FuncAnimation stops calling this callback forever if it ever
            # raises — that silently halts all plotting with no error shown
            # to the operator. Log and keep going instead.
            print(f"[Plotter] _update_plot frame failed, skipping: {exc}")

    def _update_plot_impl(self) -> None:
        now = time.time()
        loop_ms = (now - self._last_frame_time) * 1000
        self._last_frame_time = now
        self.timing_text.set_text(f"Plot Loop: {loop_ms:.1f} ms")

        current_timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        if current_timestamp != self._last_timestamp:
            self._last_timestamp = current_timestamp
            if not self._embedded:
                self.fig.canvas.manager.set_window_title(f"{self._base_window_title} | {current_timestamp}")

        has_new = False
        last_x, last_y = None, None
        last_flow, last_pressure = None, None
        last_sid = None
        while True:
            try:
                series_id, x, y, flow, pressure = self.data_queue.get_nowait()
                self._ensure_series(series_id)
                self.series_data[series_id]["X"].append(x)
                self.series_data[series_id]["Y"].append(y)
                has_new = True
                last_x, last_y = x, y
                last_flow, last_pressure = flow, pressure
                last_sid = series_id
            except queue.Empty:
                break

        if has_new:
            for sid, line in self.lines.items():
                d = self.series_data[sid]
                line.set_data(d["X"], d["Y"])

            if last_x is not None and last_y is not None and last_sid is not None:
                self.last_point = (last_sid, last_x, last_y)
                if last_sid in self._pressure_ids:
                    self.live_point_ax.set_data([last_x], [last_y])
                    self.live_point_flow.set_data([], [])
                else:
                    self.live_point_flow.set_data([last_x], [last_y])
                    self.live_point_ax.set_data([], [])

                self._indicator_values["spool"].set_text(f"{last_x:.3f}")
                if self._pressure_flow_text is not None:
                    if last_sid in self._pressure_ids:
                        self._pressure_flow_text.set_text(f"{last_y:,.1f} psi")
                    else:
                        self._pressure_flow_text.set_text(f"{last_y:,.2f} gpm")
                else:
                    self._indicator_values["pressure"].set_text(f"{last_pressure:.1f}")
                    self._indicator_values["flow"].set_text(f"{last_flow:.3f}")

        elif not self.is_running and callable(self.idle_reader):
            # No sweep running — poll the DAQ directly so the indicators read
            # live sensor values between tests instead of sitting at "--".
            # Gated on is_running to avoid two threads reading the same
            # nidaqmx Task at once (the sweep thread also calls this).
            # Any hardware read error here must NOT propagate — an exception
            # raised inside this FuncAnimation callback silently stops all
            # future redraws, which looks exactly like "the plot stopped
            # updating" even though the rest of the app is still running.
            try:
                x, flow, pressure = self.idle_reader()
            except Exception as exc:
                print(f"[Plotter] idle_reader failed, skipping this frame: {exc}")
            else:
                self._indicator_values["spool"].set_text(f"{x:.3f}")
                if self._pressure_flow_text is not None:
                    self._pressure_flow_text.set_text(f"{pressure:,.1f} psi · {flow:.2f} gpm")
                else:
                    self._indicator_values["pressure"].set_text(f"{pressure:.1f}")
                    self._indicator_values["flow"].set_text(f"{flow:.3f}")

            if callable(self.is_channels_ready):
                ready = False
                try:
                    ready = self.is_channels_ready()
                except Exception as exc:
                    print(f"[Plotter] is_channels_ready failed: {exc}")
                self.set_daq_status("DAQ Ready" if ready else "Out of Tol")

        # FuncAnimation runs with blit=False, so the full canvas is redrawn
        # each frame and this callback's return value is never consulted —
        # no need to build/return an artist list.

    def _ensure_series(self, series_id: SeriesKey) -> None:
        """Create series_data entry and a blank Line2D on first encounter."""
        if series_id in self.series_data:
            return
        self.series_data[series_id] = {"X": [], "Y": []}
        color = style.GREY
        ax = self.ax if series_id in self._pressure_ids else self.flow_ax
        line, = ax.plot(
            [], [], marker="s", markersize=3, color=color,
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
        if self.btn_run is not None:
            self.btn_run.label.set_text("Stop")
            style.recolor_button(self.btn_run, fill=style.RED, hover=style.RED_DARK, text_color="#FFFFFF")
        self.set_daq_status("Acquiring")
        self.event_queue.put({"cmd": "START"})

    def stop(self) -> None:
        """Pause data acquisition without resetting state."""
        self.is_running = False
        self.abort_event.set()
        if self.btn_run is not None:
            self.btn_run.label.set_text("Start")
            style.recolor_button(self.btn_run, fill=style.GREEN, hover=style.GREEN_DARK, text_color="#FFFFFF")
        self._reset_live_readouts()
        self.event_queue.put({"cmd": "STOP"})

    def _reset_live_readouts(self) -> None:
        """Clear the live-point markers and the Spool/Pressure/Flow cards."""
        self.last_point = None
        self.live_point_ax.set_data([], [])
        self.live_point_flow.set_data([], [])
        for value_text in self._indicator_values.values():
            value_text.set_text("--")
        if self._pressure_flow_text is not None:
            self._pressure_flow_text.set_text("--")

    def _set_btn_run_state(self, *, active: bool) -> None:
        """Configure the Run button's active state and matching label colour."""
        if self.btn_run is None:
            self.fig.canvas.draw_idle()
            return
        self.btn_run.label.set_text("Start")
        self.btn_run.set_active(active)
        if active:
            style.recolor_button(self.btn_run, fill=style.GREEN, hover=style.GREEN_DARK, text_color="#FFFFFF")
        else:
            style.recolor_button(self.btn_run, fill=style.PANEL, hover=style.PANEL, text_color=style.GREY)
        self.fig.canvas.draw_idle()

    def set_idle(self) -> None:
        """Disable the run button after a test completes."""
        self.is_running = False
        self._set_btn_run_state(active=False)
        self._reset_live_readouts()

    def set_ready(self) -> None:
        """Re-enable the run button (e.g. after loading new data)."""
        self.is_running = False
        self._set_btn_run_state(active=True)
        self._reset_live_readouts()

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
        self._reset_live_readouts()
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
        if not self._embedded:
            self.fig.canvas.manager.set_window_title(f"{self._base_window_title} | {self._last_timestamp}")

    def set_part_info(self, part_number: str, serial_number: str) -> None:
        """Show the part/serial number at the bottom-right of the window."""
        if self.pn_textbox is not None:
            if self.pn_textbox.text != part_number:
                self.pn_textbox.set_val(part_number)
            self.sn_text.set_text(f"S/N: {serial_number or '—'}")
        else:
            self.part_id_text.set_text(f"P/N: {part_number} | S/N: {serial_number or '—'}")

    def _on_pn_submit(self, text: str) -> None:
        """Notify the host (e.g. TPI) when the operator edits P/N and presses Enter."""
        if callable(self.on_part_number_change):
            self.on_part_number_change(text.strip())

    def set_daq_status(self, status: str) -> None:
        """Switch the toolbar's panel lamp to one of "Acquiring", "DAQ Ready",
        "Out of Tol", or "Standby". No-op when there's no Tk toolbar."""
        self._set_daq_status(status)

    # ------------------------------------------------------------------
    # Internal event handlers
    # ------------------------------------------------------------------

    def _toggle_run(self, _event) -> None:
        if self.is_running:
            self.stop()
        else:
            self.start()

    def _zero_spool_pos(self, _event) -> None:
        """Reset the Spool Pos. readout to 0.000 (display only)."""
        self._indicator_values["spool"].set_text("0.000")

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
