"""
analysis.py
-----------
Pure analysis functions for each FlowGrind test mode.

All functions operate on raw numpy arrays and return structured result
dataclasses.  No matplotlib, no hardware, no global state — these are
straightforward to unit-test in isolation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

import numpy as np
from matplotlib.path import Path
from scipy.interpolate import interp1d

from config import (
    FLOW_LIMIT,
    LAB_DISPLACEMENT_MAX,
    LAB_DISPLACEMENT_MIN,
    LAP_CONDITION,
    LEAKAGE_MAX,
    NO_LOAD_DRIFT_MAX,
    NO_LOAD_DRIFT_MIN,
    PRESSURE_GAIN_MIN,
    PRESSURE_GAIN_X_SCALE,
    SCALE_FACTOR,
    STROKE,
    SUPPLY_PRESSURE,
)


# ---------------------------------------------------------------------------
# Shared result base
# ---------------------------------------------------------------------------

@dataclass
class AnalysisResult:
    """Common fields every analysis result carries."""
    summary_text: str = ""          # human-readable one-liner for the info box
    passed: Optional[bool] = None   # True / False / None (no single judgement)


# ---------------------------------------------------------------------------
# Lap analysis (3-way and 4-way)
# ---------------------------------------------------------------------------

@dataclass
class LapRegression:
    """Linear-regression fit and x-intercept for one flow direction."""
    masked_xy:  np.ndarray          # points inside the ROI polygon, shape (N, 2)
    slope:      float
    intercept:  float
    x_intercept_raw:   float        # in encoder counts (unscaled)
    x_intercept_inch:  float        # scaled to inches


@dataclass
class LapResult(AnalysisResult):
    up:   Optional[LapRegression] = None
    down: Optional[LapRegression] = None


def _lap_roi_polygon(sign: float) -> Path:
    """Return the flow-axis ROI polygon for the upper (sign=+1) or lower (sign=-1) band."""
    lo = sign * FLOW_LIMIT * 0.1
    hi = sign * FLOW_LIMIT * 0.3
    if sign < 0:
        lo, hi = hi, lo       # ensure lo < hi regardless of sign
    verts = np.array([
        [-STROKE, lo],
        [ STROKE, lo],
        [ STROKE, hi],
        [-STROKE, hi],
    ])
    return Path(verts)


def _fit_regression(pts: np.ndarray) -> Optional[LapRegression]:
    """Fit a line to pts[:,0] vs pts[:,1] and compute the x-intercept."""
    if len(pts) < 2:
        return None
    m, b = np.polyfit(pts[:, 0], pts[:, 1], 1)
    if m == 0:
        return None
    x_int_raw  = -b / m
    x_int_inch = x_int_raw * SCALE_FACTOR["X"]
    return LapRegression(
        masked_xy=pts,
        slope=m,
        intercept=b,
        x_intercept_raw=x_int_raw,
        x_intercept_inch=x_int_inch,
    )


def analyse_lap(data_xy: np.ndarray) -> LapResult:
    """
    Compute lap regression for upper and lower flow bands.

    Args:
        data_xy: (N, 2) array of (x_encoder, y_flow) measurements.

    Returns:
        LapResult with optional ``up`` and ``down`` LapRegression objects.
    """
    up_mask   = _lap_roi_polygon(+1).contains_points(data_xy)
    down_mask = _lap_roi_polygon(-1).contains_points(data_xy)

    up_reg   = _fit_regression(data_xy[up_mask])
    down_reg = _fit_regression(data_xy[down_mask])

    return LapResult(up=up_reg, down=down_reg)


# ---------------------------------------------------------------------------
# 3-way lap summary (computed after both C1 and C2 sweeps)
# ---------------------------------------------------------------------------

@dataclass
class ThreeWaySummary(AnalysisResult):
    dist_up:   float = 0.0
    dist_down: float = 0.0


def summarise_3way(intercepts: Dict[str, float]) -> ThreeWaySummary:
    """
    Compute lap distances from the four 3-way x-intercepts.

    Args:
        intercepts: mapping of ``"<test_id>_up/down"`` → x_intercept_inch.
                    Must contain keys ``0_up``, ``0_down``, ``1_up``, ``1_down``.
    """
    dist_up   = abs(intercepts["0_up"]   - intercepts["1_up"])
    dist_down = abs(intercepts["0_down"] - intercepts["1_down"])

    text = (
        f"Lap Condition: {LAP_CONDITION:g} Overlap\n"
        f"X Scale: {SCALE_FACTOR['X']:g} in/rev, Y Scale: {SCALE_FACTOR['Y']:g} gpm/Hz\n"
        f"Blue (Up) Lap dS: {dist_up:.3g} in\n"
        f"Red (Down) Lap dS: {dist_down:.3g} in"
    )
    return ThreeWaySummary(summary_text=text, dist_up=dist_up, dist_down=dist_down)


# ---------------------------------------------------------------------------
# 4-way lap summary
# ---------------------------------------------------------------------------

@dataclass
class FourWaySummary(AnalysisResult):
    distance: float = 0.0
    mid_x_raw: float = 0.0     # unscaled x for annotation placement


def summarise_4way(intercepts: Dict[str, float]) -> FourWaySummary:
    dist = abs(intercepts["2_up"] - intercepts["2_down"])
    passed = LAB_DISPLACEMENT_MIN <= dist <= LAB_DISPLACEMENT_MAX
    mid_x_raw = (
        (intercepts["2_up"] + intercepts["2_down"]) / 2
    ) / SCALE_FACTOR["X"]

    text = f"Lap Distance: {LAP_CONDITION} O/L @ {dist:.3g} in, {'PASS' if passed else 'FAIL'}"
    return FourWaySummary(
        summary_text=text, passed=passed,
        distance=dist, mid_x_raw=mid_x_raw,
    )


# ---------------------------------------------------------------------------
# No-Load Drift
# ---------------------------------------------------------------------------

@dataclass
class NoLoadResult(AnalysisResult):
    max_pressure: float = 0.0
    min_pressure: float = 0.0
    x_max: float = 0.0
    x_min: float = 0.0
    max_passed: bool = False
    min_passed: bool = False


def analyse_no_load(data_xy: np.ndarray, supply_pressure: float = SUPPLY_PRESSURE) -> NoLoadResult:
    """
    Compute maximum and minimum no-load drift pressures over the stroke range.
    """
    valid = (data_xy[:, 0] >= -STROKE) & (data_xy[:, 0] <= STROKE)
    pts   = data_xy[valid] if valid.any() else data_xy

    x, y = pts[:, 0], pts[:, 1]
    max_y = float(np.max(y))
    min_y = float(np.min(y))
    x_max = float(x[np.argmax(y)])
    x_min = float(x[np.argmin(y)])

    max_psi    = supply_pressure * 0.5 + max_y
    min_psi    = supply_pressure * 0.5 + min_y
    max_passed = NO_LOAD_DRIFT_MAX <= max_psi
    min_passed = NO_LOAD_DRIFT_MIN <= min_psi

    result_str = "PASS" if (max_passed and min_passed) else "FAIL"
    text = (
        f"Max. No Load: {int(max_psi)} psi, {'PASS' if max_passed else 'FAIL'}\n"
        f"Min. No Load: {int(min_psi)} psi, {'PASS' if min_passed else 'FAIL'}"
    )
    return NoLoadResult(
        summary_text=text, passed=max_passed and min_passed,
        max_pressure=max_psi, min_pressure=min_psi,
        x_max=x_max, x_min=x_min,
        max_passed=max_passed, min_passed=min_passed,
    )


# ---------------------------------------------------------------------------
# Pressure Gain
# ---------------------------------------------------------------------------

@dataclass
class PressureGainResult(AnalysisResult):
    slope_psi_per_thou: float = 0.0
    x_raw_lo: float = 0.0      # unscaled x for plot line start
    x_raw_hi: float = 0.0      # unscaled x for plot line end
    y_lo: float = 0.0
    y_hi: float = 0.0
    mid_x_raw: float = 0.0
    mid_y: float = 0.0


def analyse_pressure_gain(
    data_xy: np.ndarray,
    supply_pressure: float = SUPPLY_PRESSURE,
) -> PressureGainResult:
    """
    Compute pressure gain slope between ±40 % of supply pressure.
    """
    x, y = data_xy[:, 0], data_xy[:, 1]
    y_lo = -0.4 * supply_pressure
    y_hi =  0.4 * supply_pressure

    order       = np.argsort(y)
    x_s, y_s   = x[order], y[order]
    x_s_scaled  = x_s * PRESSURE_GAIN_X_SCALE

    interp_raw    = interp1d(y_s, x_s,        kind="linear", fill_value="extrapolate")
    interp_scaled = interp1d(y_s, x_s_scaled, kind="linear", fill_value="extrapolate")

    x_raw_lo = float(interp_raw(y_lo))
    x_raw_hi = float(interp_raw(y_hi))
    x_sc_lo  = float(interp_scaled(y_lo))
    x_sc_hi  = float(interp_scaled(y_hi))

    dx = x_sc_hi - x_sc_lo
    slope = (y_hi - y_lo) / dx if dx != 0 else 0.0
    passed = abs(slope) >= PRESSURE_GAIN_MIN

    text = (
        f"PG Slope: {abs(slope / 1000):.2g} psi/thou, "
        f"{'PASS' if passed else 'FAIL'}"
    )
    return PressureGainResult(
        summary_text=text, passed=passed,
        slope_psi_per_thou=slope / 1000,
        x_raw_lo=x_raw_lo, x_raw_hi=x_raw_hi,
        y_lo=y_lo, y_hi=y_hi,
        mid_x_raw=(x_raw_lo + x_raw_hi) / 2,
        mid_y=(y_lo + y_hi) / 2,
    )


# ---------------------------------------------------------------------------
# Leakage
# ---------------------------------------------------------------------------

@dataclass
class LeakageResult(AnalysisResult):
    max_leak: float = 0.0
    x_peak: float = 0.0
    y_peak: float = 0.0


def analyse_leakage(data_xy: np.ndarray) -> LeakageResult:
    """Compute peak-to-peak leakage flow over the spool stroke range."""
    valid = (data_xy[:, 0] >= -STROKE) & (data_xy[:, 0] <= STROKE)
    pts   = data_xy[valid] if valid.any() else data_xy

    x, y   = pts[:, 0], pts[:, 1]
    max_y  = float(np.max(y))
    min_y  = float(np.min(y))
    x_peak = float(x[np.argmax(y)])

    leak   = abs(max_y - min_y)
    passed = leak <= LEAKAGE_MAX
    text   = f"Max Leakage: {leak:.2g} gpm, {'PASS' if passed else 'FAIL'}"

    return LeakageResult(
        summary_text=text, passed=passed,
        max_leak=leak, x_peak=x_peak, y_peak=max_y,
    )
