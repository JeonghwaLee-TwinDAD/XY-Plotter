"""
main.py
-------
Entry point for the FlowGrind test system.

Runs the two-window test sequence:
  Window 1 — 3-way lap (test IDs 0 and 1)
  Window 2 — 4-way lap, No Load, Pressure Gain, Leakage (IDs 2–5)
"""

#import matplotlib
#matplotlib.use('WebAgg')
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
    for test_id in WINDOW_1_IDS:
        tpi.execute(test_id)

    # Block until operator closes Window 1, then open Window 2
    tpi.switch_to_window_2()

    # ---------------------------------------------------------------
    # Window 2: 4-way + downstream tests
    # ---------------------------------------------------------------
    for test_id in WINDOW_2_IDS:
        tpi.execute(test_id)

    plt.show()

    # ---------------------------------------------------------------
    # Teardown
    # ---------------------------------------------------------------
    # Note: tpi.postUUT() is triggered automatically when the operator
    # closes Window 2, handled by TPI._on_window_close.


if __name__ == "__main__":
    main()
