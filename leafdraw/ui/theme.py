from PySide6.QtGui import QColor, QPalette

BG_2D = QColor("#1e2227")
GRID_MINOR = QColor(255, 255, 255, 16)
GRID_MAJOR = QColor(255, 255, 255, 38)
AXIS_X = QColor(220, 80, 80, 150)
AXIS_Y = QColor(90, 200, 90, 150)
PREVIEW = QColor("#ffd23f")
SELECTION = QColor("#4da3ff")
SNAP = QColor("#ffd23f")
ICON = QColor("#dfe6ee")
GRIP = QColor("#3d7bff")
GRIP_HOT = QColor("#ff4d4d")


def dark_palette() -> QPalette:
    p = QPalette()
    window = QColor(45, 49, 54)
    base = QColor(32, 35, 39)
    text = QColor(224, 228, 233)
    disabled = QColor(120, 125, 130)
    highlight = QColor(58, 120, 200)
    roles = {
        QPalette.ColorRole.Window: window,
        QPalette.ColorRole.WindowText: text,
        QPalette.ColorRole.Base: base,
        QPalette.ColorRole.AlternateBase: window,
        QPalette.ColorRole.ToolTipBase: base,
        QPalette.ColorRole.ToolTipText: text,
        QPalette.ColorRole.Text: text,
        QPalette.ColorRole.Button: window,
        QPalette.ColorRole.ButtonText: text,
        QPalette.ColorRole.BrightText: QColor(255, 90, 90),
        QPalette.ColorRole.Link: QColor(100, 160, 240),
        QPalette.ColorRole.Highlight: highlight,
        QPalette.ColorRole.HighlightedText: QColor(255, 255, 255),
        QPalette.ColorRole.PlaceholderText: disabled,
    }
    for role, color in roles.items():
        p.setColor(role, color)
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText, QPalette.ColorRole.WindowText):
        p.setColor(QPalette.ColorGroup.Disabled, role, disabled)
    return p
