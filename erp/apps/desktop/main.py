from __future__ import annotations

import json as jsonlib
import sys
import uuid
from collections.abc import Callable
from pathlib import Path

from erp.apps.desktop.api_client import (
    ApiHealthClient,
    ApiResponseError,
    CredentialStorageError,
)
from erp.apps.desktop.auth import (
    ACCOUNT_STATUSES,
    DESKTOP_PREFERENCE_KEYS,
    VENDOR_ONBOARDING_OPTIONS,
    VENDOR_SELF_PERMISSIONS,
    VENDOR_STATUSES,
    build_vendor_account_payload,
    navigation_visibility,
    public_auth_url,
    role_names_for_session,
    safe_login_error,
    session_display_lines,
    should_load_vendor_self,
    vendor_onboarding_result_lines,
)
from erp.packages.core.config import get_settings

NAV_ITEMS = (
    "Dashboard",
    "Products",
    "Customers",
    "Inventory",
    "Orders",
    "WooCommerce",
    "Marketplace",
    "Accounting",
    "Settings",
    "Admin",
)
VENDOR_WORKSPACE_TABS = (
    "Overview",
    "Stock",
    "Stock Movements",
    "Products",
    "Orders / Sales",
    "Financial Ledger",
    "Settlements",
    "Reports",
    "Linked Users",
    "Audit",
)
LEDGER_WORKSPACE_TABS = (
    "Overview",
    "Chart of Accounts",
    "Journals",
    "Trial Balance",
    "Profit & Loss",
    "Balance Sheet",
    "Cash Flow",
    "Vendor Payables",
    "Inventory",
    "Reconciliation",
)


def navigation_items() -> tuple[str, ...]:
    return NAV_ITEMS


def operation_notification_message(operation: str, state: str, detail: str | None = None) -> str:
    if state == "started":
        return f"Starting: {operation}"
    if state == "running":
        return f"Running: {operation}"
    if state == "completed":
        return f"Completed: {operation}"
    if state == "failed":
        return f"Failed: {operation}" + (f" — {detail}" if detail else "")
    return f"{operation}: {state}"


class OperationNotifications:
    """Send consistent lifecycle notifications through the desktop toast surface."""

    def __init__(self, emit: Callable[[str, str], None]) -> None:
        self._emit = emit

    def show(self, operation: str, state: str, detail: str | None = None) -> None:
        kind = {
            "failed": "error",
            "completed": "success",
            "running": "running",
        }.get(state, "info")
        self._emit(operation_notification_message(operation, state, detail), kind)


def woocommerce_sync_transition(
    previous_status: str | None,
    status: str,
    *,
    attempts: object = 0,
    error: str | None = None,
) -> tuple[str, str | None] | None:
    if status == previous_status:
        return None
    if status in {"queued", "running"}:
        return status, f"attempt {attempts}"
    if status == "success":
        return "completed", None
    return "failed", error or "see sync history for details"


def woocommerce_sync_completion_message(stats: dict[str, object]) -> tuple[str, bool]:
    failed_media = int(stats.get("failed_media_pushes") or 0)
    pending_media = int(stats.get("pending_media_pushes") or 0)
    failed_videos = int(stats.get("failed_video_pushes") or 0)
    pending_videos = int(stats.get("pending_video_pushes") or 0)
    failed_products = int(stats.get("failed_product_pushes") or 0)
    pending_products = int(stats.get("pending_product_pushes") or 0)
    archived_missing = int(stats.get("archived_missing_products") or 0)
    media_error = str(stats.get("last_media_error") or "").strip()
    video_error = str(stats.get("last_video_error") or "").strip()

    unresolved = (
        failed_media
        or pending_media
        or failed_videos
        or pending_videos
        or failed_products
        or pending_products
    )
    if unresolved:
        attention_parts: list[str] = []
        if failed_products or pending_products:
            attention_parts.append(f"{failed_products + pending_products} product update(s)")
        if failed_media or pending_media:
            attention_parts.append(f"{failed_media + pending_media} media item(s)")
        if failed_videos or pending_videos:
            attention_parts.append(f"{failed_videos + pending_videos} video update(s)")
        message = (
            f"WooCommerce data sync completed, but {', '.join(attention_parts)} need attention."
        )
        if media_error:
            message = f"{message} Latest reason: {media_error}"
        elif video_error:
            message = f"{message} Latest reason: {video_error}"
        return message, False
    if archived_missing:
        suffix = "product" if archived_missing == 1 else "products"
        return (
            "WooCommerce sync completed. "
            f"{archived_missing} {suffix} were archived locally because they were deleted online.",
            True,
        )
    return "WooCommerce sync completed.", True


def woocommerce_sync_running_message(run: dict[str, object]) -> str:
    stats = run.get("stats")
    if not isinstance(stats, dict):
        stats = {}
    phase = str(stats.get("current_phase") or "").strip()
    attempts = run.get("attempts", 0)
    worker = str(run.get("worker_id") or "waiting for worker")
    if phase:
        return f"WooCommerce sync running: {phase} (attempt {attempts}; {worker})."
    return f"WooCommerce sync running (attempt {attempts}; {worker})."


def format_api_error(exc: ApiResponseError, base_url: str) -> str:
    detail = exc.detail.strip()
    lowered = detail.lower()
    if exc.status_code == 0:
        if "timed out" in lowered or "timeout" in lowered:
            return (
                f"API at {base_url} did not complete this request in time. "
                "Use STOP_ERP.bat and start it again if the server is hung."
            )
        return f"API is offline at {base_url}. Start RUN_ERP.bat local or scripts/run_api.ps1."
    if exc.status_code >= 500 and (
        "sqlite3.operationalerror" in lowered
        or "no such column" in lowered
        or "no such table" in lowered
    ):
        return "API database schema is out of date. Run RUN_ERP.bat migrate or scripts/migrate.ps1."
    return f"API error: {detail}"


def is_api_offline_message(message: str) -> bool:
    return message.strip().lower().startswith("api is offline at ")


def recovered_api_page_message(message: str, page_name: str) -> str | None:
    if is_api_offline_message(message):
        return f"API online. {page_name} is ready."
    return None


