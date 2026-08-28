from __future__ import annotations

# CSS rules are intentionally kept as readable single rules for Qt's parser.
# ruff: noqa: E501
from dataclasses import dataclass

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QColor, QPalette


@dataclass(frozen=True)
class ThemeSpec:
    id: str
    label: str
    dark: bool
    accent: str
    window: str
    surface: str
    surface_alt: str
    text: str
    muted: str
    border: str
    selection: str
    success: str
    warning: str
    danger: str


THEMES: tuple[ThemeSpec, ...] = (
    ThemeSpec(
        "web-aligned", "Web Aligned (Default)", False, "#2563eb", "#f8fafc", "#ffffff",
        "#f1f5f9", "#0f172a", "#64748b", "#e2e8f0", "#eff6ff", "#16a34a",
        "#d97706", "#dc2626",
    ),
    ThemeSpec(
        "clean-light", "Clean Light", False, "#2563a8", "#f3f4f1", "#ffffff",
        "#f8f8f4", "#1d211f", "#68706a", "#d9ddd5", "#dcecff", "#127453",
        "#b36b00", "#b3372d",
    ),
    ThemeSpec(
        "night-shift", "Night Shift", True, "#57c79e", "#101715", "#18211e",
        "#202b27", "#edf7f1", "#a7b9af", "#33443d", "#15382c", "#57c79e",
        "#f2bc5e", "#ff7a72",
    ),
    ThemeSpec(
        "high-contrast", "High Contrast", False, "#003f9e", "#ffffff", "#ffffff",
        "#f2f2f2", "#000000", "#1f1f1f", "#000000", "#dce9ff", "#006b2f",
        "#8a4b00", "#b00020",
    ),
    ThemeSpec(
        "warm-traditional", "Warm Traditional", False, "#9a4d2f", "#fbf4e9", "#fffdf8",
        "#f7eadb", "#2d2019", "#78685e", "#dfc8b3", "#f5d27b", "#2d7a55",
        "#a96a12", "#a63c32",
    ),
    ThemeSpec(
        "modern-cafe", "Modern Café", False, "#8b5e3c", "#f4f0ea", "#fffdf9",
        "#f7f1e8", "#2c221b", "#756a60", "#ded3c7", "#f1dfc8", "#34745d",
        "#a86718", "#a94336",
    ),
    ThemeSpec(
        "fine-dining", "Fine Dining", True, "#d2aa62", "#11100f", "#1b1916",
        "#28231d", "#f5efe3", "#b9a486", "#4c4031", "#3d3020", "#75c49b",
        "#e1b866", "#ff8a80",
    ),
    ThemeSpec(
        "compact-pos", "Compact POS", False, "#2563a8", "#eef3f8", "#ffffff",
        "#f5f8fb", "#102f5b", "#536b84", "#c9d8e8", "#dceafe", "#18734e",
        "#a76412", "#a53732",
    ),
    ThemeSpec(
        "winter", "Winter", False, "#2578ad", "#eef7fb", "#ffffff", "#f4fbff",
        "#162433", "#597283", "#c8dce8", "#dceeff", "#217657", "#a76412",
        "#a93d3d",
    ),
)

THEME_BY_ID = {theme.id: theme for theme in THEMES}
SYSTEM_THEME_ID = "system"
SETTINGS_ORG = "ChoiceOye"
SETTINGS_APP = "EnterpriseCommerceERP"


def theme_ids() -> tuple[str, ...]:
    return (SYSTEM_THEME_ID, *(theme.id for theme in THEMES))


def theme_label(theme_id: str) -> str:
    if theme_id == SYSTEM_THEME_ID:
        return "System (Windows)"
    return THEME_BY_ID.get(theme_id, THEMES[0]).label


def load_theme_preference() -> str:
    settings = QSettings(SETTINGS_ORG, SETTINGS_APP)
    theme_id = str(settings.value("ui/theme", SYSTEM_THEME_ID))
    return theme_id if theme_id in theme_ids() else SYSTEM_THEME_ID


def save_theme_preference(theme_id: str) -> None:
    settings = QSettings(SETTINGS_ORG, SETTINGS_APP)
    settings.setValue("ui/theme", theme_id if theme_id in theme_ids() else SYSTEM_THEME_ID)
    settings.sync()


def load_reduced_motion() -> bool:
    settings = QSettings(SETTINGS_ORG, SETTINGS_APP)
    value = settings.value("ui/reduced_motion", False)
    return str(value).lower() in {"1", "true", "yes", "on"}


def save_reduced_motion(enabled: bool) -> None:
    settings = QSettings(SETTINGS_ORG, SETTINGS_APP)
    settings.setValue("ui/reduced_motion", bool(enabled))
    settings.sync()


def system_prefers_dark(app) -> bool:  # type: ignore[no-untyped-def]
    try:
        scheme = app.styleHints().colorScheme()
        if scheme == Qt.ColorScheme.Dark:
            return True
        if scheme == Qt.ColorScheme.Light:
            return False
    except AttributeError:
        pass
    return app.palette().color(QPalette.ColorRole.Window).lightness() < 128


def resolve_theme(theme_id: str, app) -> ThemeSpec:  # type: ignore[no-untyped-def]
    if theme_id == SYSTEM_THEME_ID:
        return THEME_BY_ID["night-shift"] if system_prefers_dark(app) else THEME_BY_ID["web-aligned"]
    return THEME_BY_ID.get(theme_id, THEME_BY_ID["web-aligned"])


