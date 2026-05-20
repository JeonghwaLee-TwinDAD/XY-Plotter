"""
config.py
---------
Central configuration for the FlowGrind test system.
All hardware limits, pass/fail thresholds, and test definitions live here.
Edit this file to adapt the system to a new part number or test stand.
"""

from dataclasses import dataclass, field
from typing import Dict


# ---------------------------------------------------------------------------
# Hardware / fixture constants
# ---------------------------------------------------------------------------
SIMULATION: bool = False                 # True → use CSV files; False → live hardware

SUPPLY_PRESSURE: float  = 3000.0       # psi
STROKE: float           = 10.0         # thousandths of an inch (plot x-axis half-range)
FLOW_LIMIT: float       = 16.0         # gpm (plot y-axis half-range)
SCALE_FACTOR: Dict[str, float] = {
    "X": 0.0025,   # encoder counts → inches
    "Y": 1.0,      # Hz → gpm
}

DATALOG_PATH: str = "C:\\_Data_Log\\"


# ---------------------------------------------------------------------------
# Part / stand identity
# ---------------------------------------------------------------------------
PART_NUMBER:        str = "28010712-105"
TEST_STAND_NUMBER:  str = "FGV2-001"


# ---------------------------------------------------------------------------
# Pass / fail thresholds
# ---------------------------------------------------------------------------
LAP_CONDITION:          float = 0.00034   # inches of overlap (3-way C1 and C2)
OVERLAP_CONDITION:      float = 0.3       # 3-way C1 overlap upper bound

LAB_DISPLACEMENT_MAX:   float = 0.0006   # dS upper bound  (warning only)
LAB_DISPLACEMENT_MIN:   float = 0.0003   # dS lower bound  (warning only)

NO_LOAD_DRIFT_MAX:      float = 850.0    # psi
NO_LOAD_DRIFT_MIN:      float = 150.0    # psi

LEAKAGE_MAX:            float = 0.04     # gpm

PRESSURE_GAIN_MIN:      float = 4200.0   # psi/inch
PRESSURE_GAIN_X_SCALE:  float = 0.05     # encoder counts → thou (PG test only)

NEUTRAL_PRESSURE_MAX:   float = 2500.0   # psi
NEUTRAL_PRESSURE_MIN:   float = 1000.0   # psi

SUPPLY_PRESSURE_TOLERANCE: float = 25.0  # psi


# ---------------------------------------------------------------------------
# Test sequence definition
# Each entry maps a logical test_id to its mode string, window title, and
# CSV simulation file.  Adding a new test point means adding one entry here.
# ---------------------------------------------------------------------------
@dataclass
class TestConfig:
    test_id:  int
    mode:     str
    title:    str
    sim_file: str


TEST_SEQUENCE: Dict[int, TestConfig] = {
    0: TestConfig(0, "3way-C1",  "FlowGrind - 3way Lap",        "./Simulation Files/3way_AB.csv"),
    1: TestConfig(1, "3way-C2",  "FlowGrind - 3way Lap",        "./Simulation Files/3way_CD.csv"),
    2: TestConfig(2, "4wayLap",  "FlowGrind - 4way Lap",        "./Simulation Files/4way_AB.csv"),
    3: TestConfig(3, "NoLoad",   "FlowGrind - No Load Drift",   "./Simulation Files/NoLoad.csv"),
    4: TestConfig(4, "PG",       "FlowGrind - Pressure Gain",   "./Simulation Files/PG.csv"),
    5: TestConfig(5, "Leak",     "FlowGrind - Leakage",         "./Simulation Files/Leak.csv"),
}

# Which test_ids belong to window 1 vs window 2
WINDOW_1_IDS = (0, 1)
WINDOW_2_IDS = (2, 3, 4, 5)

# test_ids whose data are written to the CSV datalog
DATALOG_IDS = (2, 3, 4, 5)
DATALOG_ID_NAMES = {2: "4wayLap", 3: "NoLoad", 4: "PG", 5: "Leak"}
