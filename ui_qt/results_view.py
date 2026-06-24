"""results_view.py
---------------
Qt port of test-station/Results.jsx — the post-sequence datalog screen:
a PASS/FAIL verdict bar, a results table, and a Save CSV action that calls
the real DataLogger instead of a mocked write.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from config import PART_NUMBER, TEST_SEQUENCE, TEST_STAND_NUMBER
from datalogger import DataLogger
from tpi import TPI

from . import theme
from .widgets import StatusChip, TestTag


class ResultsDialog(QDialog):
    def __init__(self, tpi: TPI, statuses: dict[int, str], sequence_ids: list[int], parent=None) -> None:
        super().__init__(parent)
        self.tpi = tpi
        self.statuses = statuses
        self.sequence_ids = sequence_ids
        self.setWindowTitle("FlowGrind — Test Results")
        self.resize(720, 520)

        overall = "fail" if "fail" in statuses.values() else "pass"
        layout = QVBoxLayout(self)
        layout.setSpacing(theme.SP_4)

        layout.addWidget(self._verdict_bar(overall))
        layout.addWidget(self._table())

        footer = QHBoxLayout()
        btn_save = QPushButton("Save CSV")
        btn_save.setObjectName("fgSecondary")
        btn_save.clicked.connect(self._save_csv)
        footer.addWidget(btn_save)
        footer.addStretch(1)
        btn_back = QPushButton("Back to Station")
        btn_back.setObjectName("fgSecondary")
        btn_back.clicked.connect(self.accept)
        footer.addWidget(btn_back)
        layout.addLayout(footer)

    def _verdict_bar(self, overall: str) -> QLabel:
        bg = theme.GAIN_SOFT if overall == "pass" else theme.DOWN_SOFT
        border = theme.GAIN if overall == "pass" else theme.DOWN
        label = QLabel(
            f"Unit {'PASSED' if overall == 'pass' else 'FAILED'} — S/N {self.tpi.serial_number}\n"
            f"P/N {PART_NUMBER} · Stand {TEST_STAND_NUMBER} · {len(self.sequence_ids)} tests"
        )
        label.setStyleSheet(
            f"background: {bg}; border: 1px solid {border}; border-radius: {theme.R_3}px; "
            f"padding: 14px; font-family: '{theme.FONT_SANS}'; font-size: 14px; color: {theme.INK};"
        )
        return label

    def _table(self) -> QTableWidget:
        table = QTableWidget(len(self.sequence_ids), 4)
        table.setHorizontalHeaderLabels(["#", "Test", "Result", "Verdict"])
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)

        for row, tid in enumerate(self.sequence_ids):
            cfg = TEST_SEQUENCE[tid]
            table.setItem(row, 0, QTableWidgetItem(f"{row + 1:02d}"))
            table.setCellWidget(row, 1, TestTag(cfg.mode))
            result_item = QTableWidgetItem("—")
            result_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            table.setItem(row, 2, result_item)
            chip_holder = StatusChip(self.statuses.get(tid, "idle"))
            table.setCellWidget(row, 3, chip_holder)
        return table

    def _save_csv(self) -> None:
        path = DataLogger().save(
            series_data=self.tpi.plotter.series_data,
            part_number=PART_NUMBER,
            serial_number=self.tpi.serial_number,
        )
        if path:
            QMessageBox.information(self, "FlowGrind", f"Datalog saved to:\n{path}")
        else:
            QMessageBox.warning(self, "FlowGrind", "No data available to save.")
