"""main_window.py
--------------
The FlowGrind Test Station window — a PyQt6 port of
flowgrind-design-system/app/src/test-station/Station.jsx, wired to the real
TPI/HardwareInterface/XYPlotter test logic instead of mocked plot data.

Layout mirrors Station.jsx's three columns:
  left   — SequenceRail (test list + verdicts)
  center — toolbar (Start/Stop/Clear) + the live XY plot
  right  — console-toned Live Readout / result panel
"""

from __future__ import annotations

from typing import Optional

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from PyQt6.QtCore import QDateTime, Qt, QTimer
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from config import PART_NUMBER, TEST_SEQUENCE, TEST_STAND_NUMBER, WINDOW_2_IDS
from tpi import TPI

from . import theme
from .results_view import ResultsDialog
from .widgets import LED, Panel, Readout, StatusChip, TestTag

POLL_INTERVAL_MS = 25
SEQUENCE_IDS = list(WINDOW_2_IDS)


class MainWindow(QMainWindow):
    def __init__(self, tpi: TPI, parent=None) -> None:
        super().__init__(parent)
        self.tpi = tpi
        self.setWindowTitle("FlowGrind — Test Station")
        self.resize(1440, 860)

        self._statuses: dict[int, str] = {tid: "idle" for tid in SEQUENCE_IDS}
        self._seq_pos = 0
        self._running = False
        self._active_idx = 0  # index into SEQUENCE_IDS

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(theme.SP_6, theme.SP_6, theme.SP_6, theme.SP_6)
        root.setSpacing(theme.SP_4)

        root.addWidget(self._build_topbar())

        body = QHBoxLayout()
        body.setSpacing(theme.SP_4)
        body.addWidget(self._build_sequence_rail(), stretch=0)
        body.addWidget(self._build_plot_column(), stretch=2)
        body.addWidget(self._build_console_column(), stretch=1)
        root.addLayout(body, stretch=1)

        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(POLL_INTERVAL_MS)
        self._poll_timer.timeout.connect(self._on_poll)
        self._poll_timer.start()

        self._refresh_rail()
        self._refresh_console(running=False)

    # ------------------------------------------------------------------
    # TopBar
    # ------------------------------------------------------------------

    def _build_topbar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("fgPanel")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(16, 10, 16, 10)
        layout.setSpacing(theme.SP_5)

        logo = QLabel("FLOWGRIND")
        logo.setStyleSheet(
            f"color: {theme.BRAND}; font-weight: 700; font-size: 16px; letter-spacing: 1px;"
        )
        layout.addWidget(logo)
        layout.addStretch(1)

        for k, v in (
            ("P/N", PART_NUMBER),
            ("S/N", self.tpi.serial_number or "—"),
            ("Test Stand", TEST_STAND_NUMBER),
        ):
            layout.addLayout(self._kv(k, v))

        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.VLine)
        divider.setStyleSheet(f"color: {theme.LINE};")
        layout.addWidget(divider)

        self._clock = QLabel()
        self._clock.setObjectName("fgClock")
        layout.addWidget(self._clock)
        clock_timer = QTimer(self)
        clock_timer.timeout.connect(self._tick_clock)
        clock_timer.start(1000)
        self._tick_clock()

        layout.addWidget(LED(color="pass", label="DAQ"))
        return bar

    def _kv(self, key: str, value: str) -> QVBoxLayout:
        col = QVBoxLayout()
        col.setSpacing(0)
        k_lbl = QLabel(key)
        k_lbl.setObjectName("fgKVLabel")
        v_lbl = QLabel(value)
        v_lbl.setObjectName("fgKV")
        col.addWidget(k_lbl)
        col.addWidget(v_lbl)
        return col

    def _tick_clock(self) -> None:
        self._clock.setText(QDateTime.currentDateTime().toString("yyyy-MM-dd HH:mm:ss"))

    # ------------------------------------------------------------------
    # Left column — SequenceRail
    # ------------------------------------------------------------------

    def _build_sequence_rail(self) -> Panel:
        panel = Panel(eyebrow="Window 2", title="Test Sequence")
        panel.set_body_margins(0, 0, 0, 0)
        panel.setFixedWidth(280)

        self._rail_rows: dict[int, dict] = {}
        rows = QVBoxLayout()
        rows.setContentsMargins(0, 0, 0, 0)
        rows.setSpacing(0)
        for i, tid in enumerate(SEQUENCE_IDS):
            cfg = TEST_SEQUENCE[tid]
            row = QFrame()
            row.setCursor(Qt.CursorShape.PointingHandCursor)
            row.setStyleSheet(
                f"QFrame {{ border-bottom: 1px solid {theme.LINE}; padding: 10px 16px; }}"
                f"QFrame:hover {{ background: {theme.PANEL_2}; }}"
            )
            rl = QHBoxLayout(row)
            rl.setContentsMargins(16, 10, 16, 10)
            rl.setSpacing(10)

            num = QLabel(f"{i + 1:02d}")
            num.setStyleSheet(f"font-family: '{theme.FONT_MONO}'; color: {theme.INK_3}; font-size: 12px;")
            rl.addWidget(num)
            tag = TestTag(cfg.mode)
            rl.addWidget(tag)
            rl.addStretch(1)
            chip = StatusChip("idle", size="sm")
            rl.addWidget(chip)

            row.mousePressEvent = lambda _e, idx=i: self._on_pick(idx)
            rows.addWidget(row)
            self._rail_rows[tid] = {"frame": row, "chip": chip, "tag": tag}

        rows.addStretch(1)
        panel.body_layout.addLayout(rows)
        return panel

    def _on_pick(self, idx: int) -> None:
        if self._running:
            return
        self._active_idx = idx
        self._refresh_rail()
        self._refresh_console(running=False)

    def _refresh_rail(self) -> None:
        for i, tid in enumerate(SEQUENCE_IDS):
            row = self._rail_rows[tid]
            row["chip"].set_status(self._statuses[tid])
            active = i == self._active_idx
            base = (
                f"QFrame {{ border-bottom: 1px solid {theme.LINE}; padding: 10px 16px; "
                f"background: {theme.UP_SOFT if active else theme.SURFACE}; }}"
                f"QFrame:hover {{ background: {theme.PANEL_2 if not active else theme.UP_SOFT}; }}"
            )
            row["frame"].setStyleSheet(base)

    # ------------------------------------------------------------------
    # Center column — toolbar + plot
    # ------------------------------------------------------------------

    def _build_plot_column(self) -> Panel:
        panel = Panel()
        panel.set_body_margins(0, 0, 0, 0)

        toolbar = QFrame()
        tl = QHBoxLayout(toolbar)
        tl.setContentsMargins(12, 10, 12, 10)
        tl.setSpacing(10)

        self._btn_start = QPushButton("Start")
        self._btn_start.setObjectName("fgPrimary")
        self._btn_start.clicked.connect(self._on_start_clicked)
        tl.addWidget(self._btn_start)

        self._btn_clear = QPushButton("Clear")
        self._btn_clear.setObjectName("fgSecondary")
        self._btn_clear.clicked.connect(self._on_clear)
        tl.addWidget(self._btn_clear)

        tl.addStretch(1)
        self._active_tag = TestTag(TEST_SEQUENCE[SEQUENCE_IDS[0]].mode)
        tl.addWidget(self._active_tag)

        self._diag_label = QLabel("Plot Loop: -- ms")
        self._diag_label.setObjectName("fgDiag")
        tl.addWidget(self._diag_label)

        panel.body_layout.addWidget(toolbar)

        self._canvas = FigureCanvasQTAgg(self.tpi.plotter.fig)
        panel.body_layout.addWidget(self._canvas, stretch=1)
        return panel

    def _restyle(self, widget: QWidget, object_name: str) -> None:
        """Reassign a QSS objectName and force Qt to re-apply the stylesheet."""
        widget.setObjectName(object_name)
        widget.style().unpolish(widget)
        widget.style().polish(widget)

    def _on_start_clicked(self) -> None:
        if self._running:
            self._on_stop()
        else:
            self._on_start()

    def _on_start(self) -> None:
        if self._running:
            return
        all_done = all(self._statuses[tid] != "idle" for tid in SEQUENCE_IDS)
        idle_idx = next(
            (i for i, tid in enumerate(SEQUENCE_IDS) if self._statuses[tid] == "idle"), 0
        )
        self._seq_pos = 0 if all_done else idle_idx
        if all_done:
            self.tpi.plotter.clear()
            self._statuses = {tid: "idle" for tid in SEQUENCE_IDS}

        self._running = True
        self._btn_start.setText("Stop")
        self._restyle(self._btn_start, "fgDanger")
        self._btn_clear.setEnabled(False)
        self._start_next_test()

    def _on_stop(self) -> None:
        self._running = False
        self.tpi.plotter.stop()
        self._btn_start.setText("Start")
        self._restyle(self._btn_start, "fgPrimary")
        self._btn_clear.setEnabled(True)

    def _on_clear(self) -> None:
        if self._running:
            return
        self.tpi.plotter.clear()
        self._statuses = {tid: "idle" for tid in SEQUENCE_IDS}
        self._active_idx = 0
        self._refresh_rail()
        self._refresh_console(running=False)

    def _start_next_test(self) -> None:
        if self._seq_pos >= len(SEQUENCE_IDS):
            self._on_sequence_done()
            return
        tid = SEQUENCE_IDS[self._seq_pos]
        self._active_idx = self._seq_pos
        self._statuses[tid] = "run"
        self._active_tag.set_mode(TEST_SEQUENCE[tid].mode)
        self._refresh_rail()
        self.tpi.start_test(tid)

    def _on_sequence_done(self) -> None:
        self._running = False
        self.tpi.plotter.set_ready()
        self._btn_start.setText("Re-run")
        self._restyle(self._btn_start, "fgPrimary")
        self._btn_clear.setEnabled(True)
        self._refresh_console(running=False)

    # ------------------------------------------------------------------
    # Right column — console
    # ------------------------------------------------------------------

    def _build_console_column(self) -> Panel:
        self._console_chip = StatusChip("idle", size="sm")
        panel = Panel(tone="console", eyebrow="Live Readout", title="—", actions=self._console_chip)
        panel.setFixedWidth(320)
        self._console_panel = panel

        self._readout_box = QVBoxLayout()
        panel.body_layout.addLayout(self._readout_box)

        self._result_label = QLabel("")
        self._result_label.setWordWrap(True)
        self._result_label.setStyleSheet(
            f"font-family: '{theme.FONT_MONO}'; font-size: 12px; color: {theme.CONSOLE_INK_2};"
        )
        panel.body_layout.addWidget(self._result_label)
        panel.body_layout.addStretch(1)

        self._btn_datalog = QPushButton("View Datalog")
        self._btn_datalog.setObjectName("fgPrimary")
        self._btn_datalog.setVisible(False)
        self._btn_datalog.clicked.connect(self._open_results)
        panel.body_layout.addWidget(self._btn_datalog)

        return panel

    def _clear_readouts(self) -> None:
        while self._readout_box.count():
            item = self._readout_box.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _refresh_console(self, running: bool) -> None:
        tid = SEQUENCE_IDS[self._active_idx]
        cfg = TEST_SEQUENCE[tid]
        title_label = self._console_panel.findChild(QLabel, "fgTitleConsole")
        if title_label:
            title_label.setText(cfg.title.replace("FlowGrind - ", ""))

        status = self._statuses[tid]
        self._console_chip.set_status("run" if running else status)

        self._clear_readouts()
        if running:
            point = self.tpi.plotter.last_point
            axis_is_pressure = tid in self.tpi.plotter.pressure_ids
            x = point[1] if point else 0.0
            y = point[2] if point else 0.0
            self._readout_box.addWidget(Readout("Spool Position", f"{x:.2f}", "x10⁻³ in"))
            self._readout_box.addWidget(
                Readout(
                    "Pressure" if axis_is_pressure else "Flow",
                    f"{y:.1f}" if axis_is_pressure else f"{y:.2f}",
                    "psi" if axis_is_pressure else "gpm",
                    signal="down",
                )
            )
            self._result_label.setText("")
        else:
            self._result_label.setText(self.tpi._last_result_text if status != "idle" else "")

        all_done = all(self._statuses[t] != "idle" for t in SEQUENCE_IDS)
        self._btn_datalog.setVisible(all_done)
        if all_done:
            n_pass = sum(1 for t in SEQUENCE_IDS if self._statuses[t] == "pass")
            self._btn_datalog.setText(f"View Datalog ({n_pass}/{len(SEQUENCE_IDS)} pass)")

    # ------------------------------------------------------------------
    # Poll loop — drives acquisition without blocking the GUI thread
    # ------------------------------------------------------------------

    def _on_poll(self) -> None:
        self._diag_label.setText(self.tpi.plotter.timing_text.get_text() or "Plot Loop: -- ms")

        if not self._running:
            return

        if self.tpi.is_test_acquiring():
            self._refresh_console(running=True)
            return

        # Acquisition for the current test just finished.
        _text, passed = self.tpi.finish_test()
        tid = SEQUENCE_IDS[self._seq_pos]
        self._statuses[tid] = "pass" if passed is not False else "fail"
        self._refresh_rail()
        self._refresh_console(running=False)

        self._seq_pos += 1
        if self.tpi.plotter.is_running and not self.tpi.plotter.abort_event.is_set():
            self._start_next_test()
        else:
            self._on_sequence_done()

    # ------------------------------------------------------------------
    # Results / datalog
    # ------------------------------------------------------------------

    def _open_results(self) -> None:
        dlg = ResultsDialog(self.tpi, self._statuses, SEQUENCE_IDS, self)
        dlg.exec()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def closeEvent(self, event) -> None:
        self._poll_timer.stop()
        self.tpi.plotter.abort_event.set()
        self.tpi.plotter.stop_event.set()
        try:
            self.tpi.postUUT()
        except Exception as exc:  # noqa: BLE001 - surface, don't block shutdown
            QMessageBox.warning(self, "FlowGrind", f"Teardown reported an error:\n{exc}")
        super().closeEvent(event)
