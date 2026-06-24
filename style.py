"""
style.py
--------
FlowGrind design-system theme for the matplotlib GUI.

Centralises the color palette, typography, and small helpers used to give
the plot, buttons, and info text a flat, borderless look, plus a resize-aware
mechanism (pin_axes*) for keeping fixed-size buttons aligned with the graph.
Presentation only — no test or hardware logic depends on this module.
"""

from __future__ import annotations

import matplotlib as mpl
from matplotlib.widgets import Button

# ---------------------------------------------------------------------------
# Palette
# ---------------------------------------------------------------------------
PANEL       = "#F1F4F7"   # window / figure background (design-system --c-panel)
PLOT_BG     = "#FFFFFF"   # graph background (design-system --c-surface)
INK         = "#0F1620"   # plot border, axis lines, primary text (--c-ink)
GREY        = "#5A6776"   # secondary / disabled text, quadrant labels (--c-ink-3)
GRID        = "#D7DDE3"   # gridlines, reference lines (--c-grid)

GREEN      = "#1C8B53"   # Pressure Gain / PASS (--c-gain)
GREEN_DARK = "#176E42"
GREEN_SOFT = "#E2F1E9"
RED        = "#D2243A"   # Down sweep / live cursor / FAIL (--c-down)
RED_DARK   = "#AC1D30"
RED_SOFT   = "#FBE6E8"
BLUE       = "#2563C9"   # Up sweep / primary signal (--c-up)
BLUE_SOFT  = "#E5EDF9"
PURPLE     = "#7C42B4"   # Leakage annotation (--c-leak)
PURPLE_SOFT = "#F0E8F7"
PANEL_2    = "#E6EBEF"   # neutral tag background (No Load Drift / default)
AMBER      = "#C9810B"   # warning / out-of-tolerance lamp

_FONT_STACK = ["Tahoma", "MS Sans Serif", "Segoe UI", "Arial", "DejaVu Sans"]


def apply_theme() -> None:
    """Apply the classic panel palette/typography globally via rcParams."""
    mpl.rcParams.update({
        "font.family":       "sans-serif",
        "font.sans-serif":   _FONT_STACK,
        "figure.facecolor":  PANEL,
        "axes.facecolor":    PLOT_BG,
        "axes.edgecolor":    INK,
        "axes.labelcolor":   INK,
        "axes.titlecolor":   INK,
        "axes.linewidth":    1.0,
        "axes.grid":         False,
        "axes.spines.top":   True,
        "axes.spines.right": True,
        "grid.color":        GRID,
        "grid.linewidth":    0.5,
        "xtick.color":       INK,
        "ytick.color":       INK,
        "text.color":        INK,
    })


def style_button(btn: Button, fill: str, hover: str | None = None, text_color: str = INK,
                  bold: bool = True, fontsize: float = 11) -> None:
    """Give a matplotlib Button a flat, rectangular fill (no border)."""
    ax = btn.ax
    ax.patch.set_edgecolor("none")
    ax.patch.set_linewidth(0)
    for spine in ax.spines.values():
        spine.set_visible(False)

    recolor_button(btn, fill, hover, text_color)
    btn.label.set_fontsize(fontsize)
    btn.label.set_fontweight("bold" if bold else "normal")


def recolor_button(btn: Button, fill: str, hover: str | None = None, text_color: str = INK) -> None:
    """Update an already-styled button's fill/label colors, removing hover overlay."""
    btn.ax.patch.set_facecolor(fill)
    btn.color = fill
    btn.hovercolor = fill
    btn.label.set_color(text_color)


# ---------------------------------------------------------------------------
# Indicator cards — design-system Readout.jsx look (caption + big colored
# value + unit, in a light rounded card), used for live spool/pressure/flow.
# ---------------------------------------------------------------------------

