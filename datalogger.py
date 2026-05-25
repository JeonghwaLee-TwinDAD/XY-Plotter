"""
datalogger.py
-------------
DataLogger — writes acquired test data to timestamped CSV files.

Isolated from TPI and XYPlotter so it can be unit-tested independently
and swapped for a database writer without touching test logic.
"""

from __future__ import annotations

import os
import time
from typing import Dict

import numpy as np
import pandas as pd

from config import DATALOG_IDS, DATALOG_ID_NAMES, DATALOG_PATH


class DataLogger:
    """Export raw XY series to a timestamped CSV datalog."""

    def save(
        self,
        series_data: Dict,
        part_number: str,
        serial_number: str,
    ) -> str | None:
        """
        Collate the logged series, pad to equal length, write CSV.

        Args:
            series_data:   XYPlotter.series_data dict.
            part_number:   e.g. ``"28010712-105"``.
            serial_number: operator-entered serial; used in filename.

        Returns:
            Absolute path of the written file, or None if no data available.
        """
        columns: Dict[str, list] = {}
        max_len = 0

        for raw_key in DATALOG_IDS:
            # Accept both int and str keys (belt-and-suspenders)
            entry = series_data.get(raw_key) or series_data.get(str(raw_key))
            if not entry:
                continue

            name = DATALOG_ID_NAMES[raw_key]
            x_data = list(entry["X"])
            y_data = list(entry["Y"])

            columns[f"{name}_X"] = x_data
            columns[f"{name}_Y"] = y_data
            max_len = max(max_len, len(x_data))

        if not columns:
            print("[DataLogger] No data to export.")
            return None

        # Pad shorter columns with NaN so DataFrame is rectangular
        for data in columns.values():
            deficit = max_len - len(data)
            if deficit > 0:
                data.extend([np.nan] * deficit)

        df = pd.DataFrame(columns)
        os.makedirs(DATALOG_PATH, exist_ok=True)
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        filename  = f"{part_number}_{serial_number}_{timestamp}.csv"
        filepath  = os.path.join(DATALOG_PATH, filename)
        df.to_csv(filepath, index=False)
        print(f"[DataLogger] Saved → {filepath}")
        return filepath
