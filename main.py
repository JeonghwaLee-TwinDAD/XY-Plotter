"""
main.py
-------
Entry point for the FlowGrind test system.

Runs the two-window test sequence:
  Window 1 — 3-way lap (test IDs 0 and 1)
  Window 2 — 4-way lap, No Load, Pressure Gain, Leakage (IDs 2–5)
"""

import matplotlib.pyplot as plt

from config import WINDOW_1_IDS, WINDOW_2_IDS
from tpi import TPI


def main() -> None:
    tpi = TPI()

    tpi.startup()
    tpi.preUUT()

    # ---------------------------------------------------------------
    # Window 1: 3-way lap tests
    # ---------------------------------------------------------------
    for tid in WINDOW_1_IDS:
        tpi.execute(tid)

    # Block until the operator closes the 3-way window
    tpi._is_switching_windows = True
    plt.show()
    tpi._is_switching_windows = False

    # ---------------------------------------------------------------
    # Window 2: 4-way + downstream tests
    # ---------------------------------------------------------------
    tpi.plotter = tpi._make_plotter(update_interval=10)
    tpi.plotter.part_text.set_text(tpi._result_text)

    for tid in WINDOW_2_IDS:
        tpi.execute(tid)

    plt.show()

    # ---------------------------------------------------------------
    # Teardown
    # ---------------------------------------------------------------
    tpi.postUUT()


if __name__ == "__main__":
    main()