def draw_indicator_card(fig, rect: list[float], label: str, unit: str,
                         value_color: str = INK):
    """
    Create a dedicated Axes styled as a rounded indicator card (caption +
    big colored value + unit). *rect* is its initial [x0, y0, w, h] in
    figure-fraction — pin it to a fixed pixel size/position afterward with
    pin_axes_top_left/top_right so it survives window resizes like a button.
    Returns (card_ax, value_text); update the live value via
    `value_text.set_text(...)`.
    """
    card_ax = fig.add_axes(rect)
    card_ax.set_xticks([])
    card_ax.set_yticks([])
    for spine in card_ax.spines.values():
        spine.set_visible(False)

    card_ax.patch.set_facecolor(PLOT_BG)
    card_ax.patch.set_edgecolor(GRID)
    card_ax.patch.set_linewidth(1)

    pad = 0.06
    card_ax.text(pad, 0.74, label.upper(), transform=card_ax.transAxes,
                 fontsize=6.5, color=GREY, fontweight="bold", ha="left", va="center")

    value_text = card_ax.text(pad, 0.32, "--", transform=card_ax.transAxes,
                 fontsize=13, color=value_color, fontweight="bold", ha="left", va="center")

    card_ax.text(1 - pad, 0.32, unit, transform=card_ax.transAxes,
                 fontsize=7.5, color=GREY, ha="right", va="center")

    return card_ax, value_text


# ---------------------------------------------------------------------------
# Fixed-size button anchoring
# ---------------------------------------------------------------------------
# Buttons are laid out with plt.axes()/fig.add_axes() in figure-fraction
# coordinates, which by default stretch/move whenever the window is resized.
# pin_axes() keeps an axes at a constant pixel size, with its position on
# every resize recomputed by a caller-supplied function — so it can stay
# pinned to the figure corner, or stay flush against another (fraction-based)
# axes' edge, regardless of window size.

def pin_axes(fig, ax, compute_position) -> None:
    """Register *compute_position(w_px, h_px) -> [x0, y0, w, h]* (figure
    fraction) to reposition *ax* on every resize, and apply it immediately."""
    entries = getattr(fig, "_pinned_axes", None)
    if entries is None:
        entries = fig._pinned_axes = []
        fig.canvas.mpl_connect("resize_event", lambda _evt: _reposition_pinned(fig))

    for i, (existing_ax, _fn) in enumerate(entries):
        if existing_ax is ax:
            entries[i] = (ax, compute_position)
            break
    else:
        entries.append((ax, compute_position))

    _reposition_pinned(fig)


def pin_axes_top_right(fig, ax, *, width_px: float, height_px: float,
                        right_px: float, top_px: float) -> None:
    """Anchor *ax* to a fixed pixel box measured from the top-right corner of *fig*."""
    def compute_position(w_px, h_px):
        x0 = 1.0 - (right_px + width_px) / w_px
        y0 = 1.0 - (top_px + height_px) / h_px
        return [x0, y0, width_px / w_px, height_px / h_px]

    pin_axes(fig, ax, compute_position)


def pin_axes_top_left(fig, ax, *, width_px: float, height_px: float,
                       left_px: float, top_px: float) -> None:
    """Anchor *ax* to a fixed pixel box measured from the top-left corner of *fig*."""
    def compute_position(w_px, h_px):
        x0 = left_px / w_px
        y0 = 1.0 - (top_px + height_px) / h_px
        return [x0, y0, width_px / w_px, height_px / h_px]

    pin_axes(fig, ax, compute_position)


def pin_axes_bottom_right(fig, ax, *, width_px: float, height_px: float,
                           right_px: float, bottom_px: float) -> None:
    """Anchor *ax* to a fixed pixel box measured from the bottom-right corner of *fig*."""
    def compute_position(w_px, h_px):
        x0 = 1.0 - (right_px + width_px) / w_px
        y0 = bottom_px / h_px
        return [x0, y0, width_px / w_px, height_px / h_px]

    pin_axes(fig, ax, compute_position)


def pin_axes_flush(fig, ax, *, width_px: float, height_px: float,
                    right_of: object = None, gap_right_px: float = 0.0,
                    above: object, gap_top_px: float = 0.0) -> None:
    """
    Anchor *ax* to a fixed pixel size, flush against other (fraction-based)
    axes so the alignment holds at any window size:
      • right edge   = `right_of`'s left edge minus gap_right_px (or, if
                        `right_of` is None, `above`'s right edge)
      • bottom edge   = `above`'s top edge plus gap_top_px
    """
    def compute_position(w_px, h_px):
        above_bbox = above.get_position()
        if right_of is not None:
            x1 = right_of.get_position().x0 - gap_right_px / w_px
        else:
            x1 = above_bbox.x1
        x0 = x1 - width_px / w_px
        y0 = above_bbox.y1 + gap_top_px / h_px
        return [x0, y0, width_px / w_px, height_px / h_px]

    pin_axes(fig, ax, compute_position)


