"""
main_qt.py
----------
Entry point for the FlowGrind PyQt6 Test Station — the window application
that ports the flowgrind-design-system look onto the real TPI/hardware test
logic for the Window-2 sequence (4-Way Lap, No Load Drift, Pressure Gain,
Leakage).

The 3-way lap calibration (Window 1) is unchanged and still served by the
matplotlib flow in main.py — this entry point assumes calibration is either
not required or already complete, and asks only for the serial number before
opening the Test Station.
"""

import matplotlib
matplotlib.use("QtAgg")  # must be set before plotter.py imports pyplot

import sys

from PyQt6.QtWidgets import QApplication, QInputDialog

from config import PART_NUMBER
from tpi import TPI
from ui_qt import theme
from ui_qt.main_window import MainWindow


def main() -> None:
    app = QApplication(sys.argv)
    app.setStyleSheet(theme.stylesheet())

    serial, ok = QInputDialog.getText(
        None, "FlowGrind Setup", f"P/N {PART_NUMBER}\nEnter Serial Number:"
    )
    if not ok or not serial.strip():
        return

    tpi = TPI(embedded=True)
    tpi.startup()
    tpi.serial_number = serial.strip()
    tpi.plotter.set_window_title("FlowGrind")
    tpi.plotter.set_part_info(tpi.part_number, tpi.serial_number)

    window = MainWindow(tpi)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