def _palette(theme: ThemeSpec) -> QPalette:
    palette = QPalette()
    roles = {
        QPalette.ColorRole.Window: theme.window,
        QPalette.ColorRole.Base: theme.surface,
        QPalette.ColorRole.AlternateBase: theme.surface_alt,
        QPalette.ColorRole.Button: theme.surface,
        QPalette.ColorRole.Text: theme.text,
        QPalette.ColorRole.WindowText: theme.text,
        QPalette.ColorRole.ButtonText: theme.text,
        QPalette.ColorRole.PlaceholderText: theme.muted,
        QPalette.ColorRole.Highlight: theme.accent,
        QPalette.ColorRole.HighlightedText: "#ffffff",
        QPalette.ColorRole.ToolTipBase: theme.surface,
        QPalette.ColorRole.ToolTipText: theme.text,
    }
    for role, color in roles.items():
        palette.setColor(role, QColor(color))
    return palette


def stylesheet(theme: ThemeSpec) -> str:
    return f"""
    QWidget {{ color: {theme.text}; font-family: 'Segoe UI'; font-size: 10pt; }}
    QMainWindow, QWidget#erpRoot {{ background: {theme.window}; }}
    QLabel#appTitle {{ font-size: 20pt; font-weight: 700; color: {theme.text}; }}
    QLabel#pageTitle {{ font-size: 16pt; font-weight: 700; color: {theme.text}; }}
    QLabel#pageSubtitle, QLabel#mutedLabel {{ color: {theme.muted}; }}
    QGroupBox {{ border: 1px solid {theme.border}; border-radius: 12px; margin-top: 12px; padding: 14px; background: {theme.surface}; font-weight: 600; }}
    QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 6px; color: {theme.muted}; }}
    QLineEdit, QTextEdit, QComboBox, QSpinBox, QTableWidget {{ background: {theme.surface}; border: 1px solid {theme.border}; border-radius: 8px; padding: 7px; selection-background-color: {theme.selection}; selection-color: {theme.text}; min-height: 24px; }}
    QLineEdit:focus, QTextEdit:focus, QComboBox:focus, QSpinBox:focus {{ border: 2px solid {theme.accent}; padding: 6px; }}
    QPushButton {{ background: {theme.surface}; border: 1px solid {theme.border}; border-radius: 8px; padding: 8px 14px; font-weight: 600; min-height: 28px; }}
    QPushButton:hover {{ background: {theme.selection}; border-color: {theme.accent}; }}
    QPushButton:pressed {{ background: {theme.accent}; color: #ffffff; }}
    QPushButton:disabled {{ color: {theme.muted}; background: {theme.surface_alt}; }}
    QPushButton#primaryButton {{ background: {theme.accent}; color: #ffffff; border-color: {theme.accent}; }}
    QPushButton#primaryButton:hover {{ background: {theme.accent}; border-color: {theme.accent}; }}
    QTableWidget {{ gridline-color: {theme.border}; alternate-background-color: {theme.surface_alt}; min-height: 250px; }}
    QHeaderView::section {{ background: {theme.surface_alt}; color: {theme.muted}; border: 0; border-bottom: 1px solid {theme.border}; padding: 8px; font-weight: 700; }}
    QTabWidget::pane {{ border: 1px solid {theme.border}; border-radius: 10px; background: {theme.surface}; }}
    QTabBar::tab {{ background: {theme.surface_alt}; color: {theme.muted}; padding: 9px 14px; margin-right: 2px; border-radius: 7px; }}
    QTabBar::tab:selected {{ background: {theme.selection}; color: {theme.text}; font-weight: 700; }}
    QListWidget#sidebar {{ background: {theme.surface}; border: 0; border-right: 1px solid {theme.border}; padding: 12px 8px; outline: 0; }}
    QListWidget#sidebar::item {{ padding: 11px 14px; margin: 2px 0; border-radius: 8px; color: {theme.muted}; }}
    QListWidget#sidebar::item:hover {{ background: {theme.surface_alt}; color: {theme.text}; }}
    QListWidget#sidebar::item:selected {{ background: {theme.selection}; color: {theme.text}; font-weight: 700; border-left: 3px solid {theme.accent}; }}
    QScrollBar:vertical {{ background: {theme.surface_alt}; width: 10px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: {theme.border}; border-radius: 5px; min-height: 25px; }}
    QStatusBar {{ background: {theme.surface}; color: {theme.muted}; border-top: 1px solid {theme.border}; }}
    QLabel#notification {{ background: {theme.success}; color: #ffffff; border-radius: 10px; padding: 10px 16px; font-weight: 700; }}
    QLabel#notification[notificationType="error"] {{ background: {theme.danger}; }}
    QLabel#notification[notificationType="info"] {{ background: {theme.accent}; }}
    QLabel#notification[notificationType="running"] {{ background: #2563eb; }}
    QProgressBar {{ border: 0; background: {theme.surface_alt}; border-radius: 4px; height: 7px; text-align: center; }}
    QProgressBar::chunk {{ background: {theme.accent}; border-radius: 4px; }}
    """


def apply_theme(app, theme_id: str | None = None) -> ThemeSpec:  # type: ignore[no-untyped-def]
    selected = theme_id or load_theme_preference()
    theme = resolve_theme(selected, app)
    app.setPalette(_palette(theme))
    app.setStyleSheet(stylesheet(theme))
    app.setProperty("erpThemeId", selected)
    app.setProperty("erpReducedMotion", load_reduced_motion())
    return theme
