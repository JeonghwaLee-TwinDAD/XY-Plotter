XY Plotter / TPI
=================

Overview
--------
Small Python project that provides a live XY plotting GUI (XYPlotter.py) and a test process interface/orchestrator (TPI_FG.py) which exercises the plotter with test data and analysis overlays.

Key files
---------
- XYPlotter.py — plotting/animation, widgets (Run button), data queue, series_data and drawing helpers.
- TPI_FG.py — TPI class: lifecycle methods (startup, preUUT, testExecution, postUUT), simulation_interface and logic that drives XYPlotter.

Requirements
------------
- Python 3.8+
- matplotlib
- numpy

Install
-------
python -m pip install matplotlib numpy

Run
---
python "TPI_FG.py"
(Depending on filesystem case-sensitivity the script may be named tpi_fg.py)

Notes for developers
--------------------
- XYPlotter exposes an update loop and a data_queue for external data feeds. Extend by pushing (X,Y) samples into that queue or by adding new plotting series to series_data.
- TPI_FG orchestrates tests and annotates plots. Inspect testExecution() for how series and annotations are created.

Questions or changes: open an issue or ask the maintainer in the repo.
