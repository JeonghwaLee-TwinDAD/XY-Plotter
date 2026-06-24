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

MCP Server
----------
`mcp_server.py` exposes the FlowGrind test sequence as an MCP server, so an
LLM client (Claude Desktop, Claude Code, etc.) can drive the test stand
headlessly -- no matplotlib GUI.

Install dependencies:

    python -m pip install -r requirements.txt

Run standalone (stdio transport):

    python mcp_server.py

Register with an MCP client by pointing it at this script, e.g. in
Claude Desktop's `claude_desktop_config.json`:

    {
      "mcpServers": {
        "flowgrind-xy-plotter": {
          "command": "python",
          "args": ["C:\\Working copy\\XY Plotter\\mcp_server.py"]
        }
      }
    }

Available tools:

| Tool                      | Description |
|---------------------------|-------------|
| `list_tests`              | List test IDs, modes, titles, and named groups |
| `startup`                 | Connect to the DAQ (or simulation per `config.SIMULATION`) |
| `shutdown`                | Disconnect from the DAQ |
| `reset_uut(serial_number)`| Clear results/data and set the UUT serial number |
| `run_test(test_id)`       | Run one test point (0-5) and return its analysis |
| `run_sequence(group)`     | Run a named group: `window1`, `window2`, `3way`, `4wayLap`, `NoLoad`, `PG`, `Leak`, `all` |
| `abort`                   | Abort the running sweep/sequence |
| `get_status`              | Connection/run state |
| `get_results(test_id?)`   | Analysis results so far (all, or one test) |
| `get_series_data(test_id)`| Raw acquired (X, Y) samples |
| `save_datalog`            | Save acquired data to a timestamped CSV |

Questions or changes: open an issue or ask the maintainer in the repo.
