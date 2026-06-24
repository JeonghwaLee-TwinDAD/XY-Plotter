"""
main.py
-------
Entry point for the FlowGrind test system.

Runs the full test sequence (3-way lap, 4-way lap, No Load, Pressure Gain,
Leakage) in a single window. The cycle menu picks which group of test IDs
"Start" runs: 3-Way Lap, All Sequence, 4-Way Lap, No Load Drift, Pressure
Gain, or Leakage.
"""

#import matplotlib
#matplotlib.use('WebAgg')
import matplotlib.pyplot as plt

from tpi import TPI


def main() -> None:
    tpi = TPI()

    tpi.startup()
    tpi.preUUT()

    # Tests will be triggered when the operator clicks Start.
    plt.show()

    # ---------------------------------------------------------------
    # Teardown
    # ---------------------------------------------------------------
    # Note: tpi.postUUT() is triggered automatically when the operator
    # closes the window, handled by TPI._on_window_close.


if __name__ == "__main__":
    main()
