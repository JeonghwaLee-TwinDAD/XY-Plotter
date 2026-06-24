"""theme.py
--------
FlowGrind design-system tokens, ported from the React design system's
tokens/colors.css, typography.css, and spacing.css into Python constants
plus a single Qt stylesheet (QSS) string.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Color tokens (tokens/colors.css)
# ---------------------------------------------------------------------------
INK           = "#0F1620"
INK_2         = "#2B3744"
INK_3         = "#5A6776"
LINE          = "#D7DDE3"
LINE_STRONG   = "#B6BFC8"
SURFACE       = "#FFFFFF"
PANEL         = "#F1F4F7"
PANEL_2       = "#E6EBEF"

CONSOLE       = "#111A22"
CONSOLE_2     = "#18242E"
CONSOLE_INK   = "#E8EEF2"
CONSOLE_INK_2 = "#8FA1AE"
CONSOLE_LINE  = "#283742"

BRAND         = "#0B4DA2"
BRAND_INK     = "#FFFFFF"

UP            = "#2563C9"
UP_SOFT       = "#E5EDF9"
DOWN          = "#D2243A"
DOWN_SOFT     = "#FBE6E8"
GAIN          = "#1C8B53"
GAIN_SOFT     = "#E2F1E9"
LEAK          = "#7C42B4"
LEAK_SOFT     = "#F0E8F7"
AMBER         = "#C9810B"
AMBER_SOFT    = "#FBF0DA"

PASS, PASS_SOFT = GAIN, GAIN_SOFT
FAIL, FAIL_SOFT = DOWN, DOWN_SOFT
WARN, WARN_SOFT = AMBER, AMBER_SOFT
RUN, RUN_SOFT   = UP, UP_SOFT
IDLE            = INK_3

MARKER_FACE = "#FFFFFF"
GRID        = "#D7DDE3"
FIT         = "#0F1620"

# ---------------------------------------------------------------------------
# Typography (tokens/typography.css)
# ---------------------------------------------------------------------------
FONT_SANS = "IBM Plex Sans"
FONT_MONO = "IBM Plex Mono"
FONT_SANS_FALLBACK = f"'{FONT_SANS}', 'Segoe UI', sans-serif"
FONT_MONO_FALLBACK = f"'{FONT_MONO}', 'Consolas', monospace"

FZ_DISPLAY, FZ_H1, FZ_H2, FZ_H3 = 40, 28, 22, 18
FZ_BODY, FZ_SM, FZ_XS = 15, 13, 11

# ---------------------------------------------------------------------------
# Spacing & radii (tokens/spacing.css)
# ---------------------------------------------------------------------------
SP_1, SP_2, SP_3, SP_4, SP_5, SP_6 = 4, 8, 12, 16, 20, 24
R_1, R_2, R_3, R_PILL = 2, 4, 6, 999
CTL_H_SM, CTL_H, CTL_H_LG = 28, 36, 44

# ---------------------------------------------------------------------------
# Test-mode color map (TestTag.jsx)
# ---------------------------------------------------------------------------
MODE_STYLE = {
    "3way-C1": ("3-Way Lap · C1", UP, UP_SOFT),
    "3way-C2": ("3-Way Lap · C2", UP, UP_SOFT),
    "4wayLap": ("4-Way Lap", DOWN, DOWN_SOFT),
    "NoLoad":  ("No Load Drift", INK_2, PANEL_2),
    "PG":      ("Pressure Gain", GAIN, GAIN_SOFT),
    "Leak":    ("Leakage", LEAK, LEAK_SOFT),
}

VERDICT_STYLE = {
    "idle": (IDLE, PANEL_2, "IDLE"),
    "run":  (RUN, RUN_SOFT, "RUNNING"),
    "pass": (PASS, PASS_SOFT, "PASS"),
    "fail": (FAIL, FAIL_SOFT, "FAIL"),
    "warn": (WARN, WARN_SOFT, "WARN"),
}


def stylesheet() -> str:
    """Global QSS applying the panel/control look to the whole app."""
    return f"""
    QWidget {{
        background: {PANEL};
        color: {INK};
        font-family: {FONT_SANS_FALLBACK};
        font-size: {FZ_BODY - 1}px;
    }}
    QMainWindow {{ background: {PANEL}; }}

    QFrame#fgPanel {{
        background: {SURFACE};
        border: 1px solid {LINE};
        border-radius: {R_3}px;
    }}
    QFrame#fgPanelConsole {{
        background: {CONSOLE};
        border: 1px solid {CONSOLE_LINE};
        border-radius: {R_3}px;
    }}
    QFrame#fgPanelHeader {{
        background: {PANEL};
        border-bottom: 1px solid {LINE};
        border-top-left-radius: {R_3}px;
        border-top-right-radius: {R_3}px;
    }}
    QFrame#fgPanelHeaderConsole {{
        background: {CONSOLE_2};
        border-bottom: 1px solid {CONSOLE_LINE};
        border-top-left-radius: {R_3}px;
        border-top-right-radius: {R_3}px;
    }}
    QLabel#fgEyebrow {{
        color: {INK_3};
        font-family: {FONT_MONO_FALLBACK};
        font-size: {FZ_XS - 1}px;
        font-weight: 600;
        letter-spacing: 1px;
    }}
    QLabel#fgEyebrowConsole {{ color: {CONSOLE_INK_2}; }}
    QLabel#fgTitle {{
        color: {INK};
        font-weight: 600;
        font-size: {FZ_SM + 2}px;
    }}
    QLabel#fgTitleConsole {{ color: {CONSOLE_INK}; }}

    QPushButton {{
        border-radius: {R_2}px;
        font-weight: 600;
        font-size: {FZ_SM}px;
        padding: 0 16px;
        min-height: {CTL_H}px;
        border: 1px solid {LINE_STRONG};
        background: {SURFACE};
        color: {INK};
    }}
    QPushButton:disabled {{ color: {INK_3}; background: {PANEL_2}; border-color: {LINE}; }}
    QPushButton#fgPrimary {{ background: {BRAND}; border-color: {BRAND}; color: white; }}
    QPushButton#fgPrimary:hover {{ background: #0a4490; }}
    QPushButton#fgDanger {{ background: {DOWN}; border-color: {DOWN}; color: white; }}
    QPushButton#fgDanger:hover {{ background: #b91f33; }}
    QPushButton#fgSecondary:hover {{ background: {PANEL_2}; }}

    QLabel#fgClock, QLabel#fgDiag {{
        color: {INK_3};
        font-family: {FONT_MONO_FALLBACK};
        font-size: {FZ_XS}px;
    }}
    QLabel#fgKV {{ font-family: {FONT_MONO_FALLBACK}; font-size: {FZ_SM}px; color: {INK}; }}
    QLabel#fgKVLabel {{ font-family: {FONT_MONO_FALLBACK}; font-size: {FZ_XS}px; color: {INK_3}; }}

    QTableWidget {{
        background: {SURFACE};
        gridline-color: {LINE};
        border: none;
        font-family: {FONT_MONO_FALLBACK};
        font-size: {FZ_SM}px;
    }}
    QHeaderView::section {{
        background: {PANEL};
        color: {INK_3};
        border: none;
        border-bottom: 1px solid {LINE};
        padding: 6px;
        font-family: {FONT_MONO_FALLBACK};
        font-size: {FZ_XS}px;
        font-weight: 600;
        text-transform: uppercase;
    }}
    """