def _reposition_pinned(fig) -> None:
    w_px, h_px = fig.get_size_inches() * fig.dpi
    if w_px <= 0 or h_px <= 0:
        return
    for ax, compute_position in fig._pinned_axes:
        ax.set_position(compute_position(w_px, h_px))


# ---------------------------------------------------------------------------
# Fixed-position text anchoring — same idea as pin_axes(), but for plain
# matplotlib Text artists (e.g. S/N), which aren't Axes and so can't use
# ax.set_position().
# ---------------------------------------------------------------------------

def pin_text(fig, text_artist, compute_xy) -> None:
    """Register *compute_xy(w_px, h_px) -> (x, y)* (figure fraction) to
    reposition *text_artist* on every resize, and apply it immediately."""
    entries = getattr(fig, "_pinned_texts", None)
    if entries is None:
        entries = fig._pinned_texts = []
        fig.canvas.mpl_connect("resize_event", lambda _evt: _reposition_pinned_texts(fig))

    for i, (existing, _fn) in enumerate(entries):
        if existing is text_artist:
            entries[i] = (text_artist, compute_xy)
            break
    else:
        entries.append((text_artist, compute_xy))

    _reposition_pinned_texts(fig)


def pin_text_top_left(fig, text_artist, *, x_px: float, top_px: float) -> None:
    """Anchor *text_artist* to a fixed pixel position from the top-left corner of *fig*."""
    def compute_xy(w_px, h_px):
        return (x_px / w_px, 1.0 - top_px / h_px)

    pin_text(fig, text_artist, compute_xy)


def _reposition_pinned_texts(fig) -> None:
    w_px, h_px = fig.get_size_inches() * fig.dpi
    if w_px <= 0 or h_px <= 0:
        return
    for text_artist, compute_xy in fig._pinned_texts:
        text_artist.set_position(compute_xy(w_px, h_px))


# ---------------------------------------------------------------------------
# Navigation toolbar (Home/Pan/Zoom/Save) — backend-native widget, not drawn
# on the Figure, so it needs its own (best-effort) recoloring.
# ---------------------------------------------------------------------------

def style_toolbar(fig) -> None:
    """Recolor the TkAgg navigation toolbar to match the theme. No-op on
    backends without a Tk toolbar (Agg, Qt windows that don't add one)."""
    toolbar = getattr(getattr(fig.canvas, "manager", None), "toolbar", None)
    if toolbar is None or not hasattr(toolbar, "winfo_children"):
        return

    def _recolor(widget) -> None:
        for option in ("background", "highlightbackground", "activebackground"):
            try:
                widget.configure({option: PANEL})
            except Exception:
                pass
        try:
            widget.configure(foreground=INK)
        except Exception:
            pass
        for child in widget.winfo_children():
            _recolor(child)

    _recolor(toolbar)


def add_status_lamp(fig, states: dict[str, str], initial: str):
    """
    Add a single dynamic "PANEL LAMP" (colored dot + caps label), centered
    in the TkAgg navigation toolbar. *states* maps each possible status name
    (e.g. "Acquiring", "DAQ Ready", "Out of Tol", "Standby") to the dot/text
    color it should take on when active — an enum-style indicator showing
    exactly one current state, not all of them at once. No-op on backends
    without a Tk toolbar (returns (None, a no-op setter)).
    Returns (frame, set_status): call `set_status(name)` to switch the
    lamp to a different state; *frame* hosts the lamp — pass it to
    add_toolbar_label() to add more widgets in the same row.
    """
    toolbar = getattr(getattr(fig.canvas, "manager", None), "toolbar", None)
    if toolbar is None or not hasattr(toolbar, "winfo_children"):
        return None, (lambda _name: None)

    import tkinter as tk

    frame = tk.Frame(toolbar, background=PANEL)
    frame.pack(side=tk.RIGHT, padx=(0, 4))

    dot = tk.Label(frame, text="●", background=PANEL, font=("TkDefaultFont", 11))
    dot.grid(row=0, column=0, padx=(0, 3))
    text = tk.Label(frame, font=("TkDefaultFont", 9, "bold"), background=PANEL)
    text.grid(row=0, column=1, sticky="w")

    def set_status(name: str) -> None:
        color = states.get(name, GREY)
        dot.configure(foreground=color)
        text.configure(text=name.upper(), foreground=color)

    set_status(initial)

    frame._next_extra_col = 2
    return frame, set_status