def run() -> int:
    from PySide6.QtCore import QSettings, Qt, QTimer, QUrl
    from PySide6.QtGui import QDesktopServices
    from PySide6.QtWidgets import (
        QAbstractItemView,
        QApplication,
        QCheckBox,
        QComboBox,
        QFileDialog,
        QFormLayout,
        QFrame,
        QGroupBox,
        QHBoxLayout,
        QInputDialog,
        QLabel,
        QLineEdit,
        QListWidget,
        QMainWindow,
        QMessageBox,
        QPushButton,
        QScrollArea,
        QSizePolicy,
        QSpinBox,
        QSplitter,
        QStackedWidget,
        QTableWidget,
        QTableWidgetItem,
        QTabWidget,
        QTextEdit,
        QVBoxLayout,
        QWidget,
    )

    from erp.apps.desktop import theme
    from erp.apps.desktop.ui_tasks import UiTaskRunner

    settings = get_settings()
    app = QApplication(sys.argv)
    app.setOrganizationName("ChoiceOye")
    app.setApplicationName("Enterprise Commerce ERP")

    # Apply global modern UI styling
    active_theme = theme.resolve_theme(theme.load_theme_preference(), app)
    app.setPalette(theme._palette(active_theme))
    app.setStyleSheet(theme.stylesheet(active_theme))

    window = QMainWindow()
    window.setWindowTitle(settings.app_name)
    window.resize(1180, 760)

    api_base_url = (
        settings.api_base_url.strip() or f"http://{settings.api_host}:{settings.api_port}"
    )
    client = ApiHealthClient(api_base_url)
    task_runner = UiTaskRunner(window)
    preferences = QSettings()
    state: dict[str, object] = {
        "token": None,
        "refresh_token": None,
        "username": None,
        "permissions": [],
        "roles": [],
        "remembered": False,
        "session_payload": {},
        "current_session": {},
        "current_vendor": None,
        "auth_epoch": 0,
        "auth_busy": False,
        "refresh_busy": False,
        "health_busy": False,
        "admin_roles": [],
        "admin_users": [],
        "selected_product_id": None,
        "woo_sync_run_id": None,
    }
    page_messages: list[tuple[str, QLabel]] = []

    screen_stack = QStackedWidget()

    auth_page = QWidget()
    auth_page_layout = QVBoxLayout(auth_page)
    auth_page_layout.addStretch(1)
    auth_title = QLabel(settings.app_name)
    auth_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
    auth_title.setStyleSheet("font-size: 26px; font-weight: 700;")
    auth_page_layout.addWidget(auth_title)
    login_box = QGroupBox("Sign in")
    login_box.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
    login_form = QFormLayout(login_box)
    username_input = QLineEdit()
    username_input.setPlaceholderText("Username, login ID, or email")
    username_input.setText(str(preferences.value(DESKTOP_PREFERENCE_KEYS["username"], "")))
    password_input = QLineEdit()
    password_input.setPlaceholderText("Password")
    password_input.setEchoMode(QLineEdit.EchoMode.Password)
    workspace_input = QLineEdit()
    workspace_input.setPlaceholderText("Workspace slug")
    saved_workspace = str(preferences.value(DESKTOP_PREFERENCE_KEYS["workspace"], "")).strip()
    workspace_input.setText(saved_workspace or "inaam")
    remember_input = QCheckBox("Remember me securely on this computer")
    secure_storage_available = client.secure_storage_available()
    remember_input.setEnabled(secure_storage_available)
    if not secure_storage_available:
        remember_input.setToolTip(
            "Remember Me is disabled because secure operating-system credential storage "
            "is unavailable."
        )
    login_button = QPushButton("Sign in")
    forgot_password_button = QPushButton("Forgot password")
    forgot_password_button.setFlat(True)
    vendor_registration_button = QPushButton("Register as a vendor")
    vendor_registration_button.setFlat(True)
    auth_links = QHBoxLayout()
    auth_links.addWidget(forgot_password_button)
    auth_links.addWidget(vendor_registration_button)
    login_status_label = QLabel("")
    login_status_label.setWordWrap(True)
    login_form.addRow("Login ID", username_input)
    login_form.addRow("Password", password_input)
    login_form.addRow("Workspace", workspace_input)
    login_form.addRow(remember_input)
    login_form.addRow(login_button)
    login_form.addRow(auth_links)
    login_form.addRow(login_status_label)
    auth_page_layout.addWidget(login_box)
    auth_page_layout.addStretch(1)

    root = QWidget()
    root_layout = QHBoxLayout(root)

    sidebar = QListWidget()
    sidebar.setFixedWidth(220)
    for item in navigation_items():
        sidebar.addItem(item)

    content = QVBoxLayout()
    title = QLabel(settings.app_name)
    title.setAlignment(Qt.AlignmentFlag.AlignLeft)
    title.setStyleSheet("font-size: 22px; font-weight: 600;")

    status_label = QLabel("Checking API health...")
    status_label.setWordWrap(True)
    status_label.setStyleSheet("font-weight: 600;")

    auth_box = QGroupBox("Authenticated session")
    auth_box.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
    auth_layout = QHBoxLayout(auth_box)
    logout_button = QPushButton("Logout")
    session_label = QLabel("Not signed in")
    session_label.setWordWrap(True)
    auth_layout.addWidget(session_label)
    auth_layout.addWidget(logout_button)

    password_change_page = QWidget()
    password_change_layout = QVBoxLayout(password_change_page)
    password_change_layout.addStretch(1)
    password_change_box = QGroupBox("Password change required")
    password_change_box.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
    password_change_form = QFormLayout(password_change_box)
    password_change_explanation = QLabel(
        "This temporary-password session is restricted until you choose a new password."
    )
    password_change_explanation.setWordWrap(True)
    current_password_input = QLineEdit()
    current_password_input.setEchoMode(QLineEdit.EchoMode.Password)
    new_password_input = QLineEdit()
    new_password_input.setEchoMode(QLineEdit.EchoMode.Password)
    confirm_password_input = QLineEdit()
    confirm_password_input.setEchoMode(QLineEdit.EchoMode.Password)
    password_change_button = QPushButton("Change password")
    password_change_logout_button = QPushButton("Logout")
    password_change_message = QLabel("")
    password_change_message.setWordWrap(True)
    password_change_form.addRow(password_change_explanation)
    password_change_form.addRow("Current password", current_password_input)
    password_change_form.addRow("New password", new_password_input)
    password_change_form.addRow("Confirm password", confirm_password_input)
    password_change_form.addRow(password_change_button)
    password_change_form.addRow(password_change_logout_button)
    password_change_form.addRow(password_change_message)
    password_change_layout.addWidget(password_change_box)
    password_change_layout.addStretch(1)

    screen_stack.addWidget(auth_page)
    screen_stack.addWidget(root)
    screen_stack.addWidget(password_change_page)

    stack = QStackedWidget()

    def set_status(message: str, *, ok: bool = True) -> None:
        status_label.setText(message)
        color = "#166534" if ok else "#991b1b"
        status_label.setStyleSheet(f"color: {color}; font-weight: 600;")

    def set_page_message(message: QLabel, text: str, *, ok: bool | None = None) -> None:
        message.setText(text)
        if ok is None:
            message.setStyleSheet("")
            return
        color = "#166534" if ok else "#991b1b"
        message.setStyleSheet(f"color: {color}; font-weight: 600;")

    def apply_api_health_status(health, *, success_message: str | None = None) -> bool:  # type: ignore[no-untyped-def]
        if health.reachable:
            set_status(
                success_message
                or f"API online: {health.status}. {health.module_count} modules registered.",
                ok=True,
            )
            # Page requests can fail while the API is starting and leave local
            # page labels stale after the shared header recovers. Clear only that
            # specific connectivity error; keep real business/API errors visible.
            for page_name, page_message in page_messages:
                recovered = recovered_api_page_message(page_message.text(), page_name)
                if recovered:
                    set_page_message(page_message, recovered, ok=True)
            return True
        set_status(
            f"{health.detail} Start the API with RUN_ERP.bat local or scripts/run_api.ps1.",
            ok=False,
        )
        return False

    def refresh_api_health_status(*, success_message: str | None = None) -> bool:
        return apply_api_health_status(client.get_health(), success_message=success_message)

    def refresh_api_health_async() -> None:
        if bool(state.get("health_busy")):
            return
        state["health_busy"] = True

        def result(value: object) -> None:
            if hasattr(value, "reachable"):
                apply_api_health_status(value)

        def error(_exc: BaseException) -> None:
            set_status("API health check could not be completed.", ok=False)

        def finished() -> None:
            state["health_busy"] = False

        task_runner.start(
            client.get_health,
            on_result=result,
            on_error=error,
            on_finished=finished,
        )

    def current_token() -> str | None:
        token = client.access_token
        if token:
            state["token"] = token
        if not isinstance(token, str) or not token:
            set_status("Login required for this screen.", ok=False)
            return None
        return token

    def make_page() -> tuple[QWidget, QVBoxLayout, QLabel]:
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        page = QWidget()
        scroll_area.setWidget(page)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        message = QLabel("")
        message.setWordWrap(True)
        layout.addWidget(message)
        return scroll_area, layout, message

    def make_table(headers: list[str]) -> QTableWidget:
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.verticalHeader().setVisible(False)
        table.setAlternatingRowColors(True)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        return table

    def populate_table(
        table: QTableWidget,
        rows: list[dict[str, object]],
        columns: list[tuple[str, str]],
    ) -> None:
        table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            for column_index, (key, _label) in enumerate(columns):
                value = row.get(key, "")
                if isinstance(value, list):
                    value = ", ".join(str(item) for item in value)
                table.setItem(row_index, column_index, QTableWidgetItem(str(value or "")))
        table.resizeColumnsToContents()

    def woocommerce_run_rows(runs: list[dict[str, object]]) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        for run in runs:
            stats = run.get("stats")
            if not isinstance(stats, dict):
                stats = {}
            rows.append(
                {
                    "started_at": run.get("started_at"),
                    "status": run.get("status"),
                    "finished_at": run.get("finished_at"),
                    "pulled_products": stats.get("pulled_products", 0),
                    "pulled_customers": stats.get("pulled_customers", 0),
                    "pulled_orders": stats.get("pulled_orders", 0),
                    "pushed_records": stats.get("pushed_records", 0),
                    "pushed_media_records": stats.get("pushed_media_records", 0),
                    "pushed_video_records": stats.get("pushed_video_records", 0),
                    "deferred_media_records": stats.get("deferred_media_records", 0),
                    "deferred_video_records": stats.get("deferred_video_records", 0),
                    "pending_media_pushes": stats.get("pending_media_pushes", 0),
                    "pending_video_pushes": stats.get("pending_video_pushes", 0),
                    "failed_media_pushes": stats.get("failed_media_pushes", 0),
                    "failed_video_pushes": stats.get("failed_video_pushes", 0),
                    "archived_missing_products": stats.get("archived_missing_products", 0),
                    "failed_records": stats.get("failed_records", 0),
                    "error": run.get("error") or "",
                }
            )
        return rows

    def woocommerce_status_summary(
        config: dict[str, object],
        runs: list[dict[str, object]],
        conflicts: list[dict[str, object]],
    ) -> str:
        lines = [
            f"Configured: {config.get('configured', False)}",
            f"Site URL: {config.get('site_url') or 'not configured'}",
            f"Consumer key: {config.get('consumer_key_hint') or 'not stored'}",
            f"WordPress media user: {config.get('wordpress_username') or 'not configured'}",
            f"WordPress media uploads: {config.get('wordpress_media_configured', False)}",
            f"Video plugin detected: {config.get('video_plugin_detected', False)}",
            f"Video plugin compatible: {config.get('video_plugin_compatible', False)}",
            f"Video plugin version: {config.get('video_plugin_version') or 'not detected'}",
            (
                "WordPress upload limit: "
                f"{config.get('wordpress_max_upload_bytes') or 'unknown'} bytes"
            ),
            f"Webhook signing: {config.get('webhook_secret_configured', False)}",
            f"Pending product pushes: {config.get('pending_product_pushes', 0)}",
            f"Pending media pushes: {config.get('pending_media_pushes', 0)}",
            f"Pending video pushes: {config.get('pending_video_pushes', 0)}",
            f"Failed product pushes: {config.get('failed_product_pushes', 0)}",
            f"Failed media pushes: {config.get('failed_media_pushes', 0)}",
            f"Failed video pushes: {config.get('failed_video_pushes', 0)}",
            f"Recent sync runs: {len(runs)}",
            f"Open conflicts: {len(conflicts)}",
        ]
        last_media_error = str(config.get("last_media_error") or "").strip()
        if last_media_error:
            lines.extend(["", "Last media error", last_media_error])
        last_video_error = str(config.get("last_video_error") or "").strip()
        if last_video_error:
            lines.extend(["", "Last video error", last_video_error])
        if runs:
            latest = runs[0]
            stats = latest.get("stats")
            if not isinstance(stats, dict):
                stats = {}
            lines.extend(
                [
                    "",
                    "Last sync",
                    f"Status: {latest.get('status') or 'unknown'}",
                    f"Current phase: {stats.get('current_phase') or 'finished'}",
                    f"Started: {latest.get('started_at') or ''}",
                    f"Finished: {latest.get('finished_at') or ''}",
                    f"Products pulled from WooCommerce: {stats.get('pulled_products', 0)}",
                    f"Customers pulled from WooCommerce: {stats.get('pulled_customers', 0)}",
                    f"Orders pulled from WooCommerce: {stats.get('pulled_orders', 0)}",
                    f"ERP records pushed to WooCommerce: {stats.get('pushed_records', 0)}",
                    (
                        "Product media updates pushed to WooCommerce: "
                        f"{stats.get('pushed_media_records', 0)}"
                    ),
                    f"Product media updates deferred: {stats.get('deferred_media_records', 0)}",
                    f"Product video updates pushed: {stats.get('pushed_video_records', 0)}",
                    f"Product video updates deferred: {stats.get('deferred_video_records', 0)}",
                    (
                        "Products archived locally because they were deleted online: "
                        f"{stats.get('archived_missing_products', 0)}"
                    ),
                    f"Pending media pushes after sync: {stats.get('pending_media_pushes', 0)}",
                    f"Pending video pushes after sync: {stats.get('pending_video_pushes', 0)}",
                    f"Failed media pushes after sync: {stats.get('failed_media_pushes', 0)}",
                    f"Failed video pushes after sync: {stats.get('failed_video_pushes', 0)}",
                    f"Push failures: {stats.get('failed_records', 0)}",
                ]
            )
            error = str(latest.get("error") or "").strip()
            if error:
                lines.extend(["", "Last error", error])
        return "\n".join(lines)

    dashboard_page, dashboard_layout, dashboard_message = make_page()
    dashboard_counts = QLabel("Login to load dashboard counts.")
    dashboard_counts.setStyleSheet("font-size: 16px;")
    dashboard_refresh = QPushButton("Refresh Dashboard")
    dashboard_sync_products_button = QPushButton("Sync Products")
    dashboard_sync_all_button = QPushButton("Sync All Content")
    dashboard_layout.addWidget(dashboard_counts)
    dashboard_layout.addWidget(dashboard_sync_products_button)
    dashboard_layout.addWidget(dashboard_sync_all_button)
    dashboard_layout.addStretch(1)
    dashboard_layout.addWidget(dashboard_refresh)

    product_page, product_layout, product_message = make_page()
    product_columns = [
        ("id", "ID"),
        ("name", "Name"),
        ("sku", "SKU"),
        ("status", "Status"),
        ("product_type", "Type"),
        ("regular_price_minor", "Price"),
        ("stock_quantity", "Stock"),
        ("menu_order", "Menu Order"),
        ("updated_at", "Updated"),
    ]
    product_table = make_table([label for _key, label in product_columns])
    product_table.setColumnHidden(0, True)
    product_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
    product_search_input = QLineEdit()
    product_search_input.setPlaceholderText("Search products")
    product_status_filter = QComboBox()
    product_status_filter.addItem("All", "all")
    product_status_filter.addItem("Published", "active")
    product_status_filter.addItem("Draft", "draft")
    product_status_filter.addItem("Trash", "archived")
    product_sort_input = QComboBox()
    product_sort_input.addItem("Sort: Name", "name")
    product_sort_input.addItem("SKU", "sku")
    product_sort_input.addItem("Price", "regular_price_minor")
    product_sort_input.addItem("Stock", "stock_quantity")
    product_sort_input.addItem("Menu order", "menu_order")
    product_sort_input.addItem("Updated", "updated_at")
    product_sort_order = QComboBox()
    product_sort_order.addItem("Ascending", "asc")
    product_sort_order.addItem("Descending", "desc")
    product_bulk_action = QComboBox()
    product_bulk_action.addItem("Bulk actions", "")
    product_bulk_action.addItem("Publish selected", "active")
    product_bulk_action.addItem("Mark selected as Draft", "draft")
    product_bulk_action.addItem("Move selected to Trash", "archived")
    product_bulk_action.addItem("Restore selected", "active")
    product_bulk_action.addItem("Delete selected permanently", "delete_permanent")
    product_bulk_button = QPushButton("Apply")
    product_reorder_button = QPushButton("Save menu order")
    product_editor = QGroupBox("Product Editor")
    product_editor.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
    product_editor_layout = QVBoxLayout(product_editor)
    product_tabs = QTabWidget()
    product_name_input = QLineEdit()
    product_slug_input = QLineEdit()
    product_sku_input = QLineEdit()
    product_barcode_input = QLineEdit()
    product_type_input = QComboBox()
    product_type_input.addItems(["simple", "variable"])
    product_status_input = QComboBox()
    product_status_input.addItems(["active", "draft", "archived"])
    product_category_combo = QComboBox()
    product_brand_combo = QComboBox()
    product_vendor_combo = QComboBox()
    CREATE_CATEGORY_ACTION = "__create_category__"
    CREATE_BRAND_ACTION = "__create_brand__"
    reference_selection_state: dict[str, str | None] = {"category": None, "brand": None}
    product_description_input = QTextEdit()
    product_description_input.setFixedHeight(90)
    product_short_description_input = QTextEdit()
    product_short_description_input.setFixedHeight(70)

    product_regular_price_input = QSpinBox()
    product_regular_price_input.setRange(0, 2_000_000_000)
    product_sale_price_input = QSpinBox()
    product_sale_price_input.setRange(0, 2_000_000_000)
    product_sale_price_input.setSpecialValueText("")
    product_global_unique_id_input = QLineEdit()
    product_featured_input = QCheckBox()
    product_visibility_input = QComboBox()
    product_visibility_input.addItems(["visible", "catalog", "search", "hidden"])
    product_tax_status_input = QComboBox()
    product_tax_status_input.addItems(["taxable", "shipping", "none"])
    product_tax_class_input = QLineEdit()

    product_manage_stock_input = QCheckBox()
    product_stock_quantity_input = QSpinBox()
    product_stock_quantity_input.setRange(0, 2_000_000_000)
    product_stock_status_input = QComboBox()
    product_stock_status_input.addItems(["instock", "outofstock", "onbackorder"])
    product_backorders_input = QComboBox()
    product_backorders_input.addItems(["no", "notify", "yes"])
    product_sold_individually_input = QCheckBox()

    product_weight_input = QLineEdit()
    product_length_input = QLineEdit()
    product_width_input = QLineEdit()
    product_height_input = QLineEdit()
    product_shipping_class_input = QLineEdit()

    product_image_table = make_table(
        ["ID", "URL", "Alt Text", "Sort", "External ID", "Name", "Sync Status", "Last Synced"]
    )
    product_image_table.setColumnHidden(0, True)
    product_add_image_url_input = QLineEdit()
    product_add_image_url_input.setPlaceholderText("https://example.com/image.jpg")
    product_add_image_button = QPushButton("Add Image URL")
    product_upload_image_button = QPushButton("Upload Image")
    product_remove_image_button = QPushButton("Remove Selected Image")

    product_video_table = make_table(
        [
            "ID",
            "Source",
            "URL",
            "Name",
            "Sort",
            "Sync Status",
            "Storefront URL",
            "Last Synced",
            "Added",
        ]
    )
    product_video_table.setColumnHidden(0, True)
    product_video_table.sortItems(4, Qt.SortOrder.AscendingOrder)
    product_video_table.setSortingEnabled(True)
    product_add_video_url_input = QLineEdit()
    product_add_video_url_input.setPlaceholderText("https://youtube.com/... or https://example.com/video.mp4")
    product_add_video_button = QPushButton("Add Video URL")
    product_upload_video_button = QPushButton("Upload MP4")
    product_open_video_button = QPushButton("Open Selected Video")
    product_remove_video_button = QPushButton("Remove Selected Video")

    product_variant_table = make_table(
        [
            "ID",
            "Name",
            "SKU",
            "Barcode",
            "Price Minor",
            "Sale Minor",
            "Cost Minor",
            "Currency",
            "Attributes JSON",
            "Active",
        ]
    )
    product_variant_table.setColumnHidden(0, True)
    product_add_variant_button = QPushButton("Add Variant")
    product_remove_variant_button = QPushButton("Remove Selected Variant")

    product_seo_title_input = QLineEdit()
    product_seo_description_input = QTextEdit()
    product_seo_description_input.setFixedHeight(70)
    product_reviews_allowed_input = QCheckBox()
    product_reviews_allowed_input.setChecked(True)
    product_purchase_note_input = QTextEdit()
    product_purchase_note_input.setFixedHeight(70)
    product_menu_order_input = QSpinBox()
    product_menu_order_input.setRange(-1_000_000, 1_000_000)
    product_tags_input = QLineEdit()
    product_tags_input.setPlaceholderText("Comma-separated tags")
    product_upsell_ids_input = QLineEdit()
    product_cross_sell_ids_input = QLineEdit()
    product_grouped_ids_input = QLineEdit()
    product_attributes_input = QTextEdit()
    product_attributes_input.setFixedHeight(80)
    product_attributes_input.setPlaceholderText("JSON list")
    product_default_attributes_input = QTextEdit()
    product_default_attributes_input.setFixedHeight(80)
    product_default_attributes_input.setPlaceholderText("JSON list")
    product_custom_metadata_input = QTextEdit()
    product_custom_metadata_input.setFixedHeight(80)
    product_custom_metadata_input.setPlaceholderText("JSON object")
    product_metadata_input = QTextEdit()
    product_metadata_input.setFixedHeight(80)
    product_metadata_input.setPlaceholderText("JSON object")

    basic_tab = QWidget()
    basic_layout = QFormLayout(basic_tab)
    basic_layout.addRow("Name", product_name_input)
    basic_layout.addRow("Slug", product_slug_input)
    basic_layout.addRow("SKU", product_sku_input)
    basic_layout.addRow("Barcode", product_barcode_input)
    basic_layout.addRow("Type", product_type_input)
    basic_layout.addRow("Status", product_status_input)
    basic_layout.addRow("Category", product_category_combo)
    basic_layout.addRow("Brand", product_brand_combo)
    basic_layout.addRow("Vendor", product_vendor_combo)
    basic_layout.addRow("Description", product_description_input)
    basic_layout.addRow("Short Description", product_short_description_input)

    pricing_tab = QWidget()
    pricing_layout = QFormLayout(pricing_tab)
    pricing_layout.addRow("Regular Price Minor", product_regular_price_input)
    pricing_layout.addRow("Sale Price Minor", product_sale_price_input)
    pricing_layout.addRow("Global Unique ID", product_global_unique_id_input)
    pricing_layout.addRow("Featured", product_featured_input)
    pricing_layout.addRow("Visibility", product_visibility_input)
    pricing_layout.addRow("Tax Status", product_tax_status_input)
    pricing_layout.addRow("Tax Class", product_tax_class_input)

    inventory_tab = QWidget()
    inventory_form = QFormLayout(inventory_tab)
    inventory_form.addRow("Manage Stock", product_manage_stock_input)
    inventory_form.addRow("Stock Quantity", product_stock_quantity_input)
    inventory_form.addRow("Stock Status", product_stock_status_input)
    inventory_form.addRow("Backorders", product_backorders_input)
    inventory_form.addRow("Sold Individually", product_sold_individually_input)

    shipping_tab = QWidget()
    shipping_form = QFormLayout(shipping_tab)
    shipping_form.addRow("Weight", product_weight_input)
    shipping_form.addRow("Length", product_length_input)
    shipping_form.addRow("Width", product_width_input)
    shipping_form.addRow("Height", product_height_input)
    shipping_form.addRow("Shipping Class", product_shipping_class_input)

    images_tab = QWidget()
    images_layout = QVBoxLayout(images_tab)
    image_button_row = QHBoxLayout()
    image_button_row.addWidget(product_add_image_url_input)
    image_button_row.addWidget(product_add_image_button)
    image_button_row.addWidget(product_upload_image_button)
    image_button_row.addWidget(product_remove_image_button)
    images_layout.addWidget(product_image_table)
    images_layout.addLayout(image_button_row)

    videos_tab = QWidget()
    videos_layout = QVBoxLayout(videos_tab)
    video_button_row = QHBoxLayout()
    video_button_row.addWidget(product_add_video_url_input)
    video_button_row.addWidget(product_add_video_button)
    video_button_row.addWidget(product_upload_video_button)
    video_button_row.addWidget(product_open_video_button)
    video_button_row.addWidget(product_remove_video_button)
    videos_layout.addWidget(product_video_table)
    videos_layout.addLayout(video_button_row)

    variants_tab = QWidget()
    variants_layout = QVBoxLayout(variants_tab)
    variant_button_row = QHBoxLayout()
    variant_button_row.addWidget(product_add_variant_button)
    variant_button_row.addWidget(product_remove_variant_button)
    variants_layout.addWidget(product_variant_table)
    variants_layout.addLayout(variant_button_row)

    seo_tab = QWidget()
    seo_layout = QFormLayout(seo_tab)
    seo_layout.addRow("SEO Title", product_seo_title_input)
    seo_layout.addRow("SEO Description", product_seo_description_input)
    seo_layout.addRow("Reviews Allowed", product_reviews_allowed_input)
    seo_layout.addRow("Purchase Note", product_purchase_note_input)
    seo_layout.addRow("Menu Order", product_menu_order_input)

    advanced_tab = QWidget()
    advanced_layout = QFormLayout(advanced_tab)
    advanced_layout.addRow("Tags", product_tags_input)
    advanced_layout.addRow("Upsell Product IDs", product_upsell_ids_input)
    advanced_layout.addRow("Cross-sell Product IDs", product_cross_sell_ids_input)
    advanced_layout.addRow("Grouped Product IDs", product_grouped_ids_input)
    advanced_layout.addRow("Attributes", product_attributes_input)
    advanced_layout.addRow("Default Attributes", product_default_attributes_input)
    advanced_layout.addRow("Custom Metadata", product_custom_metadata_input)
    advanced_layout.addRow("Metadata", product_metadata_input)

    product_tabs.addTab(basic_tab, "Basic")
    product_tabs.addTab(pricing_tab, "Pricing")
    product_tabs.addTab(inventory_tab, "Inventory")
    product_tabs.addTab(shipping_tab, "Shipping")
    product_tabs.addTab(images_tab, "Images")
    product_tabs.addTab(videos_tab, "Videos")
    product_tabs.addTab(variants_tab, "Variants")
    product_tabs.addTab(seo_tab, "SEO")
    product_tabs.addTab(advanced_tab, "Advanced")
    product_action_row = QHBoxLayout()
    product_new_button = QPushButton("New")
    product_save_button = QPushButton("Save")
    product_archive_button = QPushButton("Move to Trash")
    product_delete_permanent_button = QPushButton("Delete Permanently")
    product_publish_button = QPushButton("Publish")
    product_draft_button = QPushButton("Save as Draft")
    product_restore_button = QPushButton("Restore")
    product_refresh_button = QPushButton("Refresh Products")
    product_clear_button = QPushButton("Clear")
    for button in (
        product_new_button,
        product_save_button,
        product_archive_button,
        product_delete_permanent_button,
        product_publish_button,
        product_draft_button,
        product_restore_button,
        product_refresh_button,
        product_clear_button,
    ):
        product_action_row.addWidget(button)
    product_editor_layout.addWidget(product_tabs)
    product_editor_layout.addLayout(product_action_row)
    product_workspace = QHBoxLayout()
    product_list_layout = QVBoxLayout()
    product_filter_row = QHBoxLayout()
    product_filter_row.addWidget(product_search_input)
    product_filter_row.addWidget(product_status_filter)
    product_trash_button = QPushButton("Trash")
    product_filter_row.addWidget(product_trash_button)
    product_filter_row.addWidget(product_sort_input)
    product_filter_row.addWidget(product_sort_order)
    product_list_layout.addLayout(product_filter_row)
    product_bulk_row = QHBoxLayout()
    product_bulk_row.addWidget(product_bulk_action)
    product_bulk_row.addWidget(product_bulk_button)
    product_bulk_row.addWidget(product_reorder_button)
    product_list_layout.addLayout(product_bulk_row)
    product_list_layout.addWidget(product_table)
    product_workspace.addLayout(product_list_layout, 2)
    product_workspace.addWidget(product_editor, 3)
    product_layout.addLayout(product_workspace)

    customer_page, customer_layout, customer_message = make_page()
    customer_columns = [
        ("full_name", "Name"),
        ("phone", "Phone"),
        ("email", "Email"),
        ("status", "Status"),
    ]
    customer_table = make_table([label for _key, label in customer_columns])
    customer_form = QGroupBox("Create Customer")
    customer_form.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
    customer_form_layout = QFormLayout(customer_form)
    customer_name_input = QLineEdit()
    customer_phone_input = QLineEdit()
    customer_email_input = QLineEdit()
    customer_create_button = QPushButton("Create Customer")
    customer_refresh_button = QPushButton("Refresh Customers")
    customer_form_layout.addRow("Name", customer_name_input)
    customer_form_layout.addRow("Phone", customer_phone_input)
    customer_form_layout.addRow("Email", customer_email_input)
    customer_form_layout.addRow(customer_create_button)
    customer_layout.addWidget(customer_table)
    customer_layout.addWidget(customer_form)
    customer_layout.addWidget(customer_refresh_button)

    inventory_page, inventory_layout, inventory_message = make_page()
    inventory_columns = [
        ("warehouse_id", "Warehouse"),
        ("product_id", "Product"),
        ("variant_id", "Variant"),
        ("quantity_on_hand", "Qty"),
    ]
    inventory_table = make_table([label for _key, label in inventory_columns])
    inventory_refresh_button = QPushButton("Refresh Stock")
    inventory_layout.addWidget(inventory_table)
    inventory_layout.addWidget(inventory_refresh_button)

    orders_page, orders_layout, orders_message = make_page()
    order_columns = [
        ("order_number", "Order"),
        ("status", "Status"),
        ("customer_id", "Customer"),
        ("total_minor", "Total"),
        ("payment_status", "Payment"),
    ]
    orders_table = make_table([label for _key, label in order_columns])
    orders_refresh_button = QPushButton("Refresh Orders")
    orders_layout.addWidget(orders_table)
    orders_layout.addWidget(orders_refresh_button)

    woocommerce_page, woocommerce_layout, woocommerce_message = make_page()
    woocommerce_config = QGroupBox("WooCommerce Connection")
    woocommerce_config.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
    woocommerce_config_layout = QFormLayout(woocommerce_config)
    woo_site_url_input = QLineEdit()
    woo_site_url_input.setPlaceholderText("https://choiceoye.com")
    woo_consumer_key_input = QLineEdit()
    woo_consumer_key_input.setPlaceholderText("Consumer key")
    woo_consumer_secret_input = QLineEdit()
    woo_consumer_secret_input.setPlaceholderText("Consumer secret")
    woo_consumer_secret_input.setEchoMode(QLineEdit.EchoMode.Password)
    woo_webhook_secret_input = QLineEdit()
    woo_webhook_secret_input.setPlaceholderText("WooCommerce webhook secret")
    woo_webhook_secret_input.setEchoMode(QLineEdit.EchoMode.Password)
    woo_wp_username_input = QLineEdit()
    woo_wp_username_input.setPlaceholderText("WordPress username for media uploads")
    woo_wp_app_password_input = QLineEdit()
    woo_wp_app_password_input.setPlaceholderText("WordPress application password")
    woo_wp_app_password_input.setEchoMode(QLineEdit.EchoMode.Password)
    woo_save_button = QPushButton("Save Config")
    woo_test_button = QPushButton("Test Connection")
    woo_sync_button = QPushButton("Run Sync")
    woo_refresh_button = QPushButton("Refresh WooCommerce")
    woo_button_row = QHBoxLayout()
    woo_button_row.addWidget(woo_save_button)
    woo_button_row.addWidget(woo_test_button)
    woo_button_row.addWidget(woo_sync_button)
    woo_button_row.addWidget(woo_refresh_button)
    woocommerce_config_layout.addRow("Site URL", woo_site_url_input)
    woocommerce_config_layout.addRow("Consumer Key", woo_consumer_key_input)
    woocommerce_config_layout.addRow("Consumer Secret", woo_consumer_secret_input)
    woocommerce_config_layout.addRow("Webhook Secret", woo_webhook_secret_input)
    woocommerce_config_layout.addRow("WP Media Username", woo_wp_username_input)
    woocommerce_config_layout.addRow("WP App Password", woo_wp_app_password_input)
    woocommerce_config_layout.addRow(woo_button_row)

    woocommerce_run_columns = [
        ("started_at", "Started"),
        ("status", "Status"),
        ("finished_at", "Finished"),
        ("pulled_products", "Products In"),
        ("pulled_customers", "Customers In"),
        ("pulled_orders", "Orders In"),
        ("pushed_records", "Pushed Out"),
        ("pushed_media_records", "Media Out"),
        ("pushed_video_records", "Videos Out"),
        ("deferred_media_records", "Media Deferred"),
        ("deferred_video_records", "Videos Deferred"),
        ("archived_missing_products", "Archived Locally"),
        ("pending_media_pushes", "Media Pending"),
        ("pending_video_pushes", "Videos Pending"),
        ("failed_media_pushes", "Media Failed"),
        ("failed_video_pushes", "Videos Failed"),
        ("failed_records", "Push Failed"),
        ("error", "Error"),
    ]
    woocommerce_conflict_columns = [
        ("resource_type", "Resource"),
        ("conflict_type", "Conflict"),
        ("status", "Status"),
        ("resolution", "Resolution"),
    ]
    woocommerce_runs_table = make_table([label for _key, label in woocommerce_run_columns])
    woocommerce_conflicts_table = make_table(
        [label for _key, label in woocommerce_conflict_columns]
    )
    woocommerce_summary = QTextEdit()
    woocommerce_summary.setReadOnly(True)
    woocommerce_layout.addWidget(woocommerce_config)
    woocommerce_layout.addWidget(QLabel("Recent Sync Runs"))
    woocommerce_layout.addWidget(woocommerce_runs_table)
    woocommerce_layout.addWidget(QLabel("Open Conflicts"))
    woocommerce_layout.addWidget(woocommerce_conflicts_table)
    woocommerce_layout.addWidget(woocommerce_summary)

    marketplace_page, marketplace_layout, marketplace_message = make_page()
    marketplace_vendor_columns = [
        ("id", "Vendor ID"),
        ("name", "Name"),
        ("slug", "Slug"),
        ("status", "Stored Status"),
        ("access_status", "Access Status"),
        ("default_commission_bps", "Commission"),
    ]
    marketplace_vendor_table = make_table([label for _key, label in marketplace_vendor_columns])
    marketplace_vendor_form = QGroupBox("Create Vendor")
    marketplace_vendor_form_layout = QFormLayout(marketplace_vendor_form)
    marketplace_vendor_name_input = QLineEdit()
    marketplace_vendor_slug_input = QLineEdit()
    marketplace_vendor_legal_input = QLineEdit()
    marketplace_vendor_contact_input = QLineEdit()
    marketplace_vendor_email_input = QLineEdit()
    marketplace_vendor_phone_input = QLineEdit()
    marketplace_vendor_status_input = QComboBox()
    marketplace_vendor_status_input.addItems(list(VENDOR_STATUSES))
    marketplace_vendor_status_input.setCurrentText("active")
    marketplace_vendor_username_input = QLineEdit()
    marketplace_vendor_username_input.setPlaceholderText("Required for a login account")
    marketplace_vendor_password_input = QLineEdit()
    marketplace_vendor_password_input.setEchoMode(QLineEdit.EchoMode.Password)
    marketplace_vendor_password_input.setPlaceholderText("Temporary password (optional)")
    marketplace_vendor_onboarding_input = QComboBox()
    for onboarding_label, onboarding_value in VENDOR_ONBOARDING_OPTIONS:
        marketplace_vendor_onboarding_input.addItem(onboarding_label, onboarding_value)
    marketplace_vendor_commission_input = QLineEdit()
    marketplace_vendor_commission_input.setPlaceholderText("0")
    marketplace_vendor_commission_input.setText("0")
    marketplace_vendor_create_button = QPushButton("Create Vendor")
    marketplace_vendor_onboarding_result = QTextEdit()
    marketplace_vendor_onboarding_result.setReadOnly(True)
    marketplace_vendor_onboarding_result.setPlaceholderText(
        "Linked-user and onboarding results appear here without credentials."
    )
    marketplace_refresh_button = QPushButton("Refresh Marketplace")
    marketplace_vendor_form_layout.addRow("Name", marketplace_vendor_name_input)
    marketplace_vendor_form_layout.addRow("Slug", marketplace_vendor_slug_input)
    marketplace_vendor_form_layout.addRow("Legal Name", marketplace_vendor_legal_input)
    marketplace_vendor_form_layout.addRow("Contact Name", marketplace_vendor_contact_input)
    marketplace_vendor_form_layout.addRow("Email", marketplace_vendor_email_input)
    marketplace_vendor_form_layout.addRow("Phone", marketplace_vendor_phone_input)
    marketplace_vendor_form_layout.addRow("Status", marketplace_vendor_status_input)
    marketplace_vendor_form_layout.addRow("Login ID", marketplace_vendor_username_input)
    marketplace_vendor_form_layout.addRow("Temporary password", marketplace_vendor_password_input)
    marketplace_vendor_form_layout.addRow("Onboarding", marketplace_vendor_onboarding_input)
    marketplace_vendor_form_layout.addRow("Commission BPS", marketplace_vendor_commission_input)
    marketplace_vendor_form_layout.addRow(marketplace_vendor_create_button)
    marketplace_vendor_form_layout.addRow("Onboarding result", marketplace_vendor_onboarding_result)
    marketplace_current_vendor_text = QTextEdit()
    marketplace_current_vendor_text.setReadOnly(True)
    marketplace_current_products_columns = [
        ("id", "Assignment"),
        ("product_id", "Product"),
        ("ownership_type", "Ownership"),
        ("approval_status", "Status"),
        ("settlement_id", "Settlement"),
    ]
    marketplace_current_orders_columns = [
        ("id", "Vendor Item"),
        ("order_number", "Order"),
        ("name", "Item"),
        ("line_total_minor", "Line Total"),
        ("payable_minor", "Payable"),
        ("status", "Vendor Status"),
        ("order_status", "Order Status"),
        ("payment_status", "Payment Status"),
    ]
    marketplace_current_settlements_columns = [
        ("settlement_number", "Settlement"),
        ("status", "Status"),
        ("payable_minor", "Payable"),
        ("paid_minor", "Paid"),
    ]
    marketplace_current_products_table = make_table(
        [label for _key, label in marketplace_current_products_columns]
    )
    marketplace_vendor_product_create_button = QPushButton("Add My Product")
    marketplace_vendor_product_price_button = QPushButton("Update Selected Product Price")
    marketplace_vendor_stock_adjust_button = QPushButton("Adjust Selected Stock")
    marketplace_vendor_order_status_action = QComboBox()
    marketplace_vendor_order_status_action.addItems(
        ["accepted", "packing", "dispatched", "delivered", "rejected"]
    )
    marketplace_vendor_order_status_button = QPushButton("Update Selected Order Item")
    marketplace_vendor_self_actions = QWidget()
    marketplace_vendor_self_actions_layout = QHBoxLayout(marketplace_vendor_self_actions)
    marketplace_vendor_self_actions_layout.setContentsMargins(0, 0, 0, 0)
    marketplace_vendor_self_actions_layout.addWidget(marketplace_vendor_product_create_button)
    marketplace_vendor_self_actions_layout.addWidget(marketplace_vendor_product_price_button)
    marketplace_vendor_self_actions_layout.addWidget(marketplace_vendor_stock_adjust_button)
    marketplace_vendor_self_actions_layout.addWidget(marketplace_vendor_order_status_action)
    marketplace_vendor_self_actions_layout.addWidget(marketplace_vendor_order_status_button)
    marketplace_current_orders_table = make_table(
        [label for _key, label in marketplace_current_orders_columns]
    )

    marketplace_orders_offset = 0
    marketplace_orders_limit = 10

    marketplace_orders_page_widget = QWidget()
    marketplace_orders_page_layout = QVBoxLayout(marketplace_orders_page_widget)
    marketplace_orders_page_layout.setContentsMargins(0, 0, 0, 0)
    marketplace_orders_page_layout.addWidget(marketplace_current_orders_table)

    marketplace_orders_buttons_layout = QHBoxLayout()
    marketplace_orders_prev_btn = QPushButton("Previous Page")
    marketplace_orders_next_btn = QPushButton("Next Page")
    marketplace_orders_buttons_layout.addWidget(marketplace_orders_prev_btn)
    marketplace_orders_buttons_layout.addWidget(marketplace_orders_next_btn)
    marketplace_orders_page_layout.addLayout(marketplace_orders_buttons_layout)

    marketplace_current_settlements_table = make_table(
        [label for _key, label in marketplace_current_settlements_columns]
    )
    marketplace_vendor_status_action = QComboBox()
    marketplace_vendor_status_action.addItems(list(VENDOR_STATUSES))
    marketplace_vendor_status_button = QPushButton("Apply Selected Vendor Status")
    marketplace_vendor_approve_button = QPushButton("Approve")
    marketplace_vendor_pause_button = QPushButton("Pause")
    marketplace_vendor_reactivate_button = QPushButton("Reactivate")
    marketplace_vendor_stop_button = QPushButton("Stop")
    marketplace_vendor_edit_button = QPushButton("Edit Vendor")
    marketplace_vendor_reset_password_button = QPushButton("Reset User Password")
    marketplace_vendor_lifecycle_row = QHBoxLayout()
    for lifecycle_button in (
        marketplace_vendor_approve_button,
        marketplace_vendor_pause_button,
        marketplace_vendor_reactivate_button,
        marketplace_vendor_stop_button,
        marketplace_vendor_edit_button,
        marketplace_vendor_reset_password_button,
    ):
        marketplace_vendor_lifecycle_row.addWidget(lifecycle_button)
    marketplace_vendor_detail_tabs = QTabWidget()
    marketplace_vendor_overview_text = QTextEdit()
    marketplace_vendor_overview_text.setReadOnly(True)
    marketplace_vendor_stock_table = make_table(
        ["Product", "Warehouse", "Ownership", "On Hand", "Reserved", "Available"]
    )
    marketplace_vendor_movement_table = make_table(
        ["When", "Type", "Product", "Quantity", "Before", "After", "Reason"]
    )
    marketplace_vendor_financial_table = make_table(
        ["When", "Entry", "Source", "Debit", "Credit", "Balance"]
    )
    marketplace_vendor_reports_text = QTextEdit()
    marketplace_vendor_reports_text.setReadOnly(True)
    marketplace_vendor_users_table = make_table(
        ["User ID", "Username", "Role", "Account Status", "Primary"]
    )
    marketplace_vendor_audit_table = make_table(["When", "Action", "Entity", "Actor", "Details"])
    for widget, label in zip(
        (
            marketplace_vendor_overview_text,
            marketplace_vendor_stock_table,
            marketplace_vendor_movement_table,
            marketplace_current_products_table,
            marketplace_orders_page_widget,
            marketplace_vendor_financial_table,
            marketplace_current_settlements_table,
            marketplace_vendor_reports_text,
            marketplace_vendor_users_table,
            marketplace_vendor_audit_table,
        ),
        VENDOR_WORKSPACE_TABS,
        strict=True,
    ):
        marketplace_vendor_detail_tabs.addTab(widget, label)
    marketplace_filter_row = QHBoxLayout()
    marketplace_date_from_input = QLineEdit()
    marketplace_date_from_input.setPlaceholderText("From date/time (ISO 8601)")
    marketplace_date_to_input = QLineEdit()
    marketplace_date_to_input.setPlaceholderText("To date/time (ISO 8601)")
    marketplace_order_status_filter = QLineEdit()
    marketplace_order_status_filter.setPlaceholderText("Order status")
    marketplace_payment_status_filter = QLineEdit()
    marketplace_payment_status_filter.setPlaceholderText("Payment status")
    marketplace_settlement_status_filter = QLineEdit()
    marketplace_settlement_status_filter.setPlaceholderText("Settlement status")
    marketplace_apply_filters_button = QPushButton("Apply Vendor Filters")
    for widget in (
        marketplace_date_from_input,
        marketplace_date_to_input,
        marketplace_order_status_filter,
        marketplace_payment_status_filter,
        marketplace_settlement_status_filter,
        marketplace_apply_filters_button,
    ):
        marketplace_filter_row.addWidget(widget)
    marketplace_splitter = QSplitter(Qt.Orientation.Vertical)
    marketplace_layout.addWidget(marketplace_splitter)

    # Top part: Vendor Table
    marketplace_splitter.addWidget(marketplace_vendor_table)

    # Bottom part: Rest of the controls
    marketplace_bottom_widget = QWidget()
    marketplace_bottom_layout = QVBoxLayout(marketplace_bottom_widget)
    marketplace_bottom_layout.setContentsMargins(0, 0, 0, 0)

    # Fix the form squishing
    marketplace_vendor_form.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

    marketplace_bottom_layout.addWidget(marketplace_vendor_form)
    marketplace_bottom_layout.addWidget(marketplace_vendor_status_action)
    marketplace_bottom_layout.addWidget(marketplace_vendor_status_button)
    marketplace_bottom_layout.addLayout(marketplace_vendor_lifecycle_row)
    marketplace_bottom_layout.addWidget(marketplace_vendor_self_actions)
    marketplace_bottom_layout.addLayout(marketplace_filter_row)
    marketplace_bottom_layout.addWidget(marketplace_vendor_detail_tabs)
    marketplace_bottom_layout.addWidget(marketplace_refresh_button)
    marketplace_bottom_layout.addWidget(QLabel("Current Vendor"))
    marketplace_bottom_layout.addWidget(marketplace_current_vendor_text)

    marketplace_splitter.addWidget(marketplace_bottom_widget)

    accounting_page, accounting_layout, accounting_message = make_page()
    accounting_account_columns = [
        ("code", "Code"),
        ("name", "Name"),
        ("account_type", "Type"),
        ("is_active", "Active"),
    ]
    accounting_period_columns = [
        ("name", "Period"),
        ("status", "Status"),
        ("starts_at", "Starts"),
        ("ends_at", "Ends"),
    ]
    accounting_journal_columns = [
        ("entry_number", "Entry"),
        ("status", "Status"),
        ("source_type", "Source"),
        ("posted_at", "Posted"),
    ]
    accounting_vendor_ledger_columns = [
        ("vendor_id", "Vendor"),
        ("entry_type", "Type"),
        ("amount_minor", "Amount"),
        ("balance_minor", "Balance"),
    ]
    accounting_cash_columns = [
        ("code", "Code"),
        ("name", "Name"),
        ("currency", "Currency"),
        ("opening_balance_minor", "Opening"),
    ]
    accounting_bank_columns = [
        ("code", "Code"),
        ("bank_name", "Bank"),
        ("account_name", "Account"),
        ("currency", "Currency"),
    ]
    accounting_expense_columns = [
        ("expense_number", "Expense"),
        ("status", "Status"),
        ("amount_minor", "Amount"),
        ("vendor_id", "Vendor"),
    ]
    accounting_account_table = make_table([label for _key, label in accounting_account_columns])
    accounting_period_table = make_table([label for _key, label in accounting_period_columns])
    accounting_journal_table = make_table([label for _key, label in accounting_journal_columns])
    accounting_vendor_ledger_table = make_table(
        [label for _key, label in accounting_vendor_ledger_columns]
    )
    accounting_cash_table = make_table([label for _key, label in accounting_cash_columns])
    accounting_bank_table = make_table([label for _key, label in accounting_bank_columns])
    accounting_expense_table = make_table([label for _key, label in accounting_expense_columns])
    ledger_account_columns = [
        ("code", "Code"),
        ("name", "Account"),
        ("account_type", "Type"),
        ("currency", "Currency"),
    ]
    ledger_journal_columns = [
        ("entry_number", "Entry"),
        ("posted_at", "Posted"),
        ("source_type", "Source"),
        ("status", "Status"),
    ]
    ledger_trial_columns = [
        ("account_code", "Code"),
        ("account_name", "Account"),
        ("debit_minor", "Debit"),
        ("credit_minor", "Credit"),
        ("balance_minor", "Balance"),
    ]
    ledger_account_table = make_table([label for _key, label in ledger_account_columns])
    ledger_journal_table = make_table([label for _key, label in ledger_journal_columns])
    ledger_trial_table = make_table([label for _key, label in ledger_trial_columns])
    ledger_control_summary = QTextEdit()
    ledger_control_summary.setReadOnly(True)
    ledger_profit_loss_text = QTextEdit()
    ledger_profit_loss_text.setReadOnly(True)
    ledger_balance_sheet_text = QTextEdit()
    ledger_balance_sheet_text.setReadOnly(True)
    ledger_cash_flow_text = QTextEdit()
    ledger_cash_flow_text.setReadOnly(True)
    ledger_vendor_payables_table = make_table(
        [
            "Vendor",
            "Name",
            "Status",
            "Orders",
            "Gross Sales",
            "Current",
            "31-60",
            "61-90",
            "90+",
            "Outstanding",
        ]
    )
    ledger_inventory_table = make_table(
        ["Vendor", "Product", "Warehouse", "Ownership", "On Hand", "Reserved", "Available"]
    )
    ledger_reconciliation_table = make_table(
        ["Severity", "Issue", "Vendor", "Source", "Expected", "Actual", "Detail"]
    )
    ledger_control_tabs = QTabWidget()
    for widget, label in zip(
        (
            ledger_control_summary,
            ledger_account_table,
            ledger_journal_table,
            ledger_trial_table,
            ledger_profit_loss_text,
            ledger_balance_sheet_text,
            ledger_cash_flow_text,
            ledger_vendor_payables_table,
            ledger_inventory_table,
            ledger_reconciliation_table,
        ),
        LEDGER_WORKSPACE_TABS,
        strict=True,
    ):
        ledger_control_tabs.addTab(widget, label)
    ledger_filter_row = QHBoxLayout()
    ledger_date_from_input = QLineEdit()
    ledger_date_from_input.setPlaceholderText("From date/time (ISO 8601)")
    ledger_date_to_input = QLineEdit()
    ledger_date_to_input.setPlaceholderText("To date/time (ISO 8601)")
    ledger_vendor_filter_input = QLineEdit()
    ledger_vendor_filter_input.setPlaceholderText("Vendor ID")
    ledger_account_filter_input = QLineEdit()
    ledger_account_filter_input.setPlaceholderText("Account ID")
    ledger_source_filter_input = QLineEdit()
    ledger_source_filter_input.setPlaceholderText("Journal source")
    ledger_status_filter_input = QLineEdit()
    ledger_status_filter_input.setPlaceholderText("Journal status")
    ledger_apply_filters_button = QPushButton("Apply Ledger Filters")
    ledger_export_button = QPushButton("Export Journals CSV")
    for widget in (
        ledger_date_from_input,
        ledger_date_to_input,
        ledger_vendor_filter_input,
        ledger_account_filter_input,
        ledger_source_filter_input,
        ledger_status_filter_input,
        ledger_apply_filters_button,
        ledger_export_button,
    ):
        ledger_filter_row.addWidget(widget)
    accounting_refresh_button = QPushButton("Refresh Accounting")
    accounting_account_form = QGroupBox("Create Account")
    accounting_account_form.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
    accounting_account_form_layout = QFormLayout(accounting_account_form)
    accounting_account_code_input = QLineEdit()
    accounting_account_name_input = QLineEdit()
    accounting_account_type_input = QLineEdit()
    accounting_account_parent_input = QLineEdit()
    accounting_account_active_input = QLineEdit()
    accounting_account_active_input.setPlaceholderText("true")
    accounting_account_active_input.setText("true")
    accounting_account_create_button = QPushButton("Create Account")
    accounting_account_form_layout.addRow("Code", accounting_account_code_input)
    accounting_account_form_layout.addRow("Name", accounting_account_name_input)
    accounting_account_form_layout.addRow("Type", accounting_account_type_input)
    accounting_account_form_layout.addRow("Parent ID", accounting_account_parent_input)
    accounting_account_form_layout.addRow("Active", accounting_account_active_input)
    accounting_account_form_layout.addRow(accounting_account_create_button)
    accounting_cash_form = QGroupBox("Create Cash Book")
    accounting_cash_form.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
    accounting_cash_form_layout = QFormLayout(accounting_cash_form)
    accounting_cash_code_input = QLineEdit()
    accounting_cash_name_input = QLineEdit()
    accounting_cash_currency_input = QLineEdit()
    accounting_cash_currency_input.setPlaceholderText("PKR")
    accounting_cash_opening_input = QLineEdit()
    accounting_cash_opening_input.setPlaceholderText("0")
    accounting_cash_opening_input.setText("0")
    accounting_cash_create_button = QPushButton("Create Cash Book")
    accounting_cash_form_layout.addRow("Code", accounting_cash_code_input)
    accounting_cash_form_layout.addRow("Name", accounting_cash_name_input)
    accounting_cash_form_layout.addRow("Currency", accounting_cash_currency_input)
    accounting_cash_form_layout.addRow("Opening Balance", accounting_cash_opening_input)
    accounting_cash_form_layout.addRow(accounting_cash_create_button)
    accounting_bank_form = QGroupBox("Create Bank Account")
    accounting_bank_form.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
    accounting_bank_form_layout = QFormLayout(accounting_bank_form)
    accounting_bank_code_input = QLineEdit()
    accounting_bank_name_input = QLineEdit()
    accounting_bank_account_name_input = QLineEdit()
    accounting_bank_account_number_input = QLineEdit()
    accounting_bank_iban_input = QLineEdit()
    accounting_bank_currency_input = QLineEdit()
    accounting_bank_currency_input.setPlaceholderText("PKR")
    accounting_bank_currency_input.setText("PKR")
    accounting_bank_create_button = QPushButton("Create Bank Account")
    accounting_bank_form_layout.addRow("Code", accounting_bank_code_input)
    accounting_bank_form_layout.addRow("Bank Name", accounting_bank_name_input)
    accounting_bank_form_layout.addRow("Account Name", accounting_bank_account_name_input)
    accounting_bank_form_layout.addRow("Account Number", accounting_bank_account_number_input)
    accounting_bank_form_layout.addRow("IBAN", accounting_bank_iban_input)
    accounting_bank_form_layout.addRow("Currency", accounting_bank_currency_input)
    accounting_bank_form_layout.addRow(accounting_bank_create_button)
    accounting_summary = QTextEdit()
    accounting_summary.setReadOnly(True)
    accounting_layout.addWidget(accounting_account_table)
    accounting_layout.addWidget(accounting_account_form)
    accounting_layout.addWidget(accounting_cash_table)
    accounting_layout.addWidget(accounting_cash_form)
    accounting_layout.addWidget(accounting_bank_table)
    accounting_layout.addWidget(accounting_bank_form)
    accounting_layout.addWidget(QLabel("Accounting Periods"))
    accounting_layout.addWidget(accounting_period_table)
    accounting_layout.addWidget(QLabel("Journal Entries"))
    accounting_layout.addWidget(accounting_journal_table)
    accounting_layout.addWidget(QLabel("Vendor Ledger"))
    accounting_layout.addWidget(accounting_vendor_ledger_table)
    accounting_layout.addWidget(QLabel("Expenses"))
    accounting_layout.addWidget(accounting_expense_table)
    accounting_layout.addWidget(accounting_summary)
    accounting_layout.addWidget(QLabel("Authoritative Ledger Control Center"))
    accounting_layout.addLayout(ledger_filter_row)
    accounting_layout.addWidget(ledger_control_tabs)
    accounting_layout.addWidget(accounting_refresh_button)

    settings_page, settings_layout, settings_message = make_page()
    modules_text = QTextEdit()
    modules_text.setReadOnly(True)
    settings_refresh_button = QPushButton("Refresh API Status")
    settings_layout.addWidget(modules_text)
    settings_layout.addWidget(settings_refresh_button)

    admin_page, admin_layout, admin_message = make_page()
    company_columns = [
        ("id", "Company ID"),
        ("name", "Name"),
        ("legal_name", "Legal Name"),
        ("status", "Status"),
    ]
    user_columns = [
        ("id", "User ID"),
        ("username", "Username"),
        ("email", "Email"),
        ("full_name", "Full Name"),
        ("account_status", "Account Status"),
        ("role_names", "Roles"),
        ("must_change_password", "Password Change Required"),
    ]
    role_columns = [
        ("id", "Role ID"),
        ("name", "Name"),
        ("description", "Description"),
    ]
    company_table = make_table([label for _key, label in company_columns])
    user_table = make_table([label for _key, label in user_columns])
    role_table = make_table([label for _key, label in role_columns])
    admin_summary = QTextEdit()
    admin_summary.setReadOnly(True)

    admin_refresh_button = QPushButton("Refresh Admin")

    company_form = QGroupBox("Update Company")
    company_form.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
    company_form_layout = QFormLayout(company_form)
    company_id_input = QLineEdit()
    company_id_input.setPlaceholderText("Company ID")
    company_name_input = QLineEdit()
    company_name_input.setPlaceholderText("Company name")
    company_legal_name_input = QLineEdit()
    company_legal_name_input.setPlaceholderText("Legal name")
    company_status_input = QLineEdit()
    company_status_input.setPlaceholderText("active or suspended")
    company_update_button = QPushButton("Update Company")
    company_form_layout.addRow("Company ID", company_id_input)
    company_form_layout.addRow("Name", company_name_input)
    company_form_layout.addRow("Legal Name", company_legal_name_input)
    company_form_layout.addRow("Status", company_status_input)
    company_form_layout.addRow(company_update_button)

    user_form = QGroupBox("Create / Reset User")
    user_form.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
    user_form_layout = QFormLayout(user_form)
    admin_username_input = QLineEdit()
    admin_username_input.setPlaceholderText("Username")
    admin_password_input = QLineEdit()
    admin_password_input.setPlaceholderText("Password")
    admin_password_input.setEchoMode(QLineEdit.EchoMode.Password)
    admin_user_email_input = QLineEdit()
    admin_user_email_input.setPlaceholderText("Email")
    admin_user_full_name_input = QLineEdit()
    admin_user_full_name_input.setPlaceholderText("Full name")
    admin_user_roles_input = QListWidget()
    admin_user_roles_input.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)
    admin_user_roles_input.setMaximumHeight(120)
    admin_user_id_input = QLineEdit()
    admin_user_status_input = QComboBox()
    admin_user_status_input.addItems(list(ACCOUNT_STATUSES))
    admin_user_must_change_input = QCheckBox("Require password change at next login")
    admin_user_id_input.setPlaceholderText("User ID for reset")
    admin_create_user_button = QPushButton("Create User")
    admin_apply_user_status_button = QPushButton("Apply Account Status and Roles")
    admin_reset_password_button = QPushButton("Reset Password")
    user_form_layout.addRow("Username", admin_username_input)
    user_form_layout.addRow("Password", admin_password_input)
    user_form_layout.addRow("Email", admin_user_email_input)
    user_form_layout.addRow("Full Name", admin_user_full_name_input)
    user_form_layout.addRow("Roles", admin_user_roles_input)
    user_form_layout.addRow("Account Status", admin_user_status_input)
    user_form_layout.addRow(admin_user_must_change_input)
    user_form_layout.addRow("Reset User ID", admin_user_id_input)
    user_form_layout.addRow(admin_create_user_button)
    user_form_layout.addRow(admin_apply_user_status_button)
    user_form_layout.addRow(admin_reset_password_button)

    role_form = QGroupBox("Create Role")
    role_form.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
    role_form_layout = QFormLayout(role_form)
    admin_role_name_input = QLineEdit()
    admin_role_name_input.setPlaceholderText("Role name")
    admin_role_description_input = QLineEdit()
    admin_role_description_input.setPlaceholderText("Description")
    admin_role_permissions_input = QLineEdit()
    admin_role_permissions_input.setPlaceholderText("Comma-separated permission keys")
    admin_create_role_button = QPushButton("Create Role")
    role_form_layout.addRow("Name", admin_role_name_input)
    role_form_layout.addRow("Description", admin_role_description_input)
    role_form_layout.addRow("Permissions", admin_role_permissions_input)
    role_form_layout.addRow(admin_create_role_button)

    license_form = QGroupBox("License")
    license_form.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
    license_form_layout = QFormLayout(license_form)
    admin_license_key_input = QLineEdit()
    admin_license_key_input.setPlaceholderText("License key")
    admin_license_plan_input = QLineEdit()
    admin_license_plan_input.setPlaceholderText("standard")
    admin_activate_license_button = QPushButton("Activate License")
    admin_validate_license_button = QPushButton("Validate License")
    admin_revoke_license_button = QPushButton("Revoke License")
    license_form_layout.addRow("Key", admin_license_key_input)
    license_form_layout.addRow("Plan", admin_license_plan_input)
    license_form_layout.addRow(admin_activate_license_button)
    license_form_layout.addRow(admin_validate_license_button)
    license_form_layout.addRow(admin_revoke_license_button)

    admin_layout.addWidget(company_table)
    admin_layout.addWidget(company_form)
    admin_layout.addWidget(user_table)
    admin_layout.addWidget(user_form)
    admin_layout.addWidget(role_table)
    admin_layout.addWidget(role_form)
    admin_layout.addWidget(license_form)
    admin_layout.addWidget(admin_summary)
    admin_layout.addWidget(admin_refresh_button)

    pages = [
        dashboard_page,
        product_page,
        customer_page,
        inventory_page,
        orders_page,
        woocommerce_page,
        marketplace_page,
        accounting_page,
        settings_page,
        admin_page,
    ]
    page_messages[:] = [
        ("Dashboard", dashboard_message),
        ("Products", product_message),
        ("Customers", customer_message),
        ("Inventory", inventory_message),
        ("Orders", orders_message),
        ("WooCommerce", woocommerce_message),
        ("Marketplace", marketplace_message),
        ("Accounting", accounting_message),
        ("Settings", settings_message),
        ("Admin", admin_message),
    ]
    for page in pages:
        stack.addWidget(page)

    def guarded(message: QLabel, action: Callable[[], None]) -> None:
        try:
            action()
        except ApiResponseError as exc:
            detail = format_api_error(exc, client.base_url)
            set_page_message(message, detail, ok=False)
            set_status(detail, ok=False)
            if state.get("token") and not client.access_token:
                clear_ui_session("Your session is no longer available. Sign in again.")
        except Exception as exc:
            set_page_message(message, f"API error: {exc}", ok=False)
            set_status(f"API error: {exc}", ok=False)

    def start_session_api_task(
        message: QLabel,
        operation: Callable[[], object],
        *,
        on_result: Callable[[object], None],
        controls: tuple[QWidget, ...] = (),
    ) -> None:
        epoch = int(state.get("auth_epoch") or 0)
        for control in controls:
            control.setEnabled(False)

        def session_is_current() -> bool:
            return int(state.get("auth_epoch") or 0) == epoch

        def result(value: object) -> None:
            if session_is_current():
                on_result(value)

        def error(exc: BaseException) -> None:
            if not session_is_current():
                return
            if isinstance(exc, ApiResponseError):
                detail = format_api_error(exc, client.base_url)
            else:
                detail = "The requested operation could not be completed."
            set_page_message(message, detail, ok=False)
            set_status(detail, ok=False)
            if state.get("token") and not client.access_token:
                clear_ui_session("Your session is no longer available. Sign in again.")

        def finished() -> None:
            if session_is_current():
                for control in controls:
                    control.setEnabled(True)

        task_runner.start(
            operation,
            on_result=result,
            on_error=error,
            on_finished=finished,
        )

    def refresh_dashboard() -> None:
        token = current_token()
        if not token:
            dashboard_message.setText("Login required.")
            return

        def action() -> None:
            roles = [str(value) for value in state.get("roles") or []]
            permissions = [str(value) for value in state.get("permissions") or []]
            if should_load_vendor_self(roles, permissions):
                summary = client.get_current_vendor_dashboard(token)
                revenue = summary.get("sales_minor_total", 0)
                sales = summary.get("order_count", 0)
            else:
                summary = client.get_dashboard_summary(token)
                revenue = summary.get("revenue_minor", 0)
                sales = summary.get("sales_count", 0)
            dashboard_counts.setText(
                " | ".join(
                    [
                        f"Products: {summary.get('product_count', 0)}",
                        f"Customers: {summary.get('customer_count', 0)}",
                        f"Revenue: {revenue}",
                        f"Sales: {sales}",
                        f"Pending: {summary.get('pending_orders', 0)}",
                        f"Low stock: {summary.get('low_stock_count', 0)}",
                    ]
                )
            )
            dashboard_message.setText("Dashboard loaded.")
            set_status("Dashboard loaded.", ok=True)

        guarded(dashboard_message, action)

    def refresh_products() -> None:
        token = current_token()
        if not token:
            set_page_message(product_message, "Login required.", ok=False)
            set_status("Login required for Products.", ok=False)
            return

        def action() -> None:
            load_product_reference_options(token)
            products = client.list_products(
                token, include_archived=product_status_filter.currentData() == "archived"
            )
            display_products = []
            for product in products:
                row = dict(product)
                row["status"] = {"active": "Published", "draft": "Draft", "archived": "Trash"}.get(
                    str(product.get("status") or ""), product.get("status")
                )
                display_products.append(row)
            populate_table(product_table, display_products, product_columns)
            apply_product_filter()
            product_message.setText(f"{len(products)} products loaded.")
            set_status("Products loaded.", ok=True)

        guarded(product_message, action)

    def combo_value(combo: QComboBox) -> str | None:
        data = combo.currentData()
        return str(data) if data else None

    def set_combo_value(combo: QComboBox, value: object) -> None:
        target = str(value or "")
        was_blocked = combo.blockSignals(True)
        try:
            for index in range(combo.count()):
                if str(combo.itemData(index) or "") == target:
                    combo.setCurrentIndex(index)
                    return
            combo.setCurrentIndex(0)
        finally:
            combo.blockSignals(was_blocked)

    def load_product_reference_options(token: str) -> None:
        current_category = combo_value(product_category_combo)
        current_brand = combo_value(product_brand_combo)
        current_vendor = combo_value(product_vendor_combo)
        category_blocked = product_category_combo.blockSignals(True)
        brand_blocked = product_brand_combo.blockSignals(True)
        vendor_blocked = product_vendor_combo.blockSignals(True)
        try:
            product_category_combo.clear()
            product_brand_combo.clear()
            product_vendor_combo.clear()
            product_category_combo.addItem("", None)
            product_category_combo.addItem("Add Category...", CREATE_CATEGORY_ACTION)
            product_brand_combo.addItem("", None)
            product_brand_combo.addItem("Add Brand...", CREATE_BRAND_ACTION)
            product_vendor_combo.addItem("", None)
            for category in client.list_categories(token):
                product_category_combo.addItem(str(category.get("name") or ""), category.get("id"))
            for brand in client.list_brands(token):
                product_brand_combo.addItem(str(brand.get("name") or ""), brand.get("id"))
            for vendor in client.list_vendors(token):
                product_vendor_combo.addItem(str(vendor.get("name") or ""), vendor.get("id"))
            set_combo_value(product_category_combo, current_category)
            set_combo_value(product_brand_combo, current_brand)
            set_combo_value(product_vendor_combo, current_vendor)
        finally:
            product_category_combo.blockSignals(category_blocked)
            product_brand_combo.blockSignals(brand_blocked)
            product_vendor_combo.blockSignals(vendor_blocked)
        reference_selection_state["category"] = combo_value(product_category_combo)
        reference_selection_state["brand"] = combo_value(product_brand_combo)

    def set_combo_text(combo: QComboBox, value: object) -> None:
        text = str(value or "")
        was_blocked = combo.blockSignals(True)
        try:
            index = combo.findText(text)
            combo.setCurrentIndex(index if index >= 0 else 0)
        finally:
            combo.blockSignals(was_blocked)

    def clear_table(table: QTableWidget) -> None:
        table.setRowCount(0)

    def table_text(table: QTableWidget, row: int, column: int) -> str:
        item = table.item(row, column)
        return item.text().strip() if item else ""

    def set_table_row(table: QTableWidget, values: list[object]) -> None:
        row = table.rowCount()
        table.insertRow(row)
        for column, value in enumerate(values):
            table.setItem(row, column, QTableWidgetItem(str(value or "")))

    def json_value(text: str, default: object) -> object:
        stripped = text.strip()
        if not stripped:
            return default
        return jsonlib.loads(stripped)

    def optional_text(widget: QLineEdit) -> str | None:
        value = widget.text().strip()
        return value or None

    def comma_values(value: str) -> list[str]:
        return [item.strip() for item in value.split(",") if item.strip()]

    def sync_reference_selection_state() -> None:
        reference_selection_state["category"] = combo_value(product_category_combo)
        reference_selection_state["brand"] = combo_value(product_brand_combo)

    def apply_generated_product_codes() -> None:
        token = state.get("token")
        if not token:
            return
        try:
            suggestion = client.get_product_code_suggestion(token)
        except Exception:
            return
        sku = suggestion.get("sku")
        barcode = suggestion.get("barcode")
        if isinstance(sku, str) and sku.strip():
            product_sku_input.setText(sku.strip())
        if isinstance(barcode, str) and barcode.strip():
            product_barcode_input.setText(barcode.strip())

    def clear_product_form(*, generate_defaults: bool = False) -> None:
        state["selected_product_id"] = None
        product_name_input.clear()
        product_slug_input.clear()
        product_sku_input.clear()
        product_barcode_input.clear()
        product_type_input.setCurrentIndex(0)
        product_status_input.setCurrentIndex(0)
        set_combo_value(product_category_combo, None)
        set_combo_value(product_brand_combo, None)
        set_combo_value(product_vendor_combo, None)
        product_description_input.clear()
        product_short_description_input.clear()
        product_regular_price_input.setValue(0)
        product_sale_price_input.setValue(0)
        product_global_unique_id_input.clear()
        product_featured_input.setChecked(False)
        product_visibility_input.setCurrentIndex(0)
        product_tax_status_input.setCurrentIndex(0)
        product_tax_class_input.clear()
        product_manage_stock_input.setChecked(False)
        product_stock_quantity_input.setValue(0)
        product_stock_status_input.setCurrentIndex(0)
        product_backorders_input.setCurrentIndex(0)
        product_sold_individually_input.setChecked(False)
        product_weight_input.clear()
        product_length_input.clear()
        product_width_input.clear()
        product_height_input.clear()
        product_shipping_class_input.clear()
        clear_table(product_image_table)
        clear_table(product_video_table)
        clear_table(product_variant_table)
        product_seo_title_input.clear()
        product_seo_description_input.clear()
        product_reviews_allowed_input.setChecked(True)
        product_purchase_note_input.clear()
        product_menu_order_input.setValue(0)
        product_tags_input.clear()
        product_upsell_ids_input.clear()
        product_cross_sell_ids_input.clear()
        product_grouped_ids_input.clear()
        product_attributes_input.setPlainText("[]")
        product_default_attributes_input.setPlainText("[]")
        product_custom_metadata_input.setPlainText("{}")
        product_metadata_input.setPlainText("{}")
        sync_reference_selection_state()
        if generate_defaults:
            apply_generated_product_codes()
        product_message.setText("Ready for a new product.")

    def fill_product_form(product: dict[str, object]) -> None:
        state["selected_product_id"] = str(product.get("id") or "")
        product_name_input.setText(str(product.get("name") or ""))
        product_slug_input.setText(str(product.get("slug") or ""))
        product_sku_input.setText(str(product.get("sku") or ""))
        product_barcode_input.setText(str(product.get("barcode") or ""))
        set_combo_text(product_type_input, product.get("product_type"))
        set_combo_text(product_status_input, product.get("status"))
        set_combo_value(product_category_combo, product.get("category_id"))
        set_combo_value(product_brand_combo, product.get("brand_id"))
        set_combo_value(product_vendor_combo, product.get("vendor_id"))
        product_description_input.setPlainText(str(product.get("description") or ""))
        product_short_description_input.setPlainText(str(product.get("short_description") or ""))
        product_regular_price_input.setValue(int(product.get("regular_price_minor") or 0))
        product_sale_price_input.setValue(int(product.get("sale_price_minor") or 0))
        product_global_unique_id_input.setText(str(product.get("global_unique_id") or ""))
        product_featured_input.setChecked(bool(product.get("featured")))
        set_combo_text(product_visibility_input, product.get("visibility"))
        set_combo_text(product_tax_status_input, product.get("tax_status"))
        product_tax_class_input.setText(str(product.get("tax_class") or ""))
        product_manage_stock_input.setChecked(bool(product.get("manage_stock")))
        product_stock_quantity_input.setValue(int(product.get("stock_quantity") or 0))
        set_combo_text(product_stock_status_input, product.get("stock_status"))
        set_combo_text(product_backorders_input, product.get("backorders"))
        product_sold_individually_input.setChecked(bool(product.get("sold_individually")))
        product_weight_input.setText(str(product.get("weight") or ""))
        product_length_input.setText(str(product.get("length") or ""))
        product_width_input.setText(str(product.get("width") or ""))
        product_height_input.setText(str(product.get("height") or ""))
        product_shipping_class_input.setText(str(product.get("shipping_class") or ""))
        clear_table(product_image_table)
        for image in product.get("images") if isinstance(product.get("images"), list) else []:
            if isinstance(image, dict):
                set_table_row(
                    product_image_table,
                    [
                        image.get("id"),
                        image.get("url"),
                        image.get("alt_text"),
                        image.get("sort_order"),
                        image.get("external_id"),
                        image.get("name"),
                        image.get("sync_status"),
                        image.get("last_synced_at"),
                    ],
                )
        clear_table(product_video_table)
        for video in product.get("videos") if isinstance(product.get("videos"), list) else []:
            if isinstance(video, dict):
                set_table_row(
                    product_video_table,
                    [
                        video.get("id"),
                        video.get("source_type"),
                        video.get("url"),
                        video.get("name"),
                        video.get("sort_order"),
                        video.get("sync_status"),
                        video.get("remote_url"),
                        video.get("last_synced_at"),
                        video.get("created_at"),
                    ],
                )
        clear_table(product_variant_table)
        for variant in product.get("variants") if isinstance(product.get("variants"), list) else []:
            if isinstance(variant, dict):
                set_table_row(
                    product_variant_table,
                    [
                        variant.get("id"),
                        variant.get("name"),
                        variant.get("sku"),
                        variant.get("barcode"),
                        variant.get("price_minor"),
                        variant.get("sale_price_minor"),
                        variant.get("cost_minor"),
                        variant.get("currency") or "PKR",
                        jsonlib.dumps(variant.get("attributes") or {}, ensure_ascii=True),
                        "true" if variant.get("is_active", True) else "false",
                    ],
                )
        product_seo_title_input.setText(str(product.get("seo_title") or ""))
        product_seo_description_input.setPlainText(str(product.get("seo_description") or ""))
        product_reviews_allowed_input.setChecked(bool(product.get("reviews_allowed", True)))
        product_purchase_note_input.setPlainText(str(product.get("purchase_note") or ""))
        product_menu_order_input.setValue(int(product.get("menu_order") or 0))
        product_tags_input.setText(", ".join(str(v) for v in product.get("tags", [])))
        product_upsell_ids_input.setText(", ".join(str(v) for v in product.get("upsell_ids", [])))
        product_cross_sell_ids_input.setText(
            ", ".join(str(v) for v in product.get("cross_sell_ids", []))
        )
        product_grouped_ids_input.setText(
            ", ".join(str(v) for v in product.get("grouped_product_ids", []))
        )
        product_attributes_input.setPlainText(
            jsonlib.dumps(product.get("attributes") or [], indent=2, ensure_ascii=True)
        )
        product_default_attributes_input.setPlainText(
            jsonlib.dumps(product.get("default_attributes") or [], indent=2, ensure_ascii=True)
        )
        product_custom_metadata_input.setPlainText(
            jsonlib.dumps(product.get("custom_metadata") or {}, indent=2, ensure_ascii=True)
        )
        product_metadata_input.setPlainText(
            jsonlib.dumps(product.get("metadata") or {}, indent=2, ensure_ascii=True)
        )
        sync_reference_selection_state()

    def create_category_from_dropdown() -> None:
        token = current_token()
        if not token:
            return
        name, accepted = QInputDialog.getText(window, "Add Category", "Category name:")
        if not accepted:
            return
        category_name = name.strip()
        if not category_name:
            product_message.setText("Category name is required.")
            set_status("Category name is required.", ok=False)
            return

        def action() -> None:
            category = client.create_category(token, {"name": category_name})
            load_product_reference_options(token)
            set_combo_value(product_category_combo, category.get("id"))
            sync_reference_selection_state()
            product_message.setText(f"Category '{category_name}' created.")
            set_status("Category created.", ok=True)

        guarded(product_message, action)

    def create_brand_from_dropdown() -> None:
        token = current_token()
        if not token:
            return
        name, accepted = QInputDialog.getText(window, "Add Brand", "Brand name:")
        if not accepted:
            return
        brand_name = name.strip()
        if not brand_name:
            product_message.setText("Brand name is required.")
            set_status("Brand name is required.", ok=False)
            return

        def action() -> None:
            brand = client.create_brand(token, {"name": brand_name})
            load_product_reference_options(token)
            set_combo_value(product_brand_combo, brand.get("id"))
            sync_reference_selection_state()
            product_message.setText(f"Brand '{brand_name}' created.")
            set_status("Brand created.", ok=True)

        guarded(product_message, action)

    def on_category_combo_activated(index: int) -> None:
        if product_category_combo.itemData(index) == CREATE_CATEGORY_ACTION:
            set_combo_value(product_category_combo, reference_selection_state["category"])
            create_category_from_dropdown()
            return
        reference_selection_state["category"] = combo_value(product_category_combo)

    def on_brand_combo_activated(index: int) -> None:
        if product_brand_combo.itemData(index) == CREATE_BRAND_ACTION:
            set_combo_value(product_brand_combo, reference_selection_state["brand"])
            create_brand_from_dropdown()
            return
        reference_selection_state["brand"] = combo_value(product_brand_combo)

    def collect_product_payload() -> dict[str, object]:
        name = product_name_input.text().strip()
        if not name:
            raise ValueError("Product name is required.")
        images: list[dict[str, object]] = []
        for row in range(product_image_table.rowCount()):
            url = table_text(product_image_table, row, 1)
            if not url:
                continue
            sort_text = table_text(product_image_table, row, 3) or str(row)
            images.append(
                {
                    "id": table_text(product_image_table, row, 0) or None,
                    "url": url,
                    "alt_text": table_text(product_image_table, row, 2) or None,
                    "sort_order": int(sort_text),
                    "external_id": table_text(product_image_table, row, 4) or None,
                    "name": table_text(product_image_table, row, 5) or None,
                }
            )
        videos: list[dict[str, object]] = []
        for row in range(product_video_table.rowCount()):
            url = table_text(product_video_table, row, 2)
            if not url:
                continue
            sort_text = table_text(product_video_table, row, 4) or str(row)
            videos.append(
                {
                    "id": table_text(product_video_table, row, 0) or None,
                    "url": url,
                    "name": table_text(product_video_table, row, 3) or None,
                    "sort_order": int(sort_text),
                }
            )
        variants: list[dict[str, object]] = []
        for row in range(product_variant_table.rowCount()):
            variants.append(
                {
                    "id": table_text(product_variant_table, row, 0) or None,
                    "name": table_text(product_variant_table, row, 1) or None,
                    "sku": table_text(product_variant_table, row, 2) or None,
                    "barcode": table_text(product_variant_table, row, 3) or None,
                    "price_minor": int(table_text(product_variant_table, row, 4) or "0"),
                    "sale_price_minor": (
                        int(table_text(product_variant_table, row, 5))
                        if table_text(product_variant_table, row, 5)
                        else None
                    ),
                    "cost_minor": (
                        int(table_text(product_variant_table, row, 6))
                        if table_text(product_variant_table, row, 6)
                        else None
                    ),
                    "currency": table_text(product_variant_table, row, 7) or "PKR",
                    "attributes": json_value(table_text(product_variant_table, row, 8), {}),
                    "is_active": table_text(product_variant_table, row, 9).lower()
                    not in {"false", "0", "no"},
                }
            )
        category_id = combo_value(product_category_combo)
        payload: dict[str, object] = {
            "name": name,
            "slug": optional_text(product_slug_input),
            "sku": optional_text(product_sku_input),
            "barcode": optional_text(product_barcode_input),
            "product_type": product_type_input.currentText(),
            "status": product_status_input.currentText(),
            "category_id": category_id,
            "category_ids": [category_id] if category_id else [],
            "brand_id": combo_value(product_brand_combo),
            "vendor_id": combo_value(product_vendor_combo),
            "description": product_description_input.toPlainText().strip() or None,
            "short_description": product_short_description_input.toPlainText().strip() or None,
            "regular_price_minor": product_regular_price_input.value(),
            "sale_price_minor": product_sale_price_input.value() or None,
            "global_unique_id": optional_text(product_global_unique_id_input),
            "featured": product_featured_input.isChecked(),
            "visibility": product_visibility_input.currentText(),
            "tax_status": product_tax_status_input.currentText(),
            "tax_class": optional_text(product_tax_class_input),
            "manage_stock": product_manage_stock_input.isChecked(),
            "stock_quantity": product_stock_quantity_input.value(),
            "stock_status": product_stock_status_input.currentText(),
            "backorders": product_backorders_input.currentText(),
            "sold_individually": product_sold_individually_input.isChecked(),
            "weight": optional_text(product_weight_input),
            "length": optional_text(product_length_input),
            "width": optional_text(product_width_input),
            "height": optional_text(product_height_input),
            "shipping_class": optional_text(product_shipping_class_input),
            "images": images,
            "videos": videos,
            "variants": variants,
            "seo_title": optional_text(product_seo_title_input),
            "seo_description": product_seo_description_input.toPlainText().strip() or None,
            "reviews_allowed": product_reviews_allowed_input.isChecked(),
            "purchase_note": product_purchase_note_input.toPlainText().strip() or None,
            "menu_order": product_menu_order_input.value(),
            "tags": comma_values(product_tags_input.text()),
            "upsell_ids": comma_values(product_upsell_ids_input.text()),
            "cross_sell_ids": comma_values(product_cross_sell_ids_input.text()),
            "grouped_product_ids": comma_values(product_grouped_ids_input.text()),
            "attributes": json_value(product_attributes_input.toPlainText(), []),
            "default_attributes": json_value(product_default_attributes_input.toPlainText(), []),
            "custom_metadata": json_value(product_custom_metadata_input.toPlainText(), {}),
            "metadata": json_value(product_metadata_input.toPlainText(), {}),
        }
        return payload

    def save_product() -> None:
        token = current_token()
        if not token:
            set_page_message(product_message, "Login required.", ok=False)
            set_status("Login required before saving products.", ok=False)
            return
        try:
            payload = collect_product_payload()
        except Exception as exc:
            set_page_message(product_message, f"Product form error: {exc}", ok=False)
            set_status(f"Product form error: {exc}", ok=False)
            return

        def action() -> None:
            product_id = state.get("selected_product_id")
            if product_id:
                product = client.update_product(token, product_id, payload)
            else:
                product = client.create_product(token, payload=payload)
            fill_product_form(product)
            refresh_products()
            set_page_message(product_message, "Product saved.", ok=True)
            set_status("Product saved.", ok=True)

        guarded(product_message, action)

    def load_selected_product() -> None:
        token = current_token()
        if not token:
            return
        row = product_table.currentRow()
        if row < 0:
            return
        product_id = table_text(product_table, row, 0)
        if not product_id:
            return

        def action() -> None:
            product = client.get_product(token, product_id)
            fill_product_form(product)
            product_message.setText(f"Editing {product.get('name', product_id)}.")

        guarded(product_message, action)

    def archive_selected_product() -> None:
        token = current_token()
        product_id = state.get("selected_product_id")
        if not token or not product_id:
            product_message.setText("Select a product to archive.")
            return

        def action() -> None:
            client.archive_product(token, product_id)
            clear_product_form()
            refresh_products()
            product_message.setText("Product archived.")

        guarded(product_message, action)

    def show_product_trash() -> None:
        set_combo_value(product_status_filter, "archived")
        refresh_products()

    def selected_product_ids() -> list[str]:
        rows = sorted({index.row() for index in product_table.selectionModel().selectedRows()})
        return [
            table_text(product_table, row, 0)
            for row in rows
            if table_text(product_table, row, 0) and not product_table.isRowHidden(row)
        ]

    def change_product_status(status: str, *, bulk: bool = False) -> None:
        token = current_token()
        ids = selected_product_ids() if bulk else [str(state.get("selected_product_id") or "")]
        ids = [product_id for product_id in ids if product_id]
        if not token or not ids:
            set_page_message(product_message, "Select one or more products first.", ok=False)
            return

        def action() -> None:
            for product_id in ids:
                client.update_product(token, product_id, {"status": status})
            refresh_products()
            product_message.setText(f"Updated {len(ids)} product(s).")

        guarded(product_message, action)

    def permanently_delete_products(*, bulk: bool = False) -> None:
        token = current_token()
        ids = selected_product_ids() if bulk else [str(state.get("selected_product_id") or "")]
        ids = [product_id for product_id in ids if product_id]
        if not token or not ids:
            set_page_message(
                product_message, "Select one or more trashed products first.", ok=False
            )
            return
        reply = QMessageBox.question(
            window,
            "Delete Permanently",
            f"Delete {len(ids)} product(s) permanently? This cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        def action() -> None:
            for product_id in ids:
                client.permanently_delete_product(token, product_id)
            if state.get("selected_product_id") in ids:
                clear_product_form()
            refresh_products()
            set_page_message(
                product_message, f"Deleted {len(ids)} product(s) permanently.", ok=True
            )
            set_status("Product permanently deleted.", ok=True)

        guarded(product_message, action)

    def apply_product_bulk_action() -> None:
        status = product_bulk_action.currentData()
        if status == "delete_permanent":
            permanently_delete_products(bulk=True)
        elif status:
            change_product_status(str(status), bulk=True)
        product_bulk_action.setCurrentIndex(0)

    def apply_product_filter() -> None:
        query = product_search_input.text().strip().lower()
        status = str(product_status_filter.currentData() or "all")

        key = str(product_sort_input.currentData() or "name")
        reverse = product_sort_order.currentData() == "desc"
        sort_column = next(
            (index for index, (field, _label) in enumerate(product_columns) if field == key), 1
        )
        product_table.sortItems(
            sort_column,
            Qt.SortOrder.DescendingOrder if reverse else Qt.SortOrder.AscendingOrder,
        )

        status_label = {"active": "Published", "draft": "Draft", "archived": "Trash"}.get(
            status, status
        )
        for row in range(product_table.rowCount()):
            value = product_table.item(row, 3)
            hide_by_status = status != "all" and (not value or value.text().strip() != status_label)

            values = [
                table_text(product_table, row, column).lower()
                for column in range(product_table.columnCount())
            ]
            hide_by_query = bool(query and query not in " ".join(values))

            product_table.setRowHidden(row, hide_by_status or hide_by_query)

    def add_product_image_url() -> None:
        url = product_add_image_url_input.text().strip()
        if not url:
            product_message.setText("Image URL is required.")
            return
        set_table_row(
            product_image_table,
            [
                "",
                url,
                product_name_input.text().strip(),
                product_image_table.rowCount(),
                "",
                "",
                "pending_add",
                "",
            ],
        )
        product_add_image_url_input.clear()

    def upload_product_image() -> None:
        token = current_token()
        product_id = state.get("selected_product_id")
        if not token or not product_id:
            product_message.setText("Save the product before uploading images.")
            return
        file_path, _ = QFileDialog.getOpenFileName(
            window,
            "Select product image",
            "",
            "Images (*.jpg *.jpeg *.png *.webp *.gif)",
        )
        if not file_path:
            return

        def action() -> None:
            image = client.upload_product_image(token, product_id, file_path)
            set_table_row(
                product_image_table,
                [
                    image.get("id"),
                    image.get("url"),
                    image.get("alt_text"),
                    image.get("sort_order"),
                    image.get("external_id"),
                    image.get("name"),
                    image.get("sync_status"),
                    image.get("last_synced_at"),
                ],
            )
            product_message.setText("Image uploaded.")

        guarded(product_message, action)

    def remove_selected_image() -> None:
        row = product_image_table.currentRow()
        if row >= 0:
            product_image_table.removeRow(row)

    def add_product_video_url() -> None:
        url = product_add_video_url_input.text().strip()
        if not url:
            product_message.setText("Video URL is required.")
            return
        if product_video_table.rowCount() >= 10:
            product_message.setText("A product can have at most 10 videos.")
            return
        set_table_row(
            product_video_table,
            ["", "URL", url, "", product_video_table.rowCount(), "pending_add", "", "", ""],
        )
        product_add_video_url_input.clear()

    def upload_product_video() -> None:
        token = current_token()
        product_id = state.get("selected_product_id")
        if not token or not product_id:
            product_message.setText("Save the product before uploading videos.")
            return
        if product_video_table.rowCount() >= 10:
            product_message.setText("A product can have at most 10 videos.")
            return
        file_path, _ = QFileDialog.getOpenFileName(
            window,
            "Select product video",
            "",
            "MP4 Videos (*.mp4)",
        )
        if not file_path:
            return

        def action() -> None:
            video = client.upload_product_video(token, product_id, file_path)
            set_table_row(
                product_video_table,
                [
                    video.get("id"),
                    video.get("source_type"),
                    video.get("url"),
                    video.get("name"),
                    video.get("sort_order"),
                    video.get("sync_status"),
                    video.get("remote_url"),
                    video.get("last_synced_at"),
                    video.get("created_at"),
                ],
            )
            product_message.setText("Video uploaded.")

        guarded(product_message, action)

    def open_selected_product_video() -> None:
        row = product_video_table.currentRow()
        url = table_text(product_video_table, row, 2) if row >= 0 else ""
        if not url:
            product_message.setText("Select a product video first.")
            return
        target = f"{client.base_url}{url}" if url.startswith("/") else url
        if not QDesktopServices.openUrl(QUrl(target)):
            product_message.setText("The system browser could not open this video.")

    def remove_selected_video() -> None:
        row = product_video_table.currentRow()
        if row >= 0:
            product_video_table.removeRow(row)
            product_message.setText("Video removed. Save the product to apply this change.")

    def add_product_variant() -> None:
        set_table_row(
            product_variant_table,
            ["", "Default", "", "", "0", "", "", "PKR", "{}", "true"],
        )

    def remove_selected_variant() -> None:
        row = product_variant_table.currentRow()
        if row >= 0:
            product_variant_table.removeRow(row)

    def refresh_customers() -> None:
        token = current_token()
        if not token:
            customer_message.setText("Login required.")
            return

        def action() -> None:
            customers = client.list_customers(token)
            populate_table(customer_table, customers, customer_columns)
            customer_message.setText(f"{len(customers)} customers loaded.")
            set_status("Customers loaded.", ok=True)

        guarded(customer_message, action)

    def create_customer() -> None:
        token = current_token()
        if not token:
            customer_message.setText("Login required.")
            return
        full_name = customer_name_input.text().strip()
        phone = customer_phone_input.text().strip() or None
        email = customer_email_input.text().strip() or None
        if not full_name:
            customer_message.setText("Customer name is required.")
            return

        def action() -> None:
            client.create_customer(token, full_name=full_name, phone=phone, email=email)
            customer_name_input.clear()
            customer_phone_input.clear()
            customer_email_input.clear()
            refresh_customers()

        guarded(customer_message, action)

    def refresh_inventory() -> None:
        token = current_token()
        if not token:
            inventory_message.setText("Login required.")
            return

        def action() -> None:
            stock = client.list_stock(token)
            populate_table(inventory_table, stock, inventory_columns)
            inventory_message.setText(f"{len(stock)} stock rows loaded.")
            set_status("Inventory loaded.", ok=True)

        guarded(inventory_message, action)

    def refresh_orders() -> None:
        token = current_token()
        if not token:
            orders_message.setText("Login required.")
            return

        def action() -> None:
            orders = client.list_orders(token)
            populate_table(orders_table, orders, order_columns)
            orders_message.setText(f"{len(orders)} orders loaded.")
            set_status("Orders loaded.", ok=True)

        guarded(orders_message, action)

    def refresh_woocommerce(show_loaded_status: bool = True) -> None:
        refresh_api_health_status()
        token = current_token()
        if not token:
            set_page_message(woocommerce_message, "Login required.", ok=False)
            return

        def action() -> None:
            config = client.get_woocommerce_config(token)
            runs = client.list_woocommerce_sync_runs(token)
            conflicts = client.list_woocommerce_conflicts(token)
            site_url = str(config.get("site_url") or "")
            if site_url and not woo_site_url_input.text().strip():
                woo_site_url_input.setText(site_url)
            wp_username = str(config.get("wordpress_username") or "")
            if wp_username and not woo_wp_username_input.text().strip():
                woo_wp_username_input.setText(wp_username)
            populate_table(
                woocommerce_runs_table,
                woocommerce_run_rows(runs),
                woocommerce_run_columns,
            )
            populate_table(
                woocommerce_conflicts_table,
                conflicts,
                woocommerce_conflict_columns,
            )
            woocommerce_summary.setPlainText(woocommerce_status_summary(config, runs, conflicts))
            if show_loaded_status:
                latest_run = runs[0] if runs else {}
                latest_status = str(latest_run.get("status")) if runs else "none"
                ok = latest_status not in {"failed"}
                if latest_status == "running":
                    message = woocommerce_sync_running_message(latest_run)
                else:
                    message = f"WooCommerce status loaded. Last sync: {latest_status}."
                set_page_message(woocommerce_message, message, ok=ok)
                if ok:
                    refresh_api_health_status(success_message=message)
                else:
                    set_status(message, ok=False)

        guarded(woocommerce_message, action)

    def poll_woocommerce_sync() -> None:
        token = current_token()
        run_id = state.get("woo_sync_run_id")
        if not token or not run_id:
            return

        try:
            runs = client.list_woocommerce_sync_runs(token)
        except Exception as exc:
            message = (
                format_api_error(exc, api_base_url)
                if isinstance(exc, ApiResponseError)
                else str(exc)
            )
            set_page_message(
                woocommerce_message,
                f"WooCommerce sync check failed: {message}",
                ok=False,
            )
            set_status(f"WooCommerce sync check failed: {message}", ok=False)
            for control in (
                woo_sync_button,
                dashboard_sync_products_button,
                dashboard_sync_all_button,
            ):
                control.setEnabled(True)
            state["woo_sync_run_id"] = None
            return

        latest = next((run for run in runs if str(run.get("id") or "") == run_id), None)
        if latest is None:
            refresh_woocommerce(show_loaded_status=True)
            for control in (
                woo_sync_button,
                dashboard_sync_products_button,
                dashboard_sync_all_button,
            ):
                control.setEnabled(True)
            state["woo_sync_run_id"] = None
            return

        status = str(latest.get("status") or "unknown")
        if status in {"queued", "running"}:
            message = (
                woocommerce_sync_running_message(latest)
                if status == "running"
                else "WooCommerce sync queued. Waiting for worker."
            )
            set_page_message(woocommerce_message, message, ok=True)
            set_status(message, ok=True)
            refresh_woocommerce(show_loaded_status=False)
            QTimer.singleShot(1500, poll_woocommerce_sync)
            return

        refresh_woocommerce(show_loaded_status=True)
        for control in (
            woo_sync_button,
            dashboard_sync_products_button,
            dashboard_sync_all_button,
        ):
            control.setEnabled(True)
        state["woo_sync_run_id"] = None

    def save_woocommerce() -> None:
        token = current_token()
        if not token:
            set_page_message(woocommerce_message, "Login required.", ok=False)
            return
        site_url = woo_site_url_input.text().strip()
        consumer_key = woo_consumer_key_input.text().strip()
        consumer_secret = woo_consumer_secret_input.text().strip()
        webhook_secret = woo_webhook_secret_input.text().strip() or None
        wordpress_username = woo_wp_username_input.text().strip() or None
        wordpress_application_password = woo_wp_app_password_input.text().strip() or None
        if not site_url or not consumer_key or not consumer_secret:
            set_page_message(
                woocommerce_message,
                "Site URL, consumer key, and consumer secret are required.",
                ok=False,
            )
            return

        def action() -> None:
            client.save_woocommerce_config(
                token,
                site_url=site_url,
                consumer_key=consumer_key,
                consumer_secret=consumer_secret,
                webhook_secret=webhook_secret,
                wordpress_username=wordpress_username,
                wordpress_application_password=wordpress_application_password,
            )
            woo_consumer_secret_input.clear()
            woo_webhook_secret_input.clear()
            woo_wp_app_password_input.clear()
            refresh_woocommerce(show_loaded_status=False)
            message = "WooCommerce config saved. Secrets were stored securely and hidden."
            set_page_message(woocommerce_message, message, ok=True)
            set_status(message, ok=True)

        guarded(woocommerce_message, action)

    def test_woocommerce() -> None:
        token = current_token()
        if not token:
            set_page_message(woocommerce_message, "Login required.", ok=False)
            return

        def action() -> None:
            result = client.test_woocommerce_connection(token)
            ok = bool(result.get("ok"))
            detail = str(result.get("detail") or result.get("status") or "Connection tested.")
            set_page_message(woocommerce_message, detail, ok=ok)
            set_status(detail, ok=ok)

        guarded(woocommerce_message, action)

    def run_woocommerce_sync(mode: str = "incremental") -> None:
        token = current_token()
        if not token:
            set_page_message(woocommerce_message, "Login required.", ok=False)
            return

        def action() -> None:
            message = (
                "WooCommerce product sync queued..."
                if mode in {"full_products", "products"}
                else "WooCommerce content sync queued..."
            )
            set_page_message(woocommerce_message, message, ok=True)
            set_status(message, ok=True)
            sync_controls = (
                woo_sync_button,
                dashboard_sync_products_button,
                dashboard_sync_all_button,
            )
            for control in sync_controls:
                control.setEnabled(False)
            QApplication.processEvents()
            try:
                run_log = client.run_woocommerce_sync(token, mode=mode)
                stats = run_log.get("stats") or {}
                status = str(run_log.get("status", "completed"))
                run_id = str(run_log.get("id") or "").strip()
                error = str(run_log.get("error") or "").strip()
                if run_id:
                    state["woo_sync_run_id"] = run_id
                if status == "failed" and error:
                    message = f"WooCommerce sync failed: {error}"
                    ok = False
                else:
                    phase = str(stats.get("current_phase") or "").strip()
                    if status == "running" and phase:
                        message = f"WooCommerce sync running: {phase}"
                    elif status == "running":
                        message = "WooCommerce sync running..."
                    else:
                        message = f"WooCommerce sync {status}: {stats}"
                    ok = status != "failed"
                refresh_woocommerce(show_loaded_status=False)
                set_page_message(woocommerce_message, message, ok=ok)
                set_status(message, ok=ok)
                if status in {"queued", "running"} and run_id:
                    QTimer.singleShot(500, poll_woocommerce_sync)
                    return
            finally:
                if not state.get("woo_sync_run_id"):
                    for control in sync_controls:
                        control.setEnabled(True)

        guarded(woocommerce_message, action)

    def refresh_marketplace() -> None:
        nonlocal marketplace_orders_offset, marketplace_orders_limit
        token = current_token()
        if not token:
            marketplace_message.setText("Login required.")
            return
        if not marketplace_refresh_button.isEnabled():
            return
        permissions = set(state.get("permissions") or [])
        roles = [str(value) for value in state.get("roles") or []]
        date_from = marketplace_date_from_input.text().strip() or None
        date_to = marketplace_date_to_input.text().strip() or None
        order_status = marketplace_order_status_filter.text().strip() or None
        payment_status = marketplace_payment_status_filter.text().strip() or None
        settlement_status = marketplace_settlement_status_filter.text().strip() or None

        def operation() -> object:
            vendors = client.list_vendors(token) if "vendors.view" in permissions else []
            own: dict[str, object] | None = None
            if should_load_vendor_self(roles, permissions):
                current_vendor = client.get_current_vendor(token)
                own = {
                    "vendor": current_vendor,
                    "dashboard": client.get_current_vendor_dashboard(token),
                    "products": (
                        client.list_current_vendor_products(token)
                        if "vendor.products.view" in permissions
                        else []
                    ),
                    "orders": (
                        client.list_own_vendor_orders(
                            token,
                            date_from=date_from,
                            date_to=date_to,
                            order_status=order_status,
                            payment_status=payment_status,
                            limit=marketplace_orders_limit,
                            offset=marketplace_orders_offset,
                        )
                        if "vendor.orders.view" in permissions
                        else []
                    ),
                    "settlements": (
                        client.list_own_vendor_settlements(
                            token,
                            date_from=date_from,
                            date_to=date_to,
                            status=settlement_status,
                        )
                        if "vendor.settlements.view" in permissions
                        else []
                    ),
                    "overview": (
                        client.get_vendor_ledger_overview(token)
                        if "vendor.ledger.view" in permissions
                        else current_vendor
                    ),
                    "stock": (
                        client.list_vendor_stock(token)
                        if "vendor.stock.view" in permissions
                        else []
                    ),
                    "movements": (
                        client.list_vendor_stock_movements(
                            token,
                            date_from=date_from,
                            date_to=date_to,
                        )
                        if "vendor.stock.view" in permissions
                        else []
                    ),
                    "ledger": (
                        client.list_authoritative_vendor_ledger(
                            token,
                            date_from=date_from,
                            date_to=date_to,
                        )
                        if "vendor.ledger.view" in permissions
                        else []
                    ),
                }
            return {"vendors": vendors, "own": own}

        def completed(value: object) -> None:
            result = value if isinstance(value, dict) else {}
            vendors_value = result.get("vendors")
            vendors = vendors_value if isinstance(vendors_value, list) else []
            populate_table(marketplace_vendor_table, vendors, marketplace_vendor_columns)
            own_value = result.get("own")
            own = own_value if isinstance(own_value, dict) else None
            if own is not None:
                current_vendor_value = own.get("vendor")
                current_vendor = (
                    current_vendor_value if isinstance(current_vendor_value, dict) else {}
                )
                dashboard_value = own.get("dashboard")
                dashboard = dashboard_value if isinstance(dashboard_value, dict) else {}
                products_value = own.get("products")
                products = products_value if isinstance(products_value, list) else []
                orders_value = own.get("orders")
                orders = orders_value if isinstance(orders_value, list) else []
                settlements_value = own.get("settlements")
                settlements = settlements_value if isinstance(settlements_value, list) else []
                overview_value = own.get("overview")
                authoritative_overview = overview_value if isinstance(overview_value, dict) else {}
                stock_value = own.get("stock")
                stock = stock_value if isinstance(stock_value, list) else []
                movements_value = own.get("movements")
                movements = movements_value if isinstance(movements_value, list) else []
                ledger_value = own.get("ledger")
                ledger_rows = ledger_value if isinstance(ledger_value, list) else []
                populate_table(
                    marketplace_current_products_table,
                    products,
                    marketplace_current_products_columns,
                )
                populate_table(
                    marketplace_current_orders_table,
                    orders,
                    marketplace_current_orders_columns,
                )
                populate_table(
                    marketplace_current_settlements_table,
                    settlements,
                    marketplace_current_settlements_columns,
                )
                populate_table(
                    marketplace_vendor_stock_table,
                    stock,
                    [
                        ("product_id", "Product"),
                        ("warehouse_id", "Warehouse"),
                        ("ownership_type", "Ownership"),
                        ("on_hand_quantity", "On Hand"),
                        ("reserved_quantity", "Reserved"),
                        ("available_quantity", "Available"),
                    ],
                )
                populate_table(
                    marketplace_vendor_movement_table,
                    movements,
                    [
                        ("occurred_at", "When"),
                        ("movement_type", "Type"),
                        ("product_id", "Product"),
                        ("quantity_delta", "Quantity"),
                        ("quantity_before", "Before"),
                        ("quantity_after", "After"),
                        ("reason", "Reason"),
                    ],
                )
                populate_table(
                    marketplace_vendor_financial_table,
                    ledger_rows,
                    [
                        ("posted_at", "When"),
                        ("entry_number", "Entry"),
                        ("source_type", "Source"),
                        ("debit_minor", "Debit"),
                        ("credit_minor", "Credit"),
                        ("balance_minor", "Balance"),
                    ],
                )
                marketplace_vendor_overview_text.setPlainText(
                    "\n".join(
                        f"{key.replace('_', ' ').title()}: {value}"
                        for key, value in authoritative_overview.items()
                    )
                )
                marketplace_vendor_reports_text.setPlainText(
                    "\n".join(
                        [
                            f"Filtered orders: {len(orders)}",
                            "Filtered gross sales: "
                            f"{sum(int(row.get('line_total_minor') or 0) for row in orders)}",
                            "Filtered commission: "
                            f"{sum(int(row.get('commission_minor') or 0) for row in orders)}",
                            "Filtered payable: "
                            f"{sum(int(row.get('payable_minor') or 0) for row in orders)}",
                            f"Filtered settlements: {len(settlements)}",
                            "Filtered settlement paid: "
                            f"{sum(int(row.get('paid_minor') or 0) for row in settlements)}",
                            f"Stock records: {len(stock)}",
                        ]
                    )
                )
                marketplace_vendor_users_table.setRowCount(0)
                marketplace_vendor_audit_table.setRowCount(0)
                marketplace_current_vendor_text.setPlainText(
                    "\n".join(
                        [
                            f"Vendor: {current_vendor.get('name') or 'unknown'}",
                            f"Slug: {current_vendor.get('slug') or 'n/a'}",
                            "Access status: {}".format(
                                current_vendor.get("access_status")
                                or current_vendor.get("status")
                                or "unknown"
                            ),
                            f"Products: {dashboard.get('product_count', 0)}",
                            f"Orders: {dashboard.get('order_count', 0)}",
                            f"Settlements: {dashboard.get('settlement_count', 0)}",
                            f"Balance: {dashboard.get('balance_minor', 0)}",
                        ]
                    )
                )
            else:
                marketplace_current_vendor_text.setPlainText(
                    "Vendor self-service is not assigned to this account."
                )
                marketplace_current_products_table.setRowCount(0)
                marketplace_current_orders_table.setRowCount(0)
                marketplace_current_settlements_table.setRowCount(0)
                marketplace_vendor_stock_table.setRowCount(0)
                marketplace_vendor_movement_table.setRowCount(0)
                marketplace_vendor_financial_table.setRowCount(0)
            marketplace_message.setText("Marketplace loaded.")
            set_status("Marketplace loaded.", ok=True)

        start_session_api_task(
            marketplace_message,
            operation,
            on_result=completed,
            controls=(marketplace_refresh_button,),
        )

    def create_vendor() -> None:
        token = current_token()
        if not token:
            marketplace_message.setText("Login required.")
            return
        name = marketplace_vendor_name_input.text().strip()
        if not name:
            marketplace_message.setText("Vendor name is required.")
            return
        payload: dict[str, object] = {"name": name}
        for key, widget in (
            ("slug", marketplace_vendor_slug_input),
            ("legal_name", marketplace_vendor_legal_input),
            ("contact_name", marketplace_vendor_contact_input),
            ("email", marketplace_vendor_email_input),
            ("phone", marketplace_vendor_phone_input),
        ):
            value = widget.text().strip()
            if value:
                payload[key] = value
        commission_text = marketplace_vendor_commission_input.text().strip()
        if commission_text:
            try:
                payload["default_commission_bps"] = int(commission_text)
            except ValueError:
                marketplace_message.setText("Commission BPS must be a number.")
                return
        payload["status"] = marketplace_vendor_status_input.currentText()
        username = marketplace_vendor_username_input.text().strip()
        password = marketplace_vendor_password_input.text()
        account_payload: dict[str, object] | None = None
        if username:
            onboarding = str(marketplace_vendor_onboarding_input.currentData() or "activation")
            try:
                account_payload = build_vendor_account_payload(
                    business_name=name,
                    username=username,
                    email=marketplace_vendor_email_input.text(),
                    contact_name=marketplace_vendor_contact_input.text(),
                    phone=marketplace_vendor_phone_input.text(),
                    onboarding=onboarding,
                    temporary_password=password,
                    default_commission_bps=int(payload.get("default_commission_bps", 0)),
                )
            except ValueError as exc:
                marketplace_message.setText(str(exc))
                return
        marketplace_vendor_password_input.clear()

        def operation() -> object:
            if account_payload is not None:
                return {
                    "with_account": True,
                    "result": client.create_vendor_account(token, account_payload),
                }
            return {
                "with_account": False,
                "result": client.create_vendor(token, payload),
            }

        def completed(value: object) -> None:
            outcome = value if isinstance(value, dict) else {}
            result = outcome.get("result")
            if bool(outcome.get("with_account")) and isinstance(result, dict):
                marketplace_vendor_onboarding_result.setPlainText(
                    "\n".join(vendor_onboarding_result_lines(result))
                )
                marketplace_message.setText("Vendor and linked login account created.")
            else:
                marketplace_vendor_onboarding_result.setPlainText(
                    "Vendor-only record created without a login account."
                )
            marketplace_vendor_name_input.clear()
            marketplace_vendor_slug_input.clear()
            marketplace_vendor_legal_input.clear()
            marketplace_vendor_contact_input.clear()
            marketplace_vendor_email_input.clear()
            marketplace_vendor_phone_input.clear()
            marketplace_vendor_status_input.setCurrentText("active")
            marketplace_vendor_username_input.clear()
            marketplace_vendor_onboarding_input.setCurrentIndex(0)
            marketplace_vendor_commission_input.setText("0")
            QTimer.singleShot(0, refresh_marketplace)

        start_session_api_task(
            marketplace_message,
            operation,
            on_result=completed,
            controls=(marketplace_vendor_create_button,),
        )

    def edit_vendor() -> None:
        token = current_token()
        vendor_id = selected_vendor_id()
        if not token or not vendor_id:
            marketplace_message.setText("Select a vendor first.")
            return

        from PySide6.QtWidgets import QDialog, QDialogButtonBox, QFormLayout, QLineEdit, QVBoxLayout

        dialog = QDialog()
        dialog.setWindowTitle("Edit Vendor")
        dialog.resize(400, 300)
        layout = QVBoxLayout(dialog)
        form_layout = QFormLayout()

        try:
            vendor = client.get_vendor(token, vendor_id)
        except Exception as e:
            marketplace_message.setText(f"Failed to fetch vendor: {e}")
            return

        name_input = QLineEdit(str(vendor.get("name", "")))
        slug_input = QLineEdit(str(vendor.get("slug", "")))
        legal_name_input = QLineEdit(str(vendor.get("legal_name", "")))
        contact_name_input = QLineEdit(str(vendor.get("contact_name", "")))
        email_input = QLineEdit(str(vendor.get("email", "")))
        phone_input = QLineEdit(str(vendor.get("phone", "")))
        commission_input = QLineEdit(str(vendor.get("default_commission_bps", 0)))

        form_layout.addRow("Name", name_input)
        form_layout.addRow("Slug", slug_input)
        form_layout.addRow("Legal Name", legal_name_input)
        form_layout.addRow("Contact Name", contact_name_input)
        form_layout.addRow("Email", email_input)
        form_layout.addRow("Phone", phone_input)
        form_layout.addRow("Commission BPS", commission_input)

        layout.addLayout(form_layout)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec() == QDialog.DialogCode.Accepted:
            payload = {
                "name": name_input.text().strip(),
                "slug": slug_input.text().strip(),
                "legal_name": legal_name_input.text().strip(),
                "contact_name": contact_name_input.text().strip(),
                "email": email_input.text().strip(),
                "phone": phone_input.text().strip(),
            }
            try:
                payload["default_commission_bps"] = int(commission_input.text().strip())
            except ValueError:
                pass

            def operation() -> object:
                return client.update_vendor(token, vendor_id, payload)

            def completed(value: object) -> None:
                marketplace_message.setText("Vendor updated successfully.")
                QTimer.singleShot(0, refresh_marketplace)

            start_session_api_task(
                marketplace_message,
                operation,
                on_result=completed,
                controls=(marketplace_vendor_edit_button,),
            )

    def reset_vendor_user_password() -> None:
        token = current_token()
        vendor_id = selected_vendor_id()
        if not token or not vendor_id:
            marketplace_message.setText("Select a vendor first.")
            return

        user_list = []
        for i in range(marketplace_vendor_users_table.rowCount()):
            uid_item = marketplace_vendor_users_table.item(i, 0)
            uname_item = marketplace_vendor_users_table.item(i, 1)
            if uid_item and uname_item:
                user_list.append((uid_item.text().strip(), uname_item.text().strip()))

        if not user_list:
            marketplace_message.setText("No linked users found for this vendor.")
            return

        from PySide6.QtWidgets import (
            QComboBox,
            QDialog,
            QDialogButtonBox,
            QFormLayout,
            QLineEdit,
            QVBoxLayout,
        )

        dialog = QDialog()
        dialog.setWindowTitle("Reset User Password")
        dialog.resize(350, 150)
        layout = QVBoxLayout(dialog)
        form_layout = QFormLayout()

        user_combo = QComboBox()
        for uid, uname in user_list:
            user_combo.addItem(f"{uname} ({uid})", userData=uid)

        password_input = QLineEdit()
        password_input.setEchoMode(QLineEdit.EchoMode.Password)
        password_input.setPlaceholderText("Enter new temporary password")

        form_layout.addRow("User", user_combo)
        form_layout.addRow("New Password", password_input)
        layout.addLayout(form_layout)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec() == QDialog.DialogCode.Accepted:
            selected_uid = user_combo.currentData()
            new_password = password_input.text()
            if not new_password:
                marketplace_message.setText("Password cannot be empty.")
                return

            def operation() -> object:
                return client.reset_user_password(token, selected_uid, new_password)

            def completed(value: object) -> None:
                marketplace_message.setText("Password reset successfully.")

            start_session_api_task(
                marketplace_message,
                operation,
                on_result=completed,
                controls=(marketplace_vendor_reset_password_button,),
            )

    def selected_vendor_id() -> str | None:
        row = marketplace_vendor_table.currentRow()
        item = marketplace_vendor_table.item(row, 0) if row >= 0 else None
        return item.text().strip() if item and item.text().strip() else None

    def load_selected_vendor_workspace() -> None:
        nonlocal marketplace_orders_offset, marketplace_orders_limit
        token = current_token()
        vendor_id = selected_vendor_id()
        if not token or not vendor_id:
            return
        permissions = set(state.get("permissions") or [])
        date_from = marketplace_date_from_input.text().strip() or None
        date_to = marketplace_date_to_input.text().strip() or None
        order_status = marketplace_order_status_filter.text().strip() or None
        payment_status = marketplace_payment_status_filter.text().strip() or None
        settlement_status = marketplace_settlement_status_filter.text().strip() or None

        def operation() -> object:
            vendor = client.get_vendor(token, vendor_id)
            ledger_access = "ledger.view" in permissions
            overview = (
                client.get_vendor_ledger_overview(token, vendor_id) if ledger_access else vendor
            )
            stock = client.list_vendor_stock(token, vendor_id) if ledger_access else []
            movements = (
                client.list_vendor_stock_movements(
                    token,
                    vendor_id,
                    date_from=date_from,
                    date_to=date_to,
                )
                if ledger_access
                else []
            )
            ledger_rows = (
                client.list_authoritative_vendor_ledger(
                    token,
                    vendor_id,
                    date_from=date_from,
                    date_to=date_to,
                )
                if ledger_access
                else []
            )
            products = (
                client.list_vendor_products(token, vendor_id)
                if "vendors.view" in permissions
                else []
            )
            orders = (
                client.list_vendor_orders_for_admin(
                    token,
                    vendor_id,
                    date_from=date_from,
                    date_to=date_to,
                    order_status=order_status,
                    payment_status=payment_status,
                    limit=marketplace_orders_limit,
                    offset=marketplace_orders_offset,
                )
                if "vendors.orders.view" in permissions
                else []
            )
            settlements = (
                client.list_vendor_settlements_for_admin(
                    token,
                    vendor_id,
                    date_from=date_from,
                    date_to=date_to,
                    status=settlement_status,
                )
                if "vendors.orders.view" in permissions
                else []
            )
            linked_users = (
                client.list_vendor_users_for_admin(token, vendor_id)
                if "vendors.users.manage" in permissions
                else []
            )
            company_users = (
                client.list_users(token)
                if linked_users and "identity.view_users" in permissions
                else []
            )
            users_by_id = {str(row.get("id")): row for row in company_users}
            linked_user_rows = []
            for link in linked_users:
                user = users_by_id.get(str(link.get("user_id")), {})
                linked_user_rows.append(
                    {
                        **link,
                        "username": user.get("username", ""),
                        "account_status": user.get("account_status", "unknown"),
                    }
                )
            audit_rows = (
                client.list_vendor_audit_for_admin(token, vendor_id) if ledger_access else []
            )
            return {
                "overview": overview,
                "stock": stock,
                "movements": movements,
                "ledger": ledger_rows,
                "products": products,
                "orders": orders,
                "settlements": settlements,
                "users": linked_user_rows,
                "audit": audit_rows,
            }

        def completed(value: object) -> None:
            result = value if isinstance(value, dict) else {}
            overview_value = result.get("overview")
            overview = overview_value if isinstance(overview_value, dict) else {}
            stock_value = result.get("stock")
            stock = stock_value if isinstance(stock_value, list) else []
            movements_value = result.get("movements")
            movements = movements_value if isinstance(movements_value, list) else []
            ledger_value = result.get("ledger")
            ledger_rows = ledger_value if isinstance(ledger_value, list) else []
            products_value = result.get("products")
            products = products_value if isinstance(products_value, list) else []
            orders_value = result.get("orders")
            orders = orders_value if isinstance(orders_value, list) else []
            settlements_value = result.get("settlements")
            settlements = settlements_value if isinstance(settlements_value, list) else []
            users_value = result.get("users")
            linked_user_rows = users_value if isinstance(users_value, list) else []
            audit_value = result.get("audit")
            audit_rows = audit_value if isinstance(audit_value, list) else []
            marketplace_vendor_overview_text.setPlainText(
                "\n".join(
                    f"{key.replace('_', ' ').title()}: {value}" for key, value in overview.items()
                )
            )
            populate_table(
                marketplace_vendor_stock_table,
                stock,
                [
                    ("product_id", "Product"),
                    ("warehouse_id", "Warehouse"),
                    ("ownership_type", "Ownership"),
                    ("on_hand_quantity", "On Hand"),
                    ("reserved_quantity", "Reserved"),
                    ("available_quantity", "Available"),
                ],
            )
            populate_table(
                marketplace_vendor_movement_table,
                movements,
                [
                    ("occurred_at", "When"),
                    ("movement_type", "Type"),
                    ("product_id", "Product"),
                    ("quantity_delta", "Quantity"),
                    ("quantity_before", "Before"),
                    ("quantity_after", "After"),
                    ("reason", "Reason"),
                ],
            )
            populate_table(
                marketplace_vendor_financial_table,
                ledger_rows,
                [
                    ("posted_at", "When"),
                    ("entry_number", "Entry"),
                    ("source_type", "Source"),
                    ("debit_minor", "Debit"),
                    ("credit_minor", "Credit"),
                    ("balance_minor", "Balance"),
                ],
            )
            populate_table(
                marketplace_current_products_table,
                products,
                marketplace_current_products_columns,
            )
            populate_table(
                marketplace_current_orders_table,
                orders,
                marketplace_current_orders_columns,
            )
            populate_table(
                marketplace_current_settlements_table,
                settlements,
                marketplace_current_settlements_columns,
            )
            populate_table(
                marketplace_vendor_users_table,
                linked_user_rows,
                [
                    ("user_id", "User ID"),
                    ("username", "Username"),
                    ("role_name", "Role"),
                    ("account_status", "Account Status"),
                    ("is_primary", "Primary"),
                ],
            )
            populate_table(
                marketplace_vendor_audit_table,
                audit_rows,
                [
                    ("created_at", "When"),
                    ("action", "Action"),
                    ("entity_type", "Entity"),
                    ("user_id", "Actor"),
                    ("metadata", "Details"),
                ],
            )
            marketplace_vendor_reports_text.setPlainText(
                "\n".join(
                    [
                        f"Date from: {date_from or 'all'}",
                        f"Date to: {date_to or 'all'}",
                        f"Filtered orders: {len(orders)}",
                        "Filtered gross sales: "
                        f"{sum(int(row.get('line_total_minor') or 0) for row in orders)}",
                        "Filtered commission: "
                        f"{sum(int(row.get('commission_minor') or 0) for row in orders)}",
                        "Filtered payable: "
                        f"{sum(int(row.get('payable_minor') or 0) for row in orders)}",
                        f"Filtered settlements: {len(settlements)}",
                        "Filtered settlement paid: "
                        f"{sum(int(row.get('paid_minor') or 0) for row in settlements)}",
                        f"Stock records: {len(stock)}",
                        f"Stock movements: {len(movements)}",
                    ]
                )
            )
            marketplace_vendor_status_action.setCurrentText(
                str(
                    overview.get("vendor_access_status")
                    or overview.get("access_status")
                    or overview.get("vendor_status")
                    or "active"
                )
            )

        start_session_api_task(
            marketplace_message,
            operation,
            on_result=completed,
            controls=(marketplace_apply_filters_button,),
        )

    def apply_vendor_status() -> None:
        token = current_token()
        vendor_id = selected_vendor_id()
        if not token or not vendor_id:
            marketplace_message.setText("Select a vendor first.")
            return

        selected_status = marketplace_vendor_status_action.currentText()

        def operation() -> object:
            return client.change_vendor_status(
                token,
                vendor_id,
                selected_status,
                "Changed from desktop vendor workspace",
            )

        def completed(_value: object) -> None:
            marketplace_message.setText(f"Vendor access changed to {selected_status}.")
            QTimer.singleShot(0, refresh_marketplace)

        start_session_api_task(
            marketplace_message,
            operation,
            on_result=completed,
            controls=(marketplace_vendor_status_button,),
        )

    def apply_vendor_lifecycle(lifecycle: str) -> None:
        token = current_token()
        vendor_id = selected_vendor_id()
        if not token or not vendor_id:
            marketplace_message.setText("Select a vendor first.")
            return
        reason, accepted = QInputDialog.getText(
            window,
            f"{lifecycle.title()} vendor",
            "Reason (optional):",
        )
        if not accepted:
            return

        def operation() -> object:
            if lifecycle == "approve":
                return client.approve_vendor(token, vendor_id)
            if lifecycle == "pause":
                return client.pause_vendor(token, vendor_id, reason or None)
            if lifecycle == "reactivate":
                return client.reactivate_vendor(token, vendor_id, reason or None)
            if lifecycle == "stop":
                return client.stop_vendor(token, vendor_id, reason or None)
            raise ValueError("Unsupported vendor lifecycle action.")

        def completed(value: object) -> None:
            result = value if isinstance(value, dict) else {}
            marketplace_vendor_status_action.setCurrentText(
                str(result.get("access_status") or result.get("status") or "active")
            )
            marketplace_message.setText(f"Vendor {lifecycle} action completed.")
            QTimer.singleShot(0, refresh_marketplace)

        lifecycle_controls = {
            "approve": marketplace_vendor_approve_button,
            "pause": marketplace_vendor_pause_button,
            "reactivate": marketplace_vendor_reactivate_button,
            "stop": marketplace_vendor_stop_button,
        }
        start_session_api_task(
            marketplace_message,
            operation,
            on_result=completed,
            controls=(lifecycle_controls[lifecycle],),
        )

    def refresh_accounting() -> None:
        token = current_token()
        if not token:
            accounting_message.setText("Login required.")
            return

        def action() -> None:
            permissions = set(state.get("permissions") or [])
            date_from = ledger_date_from_input.text().strip() or None
            date_to = ledger_date_to_input.text().strip() or None
            if "ledger.view" not in permissions and "vendor.ledger.view" in permissions:
                overview = client.get_vendor_ledger_overview(token)
                own_ledger = client.list_authoritative_vendor_ledger(
                    token, date_from=date_from, date_to=date_to
                )
                own_stock = client.list_vendor_stock(token)
                populate_table(ledger_journal_table, own_ledger, ledger_journal_columns)
                ledger_account_table.setRowCount(0)
                ledger_trial_table.setRowCount(0)
                ledger_vendor_payables_table.setRowCount(0)
                populate_table(
                    ledger_inventory_table,
                    own_stock,
                    [
                        ("vendor_id", "Vendor"),
                        ("product_id", "Product"),
                        ("warehouse_id", "Warehouse"),
                        ("ownership_type", "Ownership"),
                        ("on_hand_quantity", "On Hand"),
                        ("reserved_quantity", "Reserved"),
                        ("available_quantity", "Available"),
                    ],
                )
                ledger_reconciliation_table.setRowCount(0)
                ledger_profit_loss_text.setPlainText(
                    "Company profit/loss is not available to vendors."
                )
                ledger_balance_sheet_text.setPlainText(
                    "Company balance sheet is not available to vendors."
                )
                ledger_cash_flow_text.setPlainText("Company cash flow is not available to vendors.")
                ledger_control_summary.setPlainText(
                    "\n".join(
                        [
                            f"Vendor: {overview.get('vendor_id', '')}",
                            f"Gross sales: {overview.get('gross_sales_minor', 0)}",
                            f"Commission: {overview.get('commission_minor', 0)}",
                            f"Outstanding payable: {overview.get('outstanding_minor', 0)}",
                            f"Settled: {overview.get('settled_minor', 0)}",
                            f"Stock records: {len(own_stock)}",
                        ]
                    )
                )
                accounting_summary.setPlainText("Vendor financial ledger (read-only)")
                accounting_message.setText("Vendor ledger loaded.")
                return
            accounts = client.list_accounts(token)
            periods = client.list_periods(token)
            journals = client.list_journal_entries(token)
            ledger = client.list_vendor_ledger_entries(token)
            cash_books = client.list_cash_books(token)
            bank_accounts = client.list_bank_accounts(token)
            expenses = client.list_expenses(token)
            ledger_overview = client.get_ledger_overview(token)
            ledger_accounts = client.list_ledger_accounts(token)
            ledger_journals = client.list_ledger_journals(
                token,
                ledger_vendor_filter_input.text().strip() or None,
                account_id=ledger_account_filter_input.text().strip() or None,
                source_type=ledger_source_filter_input.text().strip() or None,
                status=ledger_status_filter_input.text().strip() or None,
                date_from=date_from,
                date_to=date_to,
            )
            trial_balance = client.get_trial_balance(token, date_from=date_from, date_to=date_to)
            profit_loss = client.get_profit_loss(token, date_from=date_from, date_to=date_to)
            balance_sheet = client.get_balance_sheet(token, date_to=date_to)
            cash_flow = client.get_cash_flow(token, date_from=date_from, date_to=date_to)
            vendor_payables = client.get_vendor_payables(token, as_of=date_to)
            inventory_report = client.get_ledger_inventory_report(
                token, vendor_id=ledger_vendor_filter_input.text().strip() or None
            )
            reconciliation = client.get_reconciliation(token)
            populate_table(accounting_account_table, accounts, accounting_account_columns)
            populate_table(accounting_period_table, periods, accounting_period_columns)
            populate_table(accounting_journal_table, journals, accounting_journal_columns)
            populate_table(
                accounting_vendor_ledger_table,
                ledger,
                accounting_vendor_ledger_columns,
            )
            populate_table(accounting_cash_table, cash_books, accounting_cash_columns)
            populate_table(accounting_bank_table, bank_accounts, accounting_bank_columns)
            populate_table(accounting_expense_table, expenses, accounting_expense_columns)
            populate_table(ledger_account_table, ledger_accounts, ledger_account_columns)
            populate_table(ledger_journal_table, ledger_journals, ledger_journal_columns)
            populate_table(ledger_trial_table, trial_balance, ledger_trial_columns)
            populate_table(
                ledger_vendor_payables_table,
                vendor_payables,
                [
                    ("vendor_id", "Vendor"),
                    ("vendor_name", "Name"),
                    ("status", "Status"),
                    ("order_count", "Orders"),
                    ("gross_sales_minor", "Gross Sales"),
                    ("current_minor", "Current"),
                    ("days_31_60_minor", "31-60"),
                    ("days_61_90_minor", "61-90"),
                    ("days_over_90_minor", "90+"),
                    ("outstanding_minor", "Outstanding"),
                ],
            )
            populate_table(
                ledger_inventory_table,
                inventory_report,
                [
                    ("vendor_id", "Vendor"),
                    ("product_id", "Product"),
                    ("warehouse_id", "Warehouse"),
                    ("ownership_type", "Ownership"),
                    ("on_hand_quantity", "On Hand"),
                    ("reserved_quantity", "Reserved"),
                    ("available_quantity", "Available"),
                ],
            )
            populate_table(
                ledger_reconciliation_table,
                reconciliation,
                [
                    ("severity", "Severity"),
                    ("issue_type", "Issue"),
                    ("vendor_id", "Vendor"),
                    ("source_id", "Source"),
                    ("expected_minor", "Expected"),
                    ("actual_minor", "Actual"),
                    ("detail", "Detail"),
                ],
            )
            ledger_profit_loss_text.setPlainText(jsonlib.dumps(profit_loss, indent=2, default=str))
            ledger_balance_sheet_text.setPlainText(
                jsonlib.dumps(balance_sheet, indent=2, default=str)
            )
            ledger_cash_flow_text.setPlainText(jsonlib.dumps(cash_flow, indent=2, default=str))
            accounting_summary.setPlainText(
                "\n".join(
                    [
                        f"Accounts: {len(accounts)}",
                        f"Periods: {len(periods)}",
                        f"Journal entries: {len(journals)}",
                        f"Vendor ledger rows: {len(ledger)}",
                        f"Cash books: {len(cash_books)}",
                        f"Bank accounts: {len(bank_accounts)}",
                        f"Expenses: {len(expenses)}",
                    ]
                )
            )
            ledger_control_summary.setPlainText(
                "\n".join(
                    [
                        f"Assets: {ledger_overview.get('assets_minor', 0)}",
                        f"Liabilities: {ledger_overview.get('liabilities_minor', 0)}",
                        f"Vendor payables: {ledger_overview.get('vendor_payables_minor', 0)}",
                        f"Cash / bank: {ledger_overview.get('cash_balance_minor', 0)}",
                        f"Income: {ledger_overview.get('income_minor', 0)}",
                        f"Expenses: {ledger_overview.get('expenses_minor', 0)}",
                        f"Profit: {profit_loss.get('profit_minor', 0)}",
                        f"Vendors: {ledger_overview.get('vendor_count', 0)}",
                        f"Orders: {ledger_overview.get('order_count', 0)}",
                        f"Gross order value: {ledger_overview.get('gross_order_minor', 0)}",
                        f"Paid sales: {ledger_overview.get('paid_sales_minor', 0)}",
                        f"Commission: {ledger_overview.get('commission_minor', 0)}",
                        f"Settlements: {ledger_overview.get('settlement_count', 0)}",
                        f"Settlements paid: {ledger_overview.get('settlement_paid_minor', 0)}",
                        f"Inventory units: {ledger_overview.get('inventory_on_hand', 0)}",
                        f"Inventory value: {ledger_overview.get('inventory_value_minor', 0)}",
                        f"Balance sheet total: {balance_sheet.get('total_minor', 0)}",
                        f"Reconciliation warnings: {len(reconciliation)}",
                    ]
                )
            )
            accounting_message.setText("Accounting loaded.")
            set_status("Accounting loaded.", ok=True)

        guarded(accounting_message, action)

    def create_account() -> None:
        token = current_token()
        if not token:
            accounting_message.setText("Login required.")
            return
        code = accounting_account_code_input.text().strip()
        name = accounting_account_name_input.text().strip()
        account_type = accounting_account_type_input.text().strip()
        if not code or not name or not account_type:
            accounting_message.setText("Code, name, and type are required.")
            return
        payload: dict[str, object] = {
            "code": code,
            "name": name,
            "account_type": account_type,
        }
        parent_id = accounting_account_parent_input.text().strip()
        if parent_id:
            payload["parent_id"] = parent_id
        active_text = accounting_account_active_input.text().strip().lower()
        if active_text:
            payload["is_active"] = active_text not in {"false", "0", "no"}

        def action() -> None:
            client.create_account(token, payload)
            accounting_account_code_input.clear()
            accounting_account_name_input.clear()
            accounting_account_type_input.clear()
            accounting_account_parent_input.clear()
            accounting_account_active_input.setText("true")
            refresh_accounting()

        guarded(accounting_message, action)

    def create_cash_book() -> None:
        token = current_token()
        if not token:
            accounting_message.setText("Login required.")
            return
        code = accounting_cash_code_input.text().strip()
        name = accounting_cash_name_input.text().strip()
        if not code or not name:
            accounting_message.setText("Cash book code and name are required.")
            return
        opening_text = accounting_cash_opening_input.text().strip() or "0"
        try:
            opening_balance = int(opening_text)
        except ValueError:
            accounting_message.setText("Cash opening balance must be a number.")
            return
        payload: dict[str, object] = {
            "code": code,
            "name": name,
            "currency": accounting_cash_currency_input.text().strip() or "PKR",
            "opening_balance_minor": opening_balance,
        }

        def action() -> None:
            client.create_cash_book(token, payload)
            accounting_cash_code_input.clear()
            accounting_cash_name_input.clear()
            accounting_cash_currency_input.setText("PKR")
            accounting_cash_opening_input.setText("0")
            refresh_accounting()

        guarded(accounting_message, action)

    def create_bank_account() -> None:
        token = current_token()
        if not token:
            accounting_message.setText("Login required.")
            return
        code = accounting_bank_code_input.text().strip()
        bank_name = accounting_bank_name_input.text().strip()
        account_name = accounting_bank_account_name_input.text().strip()
        if not code or not bank_name or not account_name:
            accounting_message.setText("Bank code, bank name, and account name are required.")
            return
        payload: dict[str, object] = {
            "code": code,
            "bank_name": bank_name,
            "account_name": account_name,
            "currency": accounting_bank_currency_input.text().strip() or "PKR",
        }
        account_number = accounting_bank_account_number_input.text().strip()
        iban = accounting_bank_iban_input.text().strip()
        if account_number:
            payload["account_number"] = account_number
        if iban:
            payload["iban"] = iban

        def action() -> None:
            client.create_bank_account(token, payload)
            accounting_bank_code_input.clear()
            accounting_bank_name_input.clear()
            accounting_bank_account_name_input.clear()
            accounting_bank_account_number_input.clear()
            accounting_bank_iban_input.clear()
            accounting_bank_currency_input.setText("PKR")
            refresh_accounting()

        guarded(accounting_message, action)

    def refresh_settings() -> None:
        if refresh_api_health_status():
            try:
                module_names = [
                    str(item.get("name", item.get("id"))) for item in client.get_modules()
                ]
                modules_text.setPlainText("\n".join(module_names))
                settings_message.setText("API status loaded.")
            except Exception as exc:
                settings_message.setText(f"Module list unavailable: {exc}")
        else:
            settings_message.setText(
                "Offline warning: API-backed screens are read-only/unavailable."
            )
            modules_text.setPlainText("")

    def comma_separated(value: str) -> list[str]:
        return [item.strip() for item in value.split(",") if item.strip()]

    def selected_admin_role_ids() -> list[str]:
        role_ids: list[str] = []
        for item in admin_user_roles_input.selectedItems():
            role_id = str(item.data(Qt.ItemDataRole.UserRole) or "").strip()
            if role_id:
                role_ids.append(role_id)
        return role_ids

    def refresh_admin() -> None:
        token = current_token()
        if not token:
            admin_message.setText("Login required.")
            return
        if not admin_refresh_button.isEnabled():
            return

        def operation() -> object:
            return {
                "companies": client.list_companies(token),
                "users": client.list_users(token),
                "roles": client.list_roles(token),
                "license": client.get_license_status(token),
                "diagnostics": client.get_diagnostics_summary(token),
            }

        def completed(value: object) -> None:
            result = value if isinstance(value, dict) else {}
            companies = result.get("companies")
            companies = companies if isinstance(companies, list) else []
            users = result.get("users")
            users = users if isinstance(users, list) else []
            roles = result.get("roles")
            roles = roles if isinstance(roles, list) else []
            license_value = result.get("license")
            license_status = license_value if isinstance(license_value, dict) else {}
            diagnostics_value = result.get("diagnostics")
            diagnostics = diagnostics_value if isinstance(diagnostics_value, dict) else {}
            populate_table(company_table, companies, company_columns)
            populate_table(user_table, users, user_columns)
            populate_table(role_table, roles, role_columns)
            state["admin_users"] = users
            state["admin_roles"] = roles
            admin_user_roles_input.clear()
            for role in roles:
                admin_user_roles_input.addItem(str(role.get("name") or "Unnamed role"))
                role_item = admin_user_roles_input.item(admin_user_roles_input.count() - 1)
                role_item.setData(Qt.ItemDataRole.UserRole, str(role.get("id") or ""))
            if companies and not company_id_input.text().strip():
                company_id_input.setText(str(companies[0].get("id") or ""))
                company_name_input.setText(str(companies[0].get("name") or ""))
                company_legal_name_input.setText(str(companies[0].get("legal_name") or ""))
                company_status_input.setText(str(companies[0].get("status") or ""))
            admin_summary.setPlainText(
                "\n".join(
                    [
                        f"License: {license_status.get('status', 'unknown')}",
                        f"Plan: {license_status.get('plan') or 'not configured'}",
                        f"Diagnostics version: {diagnostics.get('app_version', 'unknown')}",
                        f"Migration: {diagnostics.get('migration_revision') or 'not migrated'}",
                        f"Modules: {diagnostics.get('module_count', 0)}",
                    ]
                )
            )
            admin_message.setText("Admin data loaded.")
            set_status("Admin data loaded.", ok=True)

        start_session_api_task(
            admin_message,
            operation,
            on_result=completed,
            controls=(admin_refresh_button,),
        )

    def update_admin_company() -> None:
        token = current_token()
        if not token:
            admin_message.setText("Login required.")
            return
        company_id = company_id_input.text().strip()
        if not company_id:
            admin_message.setText("Company ID is required.")
            return
        payload: dict[str, object] = {}
        name = company_name_input.text().strip()
        legal_name = company_legal_name_input.text().strip()
        status = company_status_input.text().strip()
        if name:
            payload["name"] = name
        if legal_name:
            payload["legal_name"] = legal_name
        if status:
            payload["status"] = status
        if not payload:
            admin_message.setText("At least one company field is required.")
            return

        def operation() -> object:
            return client.update_company(token, company_id, payload)

        start_session_api_task(
            admin_message,
            operation,
            on_result=lambda _value: refresh_admin(),
            controls=(company_update_button,),
        )

    def create_admin_user() -> None:
        token = current_token()
        if not token:
            admin_message.setText("Login required.")
            return
        username = admin_username_input.text().strip()
        password = admin_password_input.text()
        if not username or not password:
            admin_message.setText("Username and password are required.")
            return
        payload: dict[str, object] = {
            "username": username,
            "password": password,
            "role_ids": selected_admin_role_ids(),
            "account_status": admin_user_status_input.currentText(),
            "must_change_password": admin_user_must_change_input.isChecked(),
        }
        email = admin_user_email_input.text().strip()
        full_name = admin_user_full_name_input.text().strip()
        if email:
            payload["email"] = email
        if full_name:
            payload["full_name"] = full_name
        admin_password_input.clear()

        def operation() -> object:
            return client.create_user(token, payload)

        def completed(_value: object) -> None:
            admin_username_input.clear()
            admin_user_email_input.clear()
            admin_user_full_name_input.clear()
            admin_user_roles_input.clearSelection()
            admin_user_status_input.setCurrentText("active")
            admin_user_must_change_input.setChecked(False)
            refresh_admin()

        start_session_api_task(
            admin_message,
            operation,
            on_result=completed,
            controls=(admin_create_user_button,),
        )

    def load_selected_admin_user() -> None:
        row = user_table.currentRow()
        user_id_item = user_table.item(row, 0) if row >= 0 else None
        status_item = user_table.item(row, 4) if row >= 0 else None
        if user_id_item:
            admin_user_id_input.setText(user_id_item.text())
        if status_item and status_item.text() in {"active", "pending", "paused", "stopped"}:
            admin_user_status_input.setCurrentText(status_item.text())
        selected_user = next(
            (
                value
                for value in state.get("admin_users", [])
                if isinstance(value, dict)
                and str(value.get("id") or "") == (user_id_item.text() if user_id_item else "")
            ),
            None,
        )
        selected_role_ids = (
            {str(value) for value in selected_user.get("role_ids", [])}
            if isinstance(selected_user, dict) and isinstance(selected_user.get("role_ids"), list)
            else set()
        )
        for index in range(admin_user_roles_input.count()):
            role_item = admin_user_roles_input.item(index)
            role_item.setSelected(
                str(role_item.data(Qt.ItemDataRole.UserRole) or "") in selected_role_ids
            )
        admin_user_must_change_input.setChecked(
            bool(selected_user.get("must_change_password"))
            if isinstance(selected_user, dict)
            else False
        )

    def apply_admin_user_status() -> None:
        token = current_token()
        if not token:
            admin_message.setText("Login required.")
            return
        user_id = admin_user_id_input.text().strip()
        if not user_id:
            admin_message.setText("Select a user or enter a user ID first.")
            return

        update_payload: dict[str, object] = {
            "account_status": admin_user_status_input.currentText(),
            "role_ids": selected_admin_role_ids(),
            "must_change_password": admin_user_must_change_input.isChecked(),
        }

        def operation() -> object:
            return client.update_user(
                token,
                user_id,
                update_payload,
            )

        start_session_api_task(
            admin_message,
            operation,
            on_result=lambda _value: refresh_admin(),
            controls=(admin_apply_user_status_button,),
        )

    def reset_admin_password() -> None:
        token = current_token()
        if not token:
            admin_message.setText("Login required.")
            return
        user_id = admin_user_id_input.text().strip()
        password = admin_password_input.text()
        if not user_id or not password:
            admin_message.setText("Reset user ID and password are required.")
            return
        admin_password_input.clear()

        def operation() -> object:
            return client.reset_user_password(token, user_id, password)

        start_session_api_task(
            admin_message,
            operation,
            on_result=lambda _value: refresh_admin(),
            controls=(admin_reset_password_button,),
        )

    def create_admin_role() -> None:
        token = current_token()
        if not token:
            admin_message.setText("Login required.")
            return
        name = admin_role_name_input.text().strip()
        if not name:
            admin_message.setText("Role name is required.")
            return
        payload: dict[str, object] = {
            "name": name,
            "description": admin_role_description_input.text().strip() or None,
            "permissions": comma_separated(admin_role_permissions_input.text()),
        }

        def operation() -> object:
            return client.create_role(token, payload)

        def completed(_value: object) -> None:
            admin_role_name_input.clear()
            admin_role_description_input.clear()
            admin_role_permissions_input.clear()
            refresh_admin()

        start_session_api_task(
            admin_message,
            operation,
            on_result=completed,
            controls=(admin_create_role_button,),
        )

    def activate_admin_license() -> None:
        token = current_token()
        if not token:
            admin_message.setText("Login required.")
            return
        license_key = admin_license_key_input.text().strip()
        plan = admin_license_plan_input.text().strip() or "standard"
        if not license_key:
            admin_message.setText("License key is required.")
            return

        def action() -> None:
            client.activate_license(token, license_key=license_key, plan=plan)
            admin_license_key_input.clear()
            refresh_admin()

        guarded(admin_message, action)

    def validate_admin_license() -> None:
        token = current_token()
        if not token:
            admin_message.setText("Login required.")
            return

        def action() -> None:
            validation = client.validate_license(token)
            admin_message.setText(str(validation.get("detail", "License validation complete.")))
            refresh_admin()

        guarded(admin_message, action)

    def revoke_admin_license() -> None:
        token = current_token()
        if not token:
            admin_message.setText("Login required.")
            return

        def action() -> None:
            client.revoke_license(token, "Revoked from desktop admin screen.")
            refresh_admin()

        guarded(admin_message, action)

    def apply_navigation_permissions(
        permissions: list[str],
        *,
        must_change_password: bool = False,
    ) -> None:
        visibility = navigation_visibility(
            permissions,
            must_change_password=must_change_password,
        )
        granted = set(permissions)
        for index in range(sidebar.count()):
            item = sidebar.item(index)
            item.setHidden(not visibility.get(item.text(), False))
        can_sync_woocommerce = bool(
            {"woocommerce.sync", "vendor.products.manage"} & granted
        ) and not must_change_password
        dashboard_sync_products_button.setVisible(can_sync_woocommerce)
        dashboard_sync_all_button.setVisible(can_sync_woocommerce)
        can_manage_vendors = "vendors.manage" in granted
        vendor_self_product_manage = "vendor.products.manage" in granted and not can_manage_vendors
        vendor_self_order_manage = "vendor.orders.manage" in granted and not can_manage_vendors
        marketplace_vendor_table.setVisible("vendors.view" in granted)
        marketplace_vendor_form.setVisible(can_manage_vendors)
        marketplace_vendor_status_action.setVisible(can_manage_vendors)
        marketplace_vendor_status_button.setVisible(can_manage_vendors)
        marketplace_vendor_product_create_button.setVisible(vendor_self_product_manage)
        marketplace_vendor_product_price_button.setVisible(vendor_self_product_manage)
        marketplace_vendor_stock_adjust_button.setVisible(
            "vendor.stock.manage" in granted and not can_manage_vendors
        )
        marketplace_vendor_order_status_action.setVisible(vendor_self_order_manage)
        marketplace_vendor_order_status_button.setVisible(vendor_self_order_manage)
        for lifecycle_button in (
            marketplace_vendor_approve_button,
            marketplace_vendor_pause_button,
            marketplace_vendor_reactivate_button,
            marketplace_vendor_stop_button,
            marketplace_vendor_edit_button,
            marketplace_vendor_reset_password_button,
        ):
            lifecycle_button.setVisible(can_manage_vendors)
        vendor_admin_view = "vendors.view" in granted
        vendor_self_view = bool(VENDOR_SELF_PERMISSIONS & granted)
        marketplace_vendor_detail_tabs.setTabVisible(
            0, vendor_admin_view or "vendor.profile.view" in granted
        )
        marketplace_vendor_detail_tabs.setTabVisible(
            1, vendor_admin_view or "vendor.stock.view" in granted
        )
        marketplace_vendor_detail_tabs.setTabVisible(
            2, vendor_admin_view or "vendor.stock.view" in granted
        )
        marketplace_vendor_detail_tabs.setTabVisible(
            3, vendor_admin_view or "vendor.products.view" in granted
        )
        marketplace_vendor_detail_tabs.setTabVisible(
            4, vendor_admin_view or "vendor.orders.view" in granted
        )
        marketplace_vendor_detail_tabs.setTabVisible(
            5, vendor_admin_view or "vendor.ledger.view" in granted
        )
        marketplace_vendor_detail_tabs.setTabVisible(
            6, vendor_admin_view or "vendor.settlements.view" in granted
        )
        marketplace_vendor_detail_tabs.setTabVisible(7, vendor_admin_view or vendor_self_view)
        marketplace_vendor_detail_tabs.setTabVisible(8, "vendors.users.manage" in granted)
        marketplace_vendor_detail_tabs.setTabVisible(9, "ledger.view" in granted)
        for filter_widget in (
            marketplace_date_from_input,
            marketplace_date_to_input,
            marketplace_order_status_filter,
            marketplace_payment_status_filter,
            marketplace_settlement_status_filter,
            marketplace_apply_filters_button,
        ):
            filter_widget.setEnabled(vendor_admin_view or vendor_self_view)
        company_accounting = "accounting.view" in granted
        for widget in (
            accounting_account_table,
            accounting_account_form,
            accounting_cash_table,
            accounting_cash_form,
            accounting_bank_table,
            accounting_bank_form,
            accounting_period_table,
            accounting_journal_table,
            accounting_vendor_ledger_table,
            accounting_expense_table,
            accounting_summary,
        ):
            widget.setVisible(company_accounting)
        ledger_export_button.setVisible("ledger.export" in granted)
        for widget in (
            ledger_vendor_filter_input,
            ledger_account_filter_input,
            ledger_source_filter_input,
            ledger_status_filter_input,
        ):
            widget.setVisible("ledger.view" in granted)
        company_form.setVisible("tenancy.manage_companies" in granted)
        user_form.setVisible("identity.manage_users" in granted)
        role_form.setVisible("identity.manage_roles" in granted)
        user_table.setVisible("identity.view_users" in granted)
        role_table.setVisible("identity.manage_roles" in granted)

    def load_session_bundle(payload: dict[str, object], *, remembered: bool) -> dict[str, object]:
        credentials = client.session_credentials()
        token = credentials.access_token
        if not token:
            raise ApiResponseError(500, "Authentication response did not create a desktop session.")
        current_session = client.get_current_session(token)
        permissions_value = current_session.get("permissions")
        permissions = (
            [str(value) for value in permissions_value]
            if isinstance(permissions_value, list)
            else []
        )
        must_change_password = bool(
            current_session.get("user", {}).get("must_change_password")
            if isinstance(current_session.get("user"), dict)
            else False
        )
        roles = role_names_for_session(current_session, permissions)
        vendor: dict[str, object] | None = None
        if should_load_vendor_self(roles, permissions) and not must_change_password:
            vendor = client.get_current_vendor(token)
            roles = role_names_for_session(current_session, permissions, vendor)
        auth_details = {
            key: payload.get(key)
            for key in (
                "expires_at",
                "refresh_expires_at",
                "session_id",
            )
        }
        return {
            "auth": auth_details,
            "current": current_session,
            "vendor": vendor,
            "permissions": permissions,
            "roles": roles,
            "remembered": remembered,
            "generation": credentials.generation,
        }

    def accept_session(bundle: dict[str, object]) -> None:
        credentials = client.session_credentials()
        current_session = bundle.get("current")
        if not isinstance(current_session, dict) or not credentials.access_token:
            raise ApiResponseError(500, "The authenticated session could not be loaded.")
        auth_details = bundle.get("auth")
        if not isinstance(auth_details, dict):
            auth_details = {}
        permissions_value = bundle.get("permissions")
        permissions = (
            [str(value) for value in permissions_value]
            if isinstance(permissions_value, list)
            else []
        )
        roles_value = bundle.get("roles")
        roles = [str(value) for value in roles_value] if isinstance(roles_value, list) else []
        vendor_value = bundle.get("vendor")
        vendor = vendor_value if isinstance(vendor_value, dict) else None
        user_value = current_session.get("user")
        user = user_value if isinstance(user_value, dict) else {}
        remembered = bool(bundle.get("remembered"))
        state["token"] = credentials.access_token
        state["refresh_token"] = credentials.refresh_token
        state["remembered"] = remembered
        state["session_payload"] = auth_details
        state["current_session"] = current_session
        state["current_vendor"] = vendor
        state["username"] = str(user.get("username") or "user")
        state["permissions"] = permissions
        state["roles"] = roles
        must_change_password = bool(user.get("must_change_password"))
        apply_navigation_permissions(
            permissions,
            must_change_password=must_change_password,
        )
        session_label.setText(
            "\n".join(
                session_display_lines(
                    auth_details,
                    current_session,
                    remembered=remembered,
                    roles=roles,
                    vendor=vendor,
                )
            )
        )
        preferences.setValue(
            DESKTOP_PREFERENCE_KEYS["username"],
            str(user.get("username") or username_input.text().strip()),
        )
        preferences.setValue(
            DESKTOP_PREFERENCE_KEYS["workspace"],
            workspace_input.text().strip(),
        )
        preferences.sync()
        password_input.clear()
        login_status_label.clear()
        if must_change_password:
            screen_stack.setCurrentWidget(password_change_page)
            current_password_input.setFocus()
            return
        screen_stack.setCurrentWidget(root)
        for index in range(sidebar.count()):
            if not sidebar.item(index).isHidden():
                sidebar.setCurrentRow(index)
                break
        set_status(f"Signed in as {state['username']}.", ok=True)
        refresh_marketplace()

    def clear_ui_session(message: str) -> None:
        state["token"] = None
        state["refresh_token"] = None
        state["username"] = None
        state["permissions"] = []
        state["roles"] = []
        state["remembered"] = False
        state["session_payload"] = {}
        state["current_session"] = {}
        state["current_vendor"] = None
        apply_navigation_permissions([])
        session_label.setText("Not signed in")
        current_password_input.clear()
        new_password_input.clear()
        confirm_password_input.clear()
        password_change_message.clear()
        screen_stack.setCurrentWidget(auth_page)
        login_status_label.setText(message)

    def start_auth_task(
        operation: Callable[[], object],
        *,
        on_result: Callable[[object], None],
        on_error: Callable[[BaseException], None],
    ) -> bool:
        if bool(state.get("auth_busy")):
            return False
        state["auth_busy"] = True
        state["auth_epoch"] = int(state.get("auth_epoch") or 0) + 1
        epoch = int(state["auth_epoch"])
        login_button.setEnabled(False)
        password_change_button.setEnabled(False)

        def result(value: object) -> None:
            if int(state.get("auth_epoch") or 0) == epoch:
                on_result(value)

        def error(exc: BaseException) -> None:
            if int(state.get("auth_epoch") or 0) == epoch:
                on_error(exc)

        def finished() -> None:
            if int(state.get("auth_epoch") or 0) == epoch:
                state["auth_busy"] = False
                login_button.setEnabled(True)
                password_change_button.setEnabled(True)

        task_runner.start(
            operation,
            on_result=result,
            on_error=error,
            on_finished=finished,
        )
        return True

    def login() -> None:
        username = username_input.text().strip()
        password = password_input.text()
        workspace_slug = workspace_input.text().strip() or None
        remembered = remember_input.isChecked() and remember_input.isEnabled()
        if not username or not password or not workspace_slug:
            login_status_label.setText("Login ID, password, and workspace are required.")
            return
        password_input.clear()
        login_status_label.setText("Signing in securely...")

        def operation() -> object:
            payload = client.login(
                username,
                password,
                workspace_slug=workspace_slug,
                remember_me=remembered,
            )
            client.install_session(payload, remembered=remembered)
            try:
                return load_session_bundle(payload, remembered=remembered)
            except Exception:
                client.logout_current_session()
                raise

        def failed(exc: BaseException) -> None:
            if isinstance(exc, CredentialStorageError):
                login_status_label.setText(
                    "Remember Me could not be enabled securely; the server session was revoked."
                )
            elif isinstance(exc, ApiResponseError):
                login_status_label.setText(safe_login_error(exc.status_code))
            else:
                login_status_label.setText("Unable to sign in. Please try again.")

        start_auth_task(operation, on_result=lambda value: accept_session(value), on_error=failed)

    def refresh_desktop_session() -> None:
        if bool(state.get("refresh_busy")) or not client.refresh_token:
            return
        epoch = int(state.get("auth_epoch") or 0)
        state["refresh_busy"] = True

        def operation() -> object:
            payload = client.refresh_current_session()
            return load_session_bundle(payload, remembered=client.remembered)

        def result(value: object) -> None:
            if int(state.get("auth_epoch") or 0) == epoch and isinstance(value, dict):
                accept_session(value)

        def failed(_exc: BaseException) -> None:
            if int(state.get("auth_epoch") or 0) == epoch:
                clear_ui_session("Your saved session expired. Sign in again.")

        def finished() -> None:
            if int(state.get("auth_epoch") or 0) == epoch:
                state["refresh_busy"] = False

        task_runner.start(
            operation,
            on_result=result,
            on_error=failed,
            on_finished=finished,
        )

    def restore_saved_session() -> None:
        if not client.secure_storage_available():
            clear_ui_session("Sign in to continue. Secure remembered login is unavailable.")
            return
        login_status_label.setText("Restoring saved login securely...")

        def operation() -> object:
            payload = client.restore_saved_session()
            if payload is None:
                return None
            return load_session_bundle(payload, remembered=True)

        def restored(value: object) -> None:
            if isinstance(value, dict):
                accept_session(value)
                set_status("Saved login restored securely.", ok=True)
            else:
                clear_ui_session("Sign in to continue.")

        def failed(_exc: BaseException) -> None:
            clear_ui_session("The saved login is invalid or expired. Sign in again.")

        start_auth_task(operation, on_result=restored, on_error=failed)

    def logout() -> None:
        clear_ui_session("Signing out securely...")

        def operation() -> object:
            return client.logout_current_session()

        def completed(value: object) -> None:
            warning = getattr(value, "warning", None)
            if warning:
                login_status_label.setText(f"Signed out locally. {warning}")
            else:
                login_status_label.setText("Signed out. Saved credentials were removed.")

        def failed(_exc: BaseException) -> None:
            login_status_label.setText(
                "Signed out locally. Server revocation could not be confirmed."
            )

        start_auth_task(operation, on_result=completed, on_error=failed)

    def change_required_password() -> None:
        current_password = current_password_input.text()
        new_password = new_password_input.text()
        confirmation = confirm_password_input.text()
        if not current_password or len(new_password) < 8:
            password_change_message.setText(
                "Current password and a new password of at least 8 characters are required."
            )
            return
        if new_password != confirmation:
            password_change_message.setText("New-password confirmation does not match.")
            return
        current_password_input.clear()
        new_password_input.clear()
        confirm_password_input.clear()
        password_change_message.setText("Changing password securely...")

        def operation() -> object:
            token = client.access_token
            if not token:
                raise ApiResponseError(401, "The desktop session has expired.")
            client.change_password(
                token,
                current_password=current_password,
                new_password=new_password,
            )
            auth_details = state.get("session_payload")
            payload = auth_details if isinstance(auth_details, dict) else {}
            return load_session_bundle(payload, remembered=client.remembered)

        def completed(value: object) -> None:
            if isinstance(value, dict):
                accept_session(value)
                set_status("Password changed. Your permitted modules are now available.", ok=True)

        def failed(_exc: BaseException) -> None:
            password_change_message.setText(
                "Password could not be changed. Verify the current password and try again."
            )

        start_auth_task(operation, on_result=completed, on_error=failed)

    def open_public_auth_page(route: str) -> None:
        try:
            url = public_auth_url(client.base_url, route, workspace_input.text())
        except ValueError:
            login_status_label.setText("The configured public authentication URL is invalid.")
            return
        if not QDesktopServices.openUrl(QUrl(url)):
            login_status_label.setText("The system browser could not be opened.")

    def apply_vendor_filters() -> None:
        if selected_vendor_id():
            load_selected_vendor_workspace()
        else:
            refresh_marketplace()

    def on_apply_vendor_filters_clicked() -> None:
        nonlocal marketplace_orders_offset
        marketplace_orders_offset = 0
        apply_vendor_filters()

    def create_current_vendor_product() -> None:
        token = current_token()
        if not token:
            marketplace_message.setText("Login required.")
            return
        name, accepted = QInputDialog.getText(window, "Add My Product", "Product name:")
        if not accepted or not name.strip():
            return
        price_text, accepted = QInputDialog.getText(
            window, "Add My Product", "Price in minor units (for example, 2500):"
        )
        if not accepted:
            return
        try:
            price = int(price_text)
            if price < 0:
                raise ValueError
        except ValueError:
            marketplace_message.setText("Price must be a non-negative whole number.")
            return

        def action() -> object:
            return client.create_current_vendor_product(
                token, {"name": name.strip(), "regular_price_minor": price}
            )

        def completed(_value: object) -> None:
            marketplace_message.setText("Product published to your storefront.")
            refresh_marketplace()

        start_session_api_task(
            marketplace_message,
            action,
            on_result=completed,
            controls=(marketplace_vendor_product_create_button,),
        )

    def update_current_vendor_product_price() -> None:
        token = current_token()
        row = marketplace_current_products_table.currentRow()
        product_id_item = marketplace_current_products_table.item(row, 1) if row >= 0 else None
        product_id = product_id_item.text().strip() if product_id_item else ""
        if not token:
            marketplace_message.setText("Login required.")
            return
        if not product_id:
            marketplace_message.setText("Select one of your products first.")
            return
        price_text, accepted = QInputDialog.getText(
            window, "Update Product Price", "New price in minor units:"
        )
        if not accepted:
            return
        try:
            price = int(price_text)
            if price < 0:
                raise ValueError
        except ValueError:
            marketplace_message.setText("Price must be a non-negative whole number.")
            return

        def action() -> object:
            return client.update_current_vendor_product(
                token, product_id, {"regular_price_minor": price, "status": "active"}
            )

        def completed(_value: object) -> None:
            marketplace_message.setText("Product price updated and published.")
            refresh_marketplace()

        start_session_api_task(
            marketplace_message,
            action,
            on_result=completed,
            controls=(marketplace_vendor_product_price_button,),
        )

    def update_current_vendor_order_item() -> None:
        token = current_token()
        row = marketplace_current_orders_table.currentRow()
        item = marketplace_current_orders_table.item(row, 0) if row >= 0 else None
        vendor_order_item_id = item.text().strip() if item else ""
        if not token:
            marketplace_message.setText("Login required.")
            return
        if not vendor_order_item_id:
            marketplace_message.setText("Select one of your order items first.")
            return
        status = marketplace_vendor_order_status_action.currentText()
        reason = None
        if status == "rejected":
            reason, accepted = QInputDialog.getText(
                window, "Reject Order Item", "Reason for rejection:"
            )
            if not accepted:
                return
            if not reason.strip():
                marketplace_message.setText("A rejection reason is required.")
                return

        def action() -> object:
            return client.update_current_vendor_order_item_status(
                token, vendor_order_item_id, status, reason
            )

        def completed(_value: object) -> None:
            marketplace_message.setText("Order item status updated.")
            refresh_marketplace()

        start_session_api_task(
            marketplace_message,
            action,
            on_result=completed,
            controls=(marketplace_vendor_order_status_button,),
        )

    def adjust_current_vendor_stock() -> None:
        token = current_token()
        row = marketplace_vendor_stock_table.currentRow()
        product_item = marketplace_vendor_stock_table.item(row, 0) if row >= 0 else None
        warehouse_item = marketplace_vendor_stock_table.item(row, 1) if row >= 0 else None
        product_id = product_item.text().strip() if product_item else ""
        warehouse_id = warehouse_item.text().strip() if warehouse_item else ""
        if not token:
            marketplace_message.setText("Login required.")
            return
        if not product_id or not warehouse_id:
            marketplace_message.setText("Select one of your stock records first.")
            return
        quantity_text, accepted = QInputDialog.getText(
            window, "Adjust Stock", "Quantity change (positive or negative):"
        )
        if not accepted:
            return
        try:
            quantity_delta = int(quantity_text)
            if quantity_delta == 0:
                raise ValueError
        except ValueError:
            marketplace_message.setText("Enter a non-zero whole-number quantity.")
            return

        def action() -> object:
            return client.create_current_vendor_stock_movement(
                token,
                {
                    "vendor_id": "ignored-by-server",
                    "product_id": product_id,
                    "warehouse_id": warehouse_id,
                    "movement_type": "adjustment",
                    "quantity_delta": quantity_delta,
                    "ownership_type": "vendor_owned",
                    "source_type": "desktop_vendor_portal",
                    "source_id": f"manual-{uuid.uuid4().hex}",
                    "idempotency_key": f"desktop-{uuid.uuid4().hex}",
                    "reason": "Vendor portal stock adjustment",
                },
            )

        def completed(_value: object) -> None:
            marketplace_message.setText("Stock adjustment saved.")
            refresh_marketplace()

        start_session_api_task(
            marketplace_message,
            action,
            on_result=completed,
            controls=(marketplace_vendor_stock_adjust_button,),
        )

    def load_next_marketplace_orders() -> None:
        nonlocal marketplace_orders_offset, marketplace_orders_limit
        marketplace_orders_offset += marketplace_orders_limit
        apply_vendor_filters()

    def load_prev_marketplace_orders() -> None:
        nonlocal marketplace_orders_offset, marketplace_orders_limit
        marketplace_orders_offset = max(0, marketplace_orders_offset - marketplace_orders_limit)
        apply_vendor_filters()

    def export_ledger_journals() -> None:
        token = current_token()
        if not token:
            accounting_message.setText("Login required.")
            return
        if "ledger.export" not in set(state.get("permissions") or []):
            accounting_message.setText("Ledger export permission is required.")
            return
        path, _selected_filter = QFileDialog.getSaveFileName(
            window,
            "Export Ledger Journals",
            "ledger-journals.csv",
            "CSV Files (*.csv)",
        )
        if not path:
            return

        def action() -> None:
            csv_text = client.export_ledger_journals_csv(
                token,
                vendor_id=ledger_vendor_filter_input.text().strip() or None,
                account_id=ledger_account_filter_input.text().strip() or None,
                source_type=ledger_source_filter_input.text().strip() or None,
                status=ledger_status_filter_input.text().strip() or None,
                date_from=ledger_date_from_input.text().strip() or None,
                date_to=ledger_date_to_input.text().strip() or None,
            )
            Path(path).write_text(csv_text, encoding="utf-8", newline="")
            accounting_message.setText(f"Ledger journals exported to {path}")

        guarded(accounting_message, action)

    refresh_by_index = {
        0: refresh_dashboard,
        1: refresh_products,
        2: refresh_customers,
        3: refresh_inventory,
        4: refresh_orders,
        5: refresh_woocommerce,
        6: refresh_marketplace,
        7: refresh_accounting,
        8: refresh_settings,
        9: refresh_admin,
    }

    def on_nav_changed(index: int) -> None:
        if index < 0 or sidebar.item(index).isHidden() or not client.access_token:
            return
        stack.setCurrentIndex(index)
        refresh_by_index.get(index, refresh_settings)()

    def update_vendor_onboarding_fields() -> None:
        temporary_password = (
            str(marketplace_vendor_onboarding_input.currentData() or "") == "temporary_password"
        )
        marketplace_vendor_password_input.setEnabled(temporary_password)
        if not temporary_password:
            marketplace_vendor_password_input.clear()

    sidebar.currentRowChanged.connect(on_nav_changed)
    login_button.clicked.connect(login)
    logout_button.clicked.connect(logout)
    password_change_logout_button.clicked.connect(logout)
    password_change_button.clicked.connect(change_required_password)
    forgot_password_button.clicked.connect(lambda: open_public_auth_page("/forgot-password"))
    vendor_registration_button.clicked.connect(lambda: open_public_auth_page("/register"))
    username_input.returnPressed.connect(login)
    password_input.returnPressed.connect(login)
    workspace_input.returnPressed.connect(login)
    dashboard_refresh.clicked.connect(refresh_dashboard)
    dashboard_sync_products_button.clicked.connect(
        lambda: run_woocommerce_sync(mode="products")
    )
    dashboard_sync_all_button.clicked.connect(
        lambda: run_woocommerce_sync(mode="incremental")
    )
    product_refresh_button.clicked.connect(refresh_products)
    product_new_button.clicked.connect(lambda: clear_product_form(generate_defaults=True))
    product_save_button.clicked.connect(save_product)
    product_archive_button.clicked.connect(archive_selected_product)
    product_delete_permanent_button.clicked.connect(lambda: permanently_delete_products(bulk=False))
    product_publish_button.clicked.connect(lambda: change_product_status("active"))
    product_draft_button.clicked.connect(lambda: change_product_status("draft"))
    product_restore_button.clicked.connect(lambda: change_product_status("active"))
    product_bulk_button.clicked.connect(apply_product_bulk_action)
    product_clear_button.clicked.connect(lambda: clear_product_form(generate_defaults=False))
    product_table.itemSelectionChanged.connect(load_selected_product)
    product_search_input.textChanged.connect(apply_product_filter)
    product_trash_button.clicked.connect(show_product_trash)
    product_status_filter.currentIndexChanged.connect(refresh_products)
    product_sort_input.currentIndexChanged.connect(apply_product_filter)
    product_sort_order.currentIndexChanged.connect(apply_product_filter)
    product_category_combo.activated[int].connect(on_category_combo_activated)
    product_brand_combo.activated[int].connect(on_brand_combo_activated)
    product_add_image_button.clicked.connect(add_product_image_url)
    product_upload_image_button.clicked.connect(upload_product_image)
    product_remove_image_button.clicked.connect(remove_selected_image)
    product_add_video_button.clicked.connect(add_product_video_url)
    product_upload_video_button.clicked.connect(upload_product_video)
    product_open_video_button.clicked.connect(open_selected_product_video)
    product_remove_video_button.clicked.connect(remove_selected_video)
    product_add_variant_button.clicked.connect(add_product_variant)
    product_remove_variant_button.clicked.connect(remove_selected_variant)
    customer_refresh_button.clicked.connect(refresh_customers)
    customer_create_button.clicked.connect(create_customer)
    inventory_refresh_button.clicked.connect(refresh_inventory)
    orders_refresh_button.clicked.connect(refresh_orders)
    woo_save_button.clicked.connect(save_woocommerce)
    woo_test_button.clicked.connect(test_woocommerce)
    woo_sync_button.clicked.connect(run_woocommerce_sync)
    woo_refresh_button.clicked.connect(lambda: refresh_woocommerce())
    marketplace_refresh_button.clicked.connect(refresh_marketplace)
    marketplace_vendor_create_button.clicked.connect(create_vendor)
    marketplace_vendor_status_button.clicked.connect(apply_vendor_status)
    marketplace_vendor_approve_button.clicked.connect(lambda: apply_vendor_lifecycle("approve"))
    marketplace_vendor_pause_button.clicked.connect(lambda: apply_vendor_lifecycle("pause"))
    marketplace_vendor_reactivate_button.clicked.connect(
        lambda: apply_vendor_lifecycle("reactivate")
    )
    marketplace_vendor_stop_button.clicked.connect(lambda: apply_vendor_lifecycle("stop"))
    marketplace_vendor_edit_button.clicked.connect(edit_vendor)
    marketplace_vendor_reset_password_button.clicked.connect(reset_vendor_user_password)
    marketplace_vendor_onboarding_input.currentIndexChanged.connect(update_vendor_onboarding_fields)
    marketplace_apply_filters_button.clicked.connect(on_apply_vendor_filters_clicked)
    marketplace_vendor_product_create_button.clicked.connect(create_current_vendor_product)
    marketplace_vendor_product_price_button.clicked.connect(update_current_vendor_product_price)
    marketplace_vendor_stock_adjust_button.clicked.connect(adjust_current_vendor_stock)
    marketplace_vendor_order_status_button.clicked.connect(update_current_vendor_order_item)
    marketplace_orders_next_btn.clicked.connect(load_next_marketplace_orders)
    marketplace_orders_prev_btn.clicked.connect(load_prev_marketplace_orders)
    marketplace_vendor_table.itemSelectionChanged.connect(load_selected_vendor_workspace)
    accounting_refresh_button.clicked.connect(refresh_accounting)
    ledger_apply_filters_button.clicked.connect(refresh_accounting)
    ledger_export_button.clicked.connect(export_ledger_journals)
    accounting_account_create_button.clicked.connect(create_account)
    accounting_cash_create_button.clicked.connect(create_cash_book)
    accounting_bank_create_button.clicked.connect(create_bank_account)
    settings_refresh_button.clicked.connect(refresh_settings)
    admin_refresh_button.clicked.connect(refresh_admin)
    company_update_button.clicked.connect(update_admin_company)
    admin_create_user_button.clicked.connect(create_admin_user)
    admin_apply_user_status_button.clicked.connect(apply_admin_user_status)
    admin_reset_password_button.clicked.connect(reset_admin_password)
    user_table.itemSelectionChanged.connect(load_selected_admin_user)
    admin_create_role_button.clicked.connect(create_admin_role)
    admin_activate_license_button.clicked.connect(activate_admin_license)
    admin_validate_license_button.clicked.connect(validate_admin_license)
    admin_revoke_license_button.clicked.connect(revoke_admin_license)

    content.addWidget(title)
    content.addWidget(status_label)
    content.addWidget(auth_box)
    content.addWidget(stack, 1)
    root_layout.addWidget(sidebar)
    root_layout.addLayout(content, 1)

    window.setCentralWidget(screen_stack)
    health_timer = QTimer(window)
    health_timer.setInterval(5000)
    health_timer.timeout.connect(refresh_api_health_async)
    health_timer.start()
    session_refresh_timer = QTimer(window)
    session_refresh_timer.setInterval(20 * 60 * 1000)
    session_refresh_timer.timeout.connect(refresh_desktop_session)
    session_refresh_timer.start()
    update_vendor_onboarding_fields()
    apply_navigation_permissions([])
    screen_stack.setCurrentWidget(auth_page)
    window.show()
    restore_saved_session()

    def shutdown_desktop_tasks() -> None:
        health_timer.stop()
        session_refresh_timer.stop()
        task_runner.pool.waitForDone(3000)

    app.aboutToQuit.connect(shutdown_desktop_tasks)
    return app.exec()


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
