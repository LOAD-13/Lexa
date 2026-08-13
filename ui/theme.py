"""Design tokens matching the Lexa design system."""

# ── Backgrounds ────────────────────────────────────────────
BG       = "#0d0e10"
PANEL    = "#16181c"
PANEL2   = "#1c1f24"
ELEV     = "#22262c"
LINE     = "#26292f"
LINE_S   = "#1f2228"   # soft line

# ── Text ────────────────────────────────────────────────────
FG    = "#e6e7e9"
FG2   = "#b8bbc1"
MUTED = "#7d8089"
DIM   = "#54575e"

# ── Accent (green  ≈ oklch 0.74 0.13 155) ──────────────────
ACCENT      = "#6ec99a"
ACCENT_SOFT = "rgba(110, 201, 154, 36)"   # ~14 %
ACCENT_LINE = "rgba(110, 201, 154, 89)"   # ~35 %
ACCENT_TEXT = "#0a1610"                    # text on accent bg

# ── Status ──────────────────────────────────────────────────
WARN   = "#c4a84f"   # oklch(0.78 0.13  75)
DANGER = "#c97272"   # oklch(0.70 0.16  25)
INFO   = "#7b8ebb"   # oklch(0.72 0.10 240)

WARN_SOFT   = "rgba(196, 168,  79, 36)"
DANGER_SOFT = "rgba(201, 114, 114, 36)"
INFO_SOFT   = "rgba(123, 142, 187, 36)"

# ── Radii ────────────────────────────────────────────────────
R_SM = 7
R_MD = 8
R_LG = 10
R_XL = 12

# ── Global stylesheet ────────────────────────────────────────
GLOBAL_QSS = f"""
* {{
    outline: none;
}}
QWidget {{
    background: transparent;
    color: {FG};
    font-family: "Segoe UI", "Inter", -apple-system, sans-serif;
    font-size: 13px;
    selection-background-color: {ACCENT_SOFT};
    selection-color: {FG};
}}
/* FIX: Labels with setStyleSheet() lose global background:transparent.
   Explicitly setting it here ensures no black "frame" appears. */
QLabel {{
    background: transparent;
    color: {FG};
}}
QMainWindow {{
    background: {BG};
}}
/* Scrollbars */
QScrollBar:vertical {{
    width: 8px;
    background: transparent;
    margin: 2px 0;
}}
QScrollBar::handle:vertical {{
    background: {LINE};
    border-radius: 4px;
    min-height: 24px;
}}
QScrollBar::handle:vertical:hover {{
    background: {ELEV};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    background: transparent;
    height: 0;
}}
QScrollBar:horizontal {{
    height: 8px;
    background: transparent;
    margin: 0 2px;
}}
QScrollBar::handle:horizontal {{
    background: {LINE};
    border-radius: 4px;
    min-width: 24px;
}}
QScrollBar::handle:horizontal:hover {{
    background: {ELEV};
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal,
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
    background: transparent;
    width: 0;
}}
/* Tooltip */
QToolTip {{
    background: {ELEV};
    color: {FG};
    border: 1px solid {LINE};
    border-radius: 6px;
    padding: 4px 8px;
    font-size: 12px;
}}
/* ComboBox */
QComboBox {{
    background: {PANEL2};
    border: 1px solid {LINE};
    border-radius: {R_SM}px;
    color: {FG};
    padding: 4px 28px 4px 10px;
    font-size: 12px;
    min-height: 26px;
}}
QComboBox:hover {{
    border-color: {MUTED};
}}
QComboBox::drop-down {{
    border: none;
    width: 20px;
}}
QComboBox::down-arrow {{
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid {MUTED};
    margin-right: 6px;
}}
QComboBox QAbstractItemView {{
    background: {ELEV};
    border: 1px solid {LINE};
    border-radius: {R_SM}px;
    color: {FG};
    selection-background-color: {PANEL};
    selection-color: {FG};
    padding: 4px;
    outline: none;
}}
QComboBox QAbstractItemView::item {{
    padding: 6px 10px;
    border-radius: 5px;
    min-height: 24px;
}}
/* Text areas */
QPlainTextEdit, QTextEdit {{
    background: {BG};
    border: 1px solid {LINE};
    border-radius: {R_MD}px;
    color: {FG2};
    font-family: "Consolas", "JetBrains Mono", monospace;
    font-size: 12px;
    padding: 8px;
    selection-background-color: {ACCENT_SOFT};
}}
/* Splitter — la zona de arrastre es mas ancha que la linea visible */
QSplitter::handle {{
    background: transparent;
}}
QSplitter::handle:horizontal {{
    width: 7px;
    image: none;
}}
QSplitter::handle:vertical {{
    height: 7px;
}}
QSplitter::handle:hover {{
    background: {ACCENT_LINE};
}}
QSplitter::handle:pressed {{
    background: {ACCENT};
}}
/* Dialogos */
QDialog {{
    background: {PANEL};
}}
QMessageBox {{
    background: {PANEL};
}}
QMessageBox QLabel {{
    color: {FG};
    font-size: 13px;
}}
QMessageBox QPushButton {{
    background: {PANEL2};
    color: {FG};
    border: 1px solid {LINE};
    border-radius: {R_SM}px;
    padding: 6px 16px;
    min-width: 72px;
    font-size: 12px;
}}
QMessageBox QPushButton:hover {{
    background: {ELEV};
}}
QMessageBox QPushButton:default {{
    background: {ACCENT};
    color: {ACCENT_TEXT};
    border-color: transparent;
    font-weight: 600;
}}
"""