def add_toolbar_center_frame(fig):
    """
    Create an independent Frame on the right side of the TkAgg navigation
    toolbar (via `pack`, so it sits free of the default Home/Pan/Zoom/Save
    buttons and add_status_lamp's centered frame). Pass it to
    add_toolbar_label() to add text there. No-op (returns None) on
    backends without a Tk toolbar.
    """
    toolbar = getattr(getattr(fig.canvas, "manager", None), "toolbar", None)
    if toolbar is None or not hasattr(toolbar, "winfo_children"):
        return None

    import tkinter as tk

    frame = tk.Frame(toolbar, background=PANEL)
    frame.pack(side=tk.RIGHT, padx=(0, 4))
    frame._next_extra_col = 0
    return frame


def add_toolbar_label(frame, *, bold: bool = False, color: str = INK):
    """Add a plain text Label to *frame* (the one returned by
    add_status_lamp), packed right after the lamp/previously-added labels.
    Returns the Label — update its text live via
    `label.configure(text=new_text)`."""
    import tkinter as tk

    col = getattr(frame, "_next_extra_col", 0)
    frame._next_extra_col = col + 1

    weight = "bold" if bold else "normal"
    label = tk.Label(frame, text="", font=("TkDefaultFont", 9, weight),
                      foreground=color, background=PANEL)
    label.grid(row=0, column=col, padx=(0 if col == 0 else 28, 0), sticky="w")
    return label


def add_toolbar_readout(fig, label: str, unit: str, value_color: str = INK):
    """
    Add a Spool/Pressure/Flow-style readout (caps caption + bold colored
    value + unit) to the TkAgg navigation toolbar, packed on the left right
    after the default Home/Pan/Zoom/Save buttons. No-op on backends without
    a Tk toolbar (returns None). Returns the value Label — update it live
    via `value_label.configure(text=new_text)`.
    """
    toolbar = getattr(getattr(fig.canvas, "manager", None), "toolbar", None)
    if toolbar is None or not hasattr(toolbar, "winfo_children"):
        return None

    import tkinter as tk

    frame = tk.Frame(toolbar, background=PANEL)
    frame.pack(side=tk.LEFT, padx=(12, 0))

    tk.Label(frame, text=label.upper(), font=("TkDefaultFont", 10, "bold"),
              foreground=GREY, background=PANEL).grid(row=0, column=0, sticky="w")

    value_label = tk.Label(frame, text="--", font=("TkDefaultFont", 18, "bold"),
                            foreground=value_color, background=PANEL)
    value_label.grid(row=0, column=1, padx=(6, 2))

    tk.Label(frame, text=unit, font=("TkDefaultFont", 10), foreground=GREY,
              background=PANEL).grid(row=0, column=2, sticky="w")

    return value_label


def add_toolbar_combo_readout(fig, color: str = INK):
    """
    Add a single bold, large-value readout (no caption/unit chrome) to the
    TkAgg navigation toolbar, e.g. "2,987 psi · 0.03 gpm" — matching the
    reference design's combined Pressure/Flow line. No-op on backends
    without a Tk toolbar (returns None). Returns the Label — update it
    live via `label.configure(text=new_text)`.
    """
    toolbar = getattr(getattr(fig.canvas, "manager", None), "toolbar", None)
    if toolbar is None or not hasattr(toolbar, "winfo_children"):
        return None

    import tkinter as tk

    frame = tk.Frame(toolbar, background=PANEL)
    frame.place(relx=0.5, rely=0.5, anchor="center")

    label = tk.Label(frame, text="--", font=("TkDefaultFont", 13, "bold"),
                      foreground=color, background=PANEL)
    label.pack()
    return label
