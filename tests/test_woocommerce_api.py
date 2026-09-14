from __future__ import annotations

import base64
import hashlib
import hmac
import json as jsonlib
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session, sessionmaker

from erp.apps.api.main import create_app
from erp.apps.worker.main import run_once as worker_run_once
from erp.packages.core import woocommerce_services
from erp.packages.core.config import get_settings
from erp.packages.core.db.base import Base
from erp.packages.core.db.models import (
    AuditLog,
    Brand,
    Category,
    Company,
    ExternalResourceMap,
    Product,
    ProductChannelListing,
    ProductCategoryLink,
    ProductImage,
    ProductVariant,
    ProductVideo,
    Setting,
    StockMovement,
    SyncInboxLog,
    SyncOutbox,
    SyncRunLog,
    User,
    Vendor,
    Warehouse,
)
from erp.packages.core.db.session import get_session
from erp.packages.core.security import encrypt_text
from erp.packages.core.services import utcnow
from erp.packages.core.woocommerce_services import (
    SYNC_OUTBOX_STALE_SECONDS,
    WOOCOMMERCE_SETTING_KEY,
    WOOCOMMERCE_VIDEO_META_KEY,
    build_woocommerce_product_video_manifest,
    enqueue_product_sync,
    enqueue_product_video_sync,
    enqueue_products_for_sync,
    enqueue_sync_outbox,
    enqueue_woocommerce_sync_run,
    ensure_remote_brand,
    ensure_remote_category,
    get_external_resource_map,
    get_woocommerce_last_sync,
    pending_product_media_ids_query,
    process_sync_outbox,
    pull_customers,
    pull_orders,
    pull_products,
    reconcile_products,
    recover_stale_woocommerce_sync_records,
    run_woocommerce_sync,
    upsert_external_resource_map,
)
from erp.packages.core.woocommerce_services import (
    test_wordpress_video_plugin as check_wordpress_video_plugin,
)


@dataclass(frozen=True)
class ApiHarness:
    client: TestClient
    session_factory: sessionmaker


def test_pending_product_media_query_is_valid_for_postgresql() -> None:
    statement = pending_product_media_ids_query("company-1")
    sql = str(statement.compile(dialect=postgresql.dialect()))

    assert "SELECT DISTINCT products.id" in sql
    assert "ORDER BY" not in sql


def test_non_numeric_product_image_ids_are_not_sent_as_remote_ids() -> None:
    image = ProductImage(
        company_id="company-1",
        product_id="product-1",
        external_id="demo-image-1",
        url="https://example.com/demo-image.jpg",
        sync_status="synced",
    )

    payload = woocommerce_services._woocommerce_image_payload(image, "Demo Product")

    assert payload is None


def test_checkpoint_setting_query_refreshes_and_locks_for_postgresql() -> None:
    statements: list[object] = []

    class FakeBind:
        dialect = postgresql.dialect()

    class FakeSession:
        def get_bind(self) -> FakeBind:
            return FakeBind()

        def scalar(self, statement: object) -> None:
            statements.append(statement)

    result = woocommerce_services.get_setting(
        FakeSession(),  # type: ignore[arg-type]
        "company-1",
        WOOCOMMERCE_SETTING_KEY,
        for_update=True,
    )

    assert result is None
    assert len(statements) == 1
    statement = statements[0]
    assert "FOR UPDATE" in str(statement.compile(dialect=postgresql.dialect()))
    assert statement.get_execution_options()["populate_existing"] is True


def query_params(url: str) -> dict[str, str]:
    parsed = urlparse(url)
    return {key: values[-1] for key, values in parse_qs(parsed.query).items()}


def woocommerce_resource_path(url: str) -> str:
    parsed = urlparse(url)
    params = query_params(url)
    rest_route = params.get("rest_route")
    if rest_route and rest_route.startswith("/wc/v3"):
        return rest_route.removeprefix("/wc/v3")
    if parsed.path.startswith("/wp-json/wc/v3"):
        return parsed.path.removeprefix("/wp-json/wc/v3")
    return parsed.path


@pytest.fixture()
def harness(tmp_path: Path) -> Iterator[ApiHarness]:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'woocommerce_api.db'}",
        connect_args={"check_same_thread": False},
        future=True,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
        future=True,
    )

    def override_session() -> Iterator[Session]:
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    app = create_app()
    app.dependency_overrides[get_session] = override_session
    with TestClient(app) as test_client:
        yield ApiHarness(client=test_client, session_factory=session_factory)
    app.dependency_overrides.clear()
    engine.dispose()


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def queue_and_process_sync(
    harness: ApiHarness,
    headers: dict[str, str],
    *,
    mode: str | None = None,
) -> tuple[dict[str, object], dict[str, object]]:
    """Exercise the API queue and separate worker exactly as production does."""

    path = "/api/v1/woocommerce/sync"
    if mode is not None:
        path = f"{path}?mode={mode}"
    queued_response = harness.client.post(path, headers=headers)
    assert queued_response.status_code == 202
    queued = queued_response.json()
    assert queued["status"] == "queued"
    run_id = str(queued["id"])
    worker_state = worker_run_once(session_factory=harness.session_factory)
    assert worker_state["run_id"] == run_id
    runs_response = harness.client.get("/api/v1/woocommerce/sync-runs", headers=headers)
    assert runs_response.status_code == 200
    completed = next(run for run in runs_response.json() if run["id"] == run_id)
    return queued, completed


def woo_webhook_signature(raw_body: bytes, secret: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).digest()
    return base64.b64encode(digest).decode("ascii")


def complete_first_use_setup(client: TestClient) -> tuple[str, str]:
    response = client.post(
        "/api/v1/setup/first-use",
        json={
            "company_name": "Woo Test Company",
            "username": "admin",
            "password": "admin12345",
            "full_name": "Admin User",
            "email": "woocommerce-admin@example.com",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert "woocommerce.configure" in payload["permissions"]
    return str(payload["access_token"]), str(payload["company"]["id"])


def configure_store(
    client: TestClient,
    headers: dict[str, str],
    *,
    wordpress_media: bool = False,
    webhook_secret: str | None = None,
) -> None:
    payload = {
        "site_url": "https://shop.example.test",
        "consumer_key": "ck_test_123456",
        "consumer_secret": "cs_test_123456",
    }
    if webhook_secret:
        payload["webhook_secret"] = webhook_secret
    if wordpress_media:
        payload["wordpress_username"] = "choiceoye"
        payload["wordpress_application_password"] = "wp-app-pass-123456"
    response = client.put(
        "/api/v1/woocommerce/config",
        headers=headers,
        json=payload,
    )
    assert response.status_code == 200


def test_admin_can_inspect_and_retry_failed_product_media_sync(
    harness: ApiHarness,
) -> None:
    token, company_id = complete_first_use_setup(harness.client)
    headers = bearer(token)
    with harness.session_factory() as db:
        product = Product(
            company_id=company_id,
            name="Retry Image Product",
            slug="retry-image-product",
            sku="ERP-RETRY-IMAGE",
            product_type="simple",
            status="active",
            metadata_json={},
        )
        db.add(product)
        db.flush()
        db.add(
            ProductImage(
                company_id=company_id,
                product_id=product.id,
                url="/media/products/missing-image.png",
                name="missing-image.png",
                sync_status="pending_add",
            )
        )
        failed = SyncOutbox(
            company_id=company_id,
            connector="woocommerce",
            operation="push_media",
            resource_type="product",
            resource_id=product.id,
            payload={"images": []},
            idempotency_key="woocommerce:test:failed-media-retry",
            status="failed",
            attempts=2,
            last_error="WordPress password=secret-value failed while uploading image.",
        )
        db.add(failed)
        db.commit()
        product_id = product.id
        failed_id = failed.id

    failures = harness.client.get(
        "/api/v1/woocommerce/media-sync-failures", headers=headers
    )
    assert failures.status_code == 200
    row = failures.json()[0]
    assert row["id"] == failed_id
    assert row["product_id"] == product_id
    assert row["product_name"] == "Retry Image Product"
    assert "secret-value" not in (row["last_error"] or "")
    assert "[redacted]" in (row["last_error"] or "")

    retried = harness.client.post(
        f"/api/v1/woocommerce/media-sync-failures/{product_id}/retry",
        headers=headers,
    )
    assert retried.status_code == 202
    assert retried.json()["queued_products"] == 1

    with harness.session_factory() as db:
        stale = db.get(SyncOutbox, failed_id)
        assert stale is not None
        assert stale.status == "synced"
        current = db.scalars(
            select(SyncOutbox).where(
                SyncOutbox.company_id == company_id,
                SyncOutbox.operation == "push_media",
                SyncOutbox.resource_id == product_id,
                SyncOutbox.status == "pending",
            )
        ).all()
        assert len(current) == 1


def test_product_video_manifest_preserves_external_video_order(harness: ApiHarness) -> None:
    _token, company_id = complete_first_use_setup(harness.client)
    with harness.session_factory() as db:
        product = Product(
            company_id=company_id,
            name="External Videos",
            slug="external-videos",
            sku="ERP-VIDEO-EXTERNAL",
            product_type="simple",
            status="active",
            metadata_json={},
        )
        db.add(product)
        db.flush()
        db.add_all(
            [
                ProductVideo(
                    company_id=company_id,
                    product_id=product.id,
                    source_type="youtube",
                    url="https://www.youtube.com/watch?v=AbCdEf_1234",
                    name="YouTube demo",
                    sort_order=2,
                ),
                ProductVideo(
                    company_id=company_id,
                    product_id=product.id,
                    source_type="vimeo",
                    url="https://vimeo.com/1234567",
                    name="Vimeo demo",
                    sort_order=0,
                ),
                ProductVideo(
                    company_id=company_id,
                    product_id=product.id,
                    source_type="mp4",
                    url="https://cdn.example.test/products/demo.mp4",
                    name="Direct MP4",
                    sort_order=1,
                ),
            ]
        )
        db.commit()
        manifest = build_woocommerce_product_video_manifest(
            db,
            company_id=company_id,
            product=product,
        )

    assert manifest["schema_version"] == 1
    videos = manifest["videos"]
    assert [video["source_type"] for video in videos] == ["vimeo", "mp4", "youtube"]
    assert [video["sort_order"] for video in videos] == [0, 1, 2]
    assert all("attachment_id" not in video for video in videos)


def test_uploaded_product_video_sync_uploads_then_publishes_metadata(
    harness: ApiHarness,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    token, company_id = complete_first_use_setup(harness.client)
    headers = bearer(token)
    configure_store(harness.client, headers, wordpress_media=True)
    monkeypatch.setattr(
        woocommerce_services,
        "get_settings",
        lambda: SimpleNamespace(media_upload_dir=str(tmp_path)),
    )
    local_path = tmp_path / "products" / company_id / "video-product" / "videos" / "demo.mp4"
    local_path.parent.mkdir(parents=True, exist_ok=True)
    local_path.write_bytes(b"demo-mp4-data")

    with harness.session_factory() as db:
        product = Product(
            id="video-product",
            company_id=company_id,
            name="Uploaded Video",
            slug="uploaded-video",
            sku="ERP-VIDEO-UPLOAD",
            product_type="simple",
            status="active",
            metadata_json={},
        )
        db.add(product)
        db.flush()
        video = ProductVideo(
            company_id=company_id,
            product_id=product.id,
            source_type="uploaded",
            url=f"/media/products/{company_id}/{product.id}/videos/demo.mp4",
            name="demo.mp4",
            sort_order=0,
        )
        db.add(video)
        upsert_external_resource_map(
            db,
            company_id=company_id,
            resource_type="product",
            internal_id=product.id,
            external_id="501",
        )
        db.flush()
        enqueue_product_video_sync(db, company_id=company_id, product=product)
        db.commit()
        video_id = video.id

    uploads: list[bytes] = []
    payloads: list[dict[str, object]] = []

    def mock_request(
        method: str,
        url: str,
        json: dict | None = None,
        **kwargs: object,
    ) -> httpx.Response:
        assert kwargs.get("follow_redirects") is True
        if method == "GET" and url.endswith("/wp-json/choiceoye-erp/v1/status"):
            return httpx.Response(
                200,
                json={
                    "plugin": "choiceoye-erp-product-videos",
                    "version": "1.0.0",
                    "schema_versions": [1],
                    "woocommerce": True,
                    "max_upload_bytes": 100 * 1024 * 1024,
                },
            )
        if method == "POST" and url.endswith("/wp-json/wp/v2/media"):
            uploads.append(b"".join(kwargs["content"]))
            return httpx.Response(
                201,
                json={
                    "id": 991,
                    "source_url": "https://shop.example.test/wp-content/uploads/demo.mp4",
                },
            )
        if method == "PUT" and url.endswith("/wp-json/wc/v3/products/501"):
            payloads.append(json or {})
            return httpx.Response(200, json={"id": 501})
        raise AssertionError(f"Unexpected video sync request: {method} {url}")

    monkeypatch.setattr(httpx, "request", mock_request)
    with harness.session_factory() as db:
        result = process_sync_outbox(db, company_id)
        db.commit()
        stored = db.get(ProductVideo, video_id)
        assert stored is not None
        assert stored.external_id == "991"
        assert stored.remote_url == "https://shop.example.test/wp-content/uploads/demo.mp4"
        assert stored.sync_status == "synced"
        assert stored.last_synced_at is not None

    assert result == {
        "pushed": 0,
        "pushed_media": 0,
        "pushed_videos": 1,
        "failed": 0,
        "deferred": 0,
        "deferred_videos": 0,
    }
    assert uploads == [b"demo-mp4-data"]
    assert payloads == [
        {
            "meta_data": [
                {
                    "key": WOOCOMMERCE_VIDEO_META_KEY,
                    "value": {
                        "schema_version": 1,
                        "videos": [
                            {
                                "erp_video_id": video_id,
                                "source_type": "uploaded",
                                "url": "https://shop.example.test/wp-content/uploads/demo.mp4",
                                "name": "demo.mp4",
                                "sort_order": 0,
                                "attachment_id": 991,
                            }
                        ],
                    },
                }
            ]
        }
    ]


def test_empty_product_video_manifest_clears_storefront_videos(
    harness: ApiHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token, company_id = complete_first_use_setup(harness.client)
    headers = bearer(token)
    configure_store(harness.client, headers)
    with harness.session_factory() as db:
        product = Product(
            company_id=company_id,
            name="Cleared Videos",
            slug="cleared-videos",
            sku="ERP-VIDEO-CLEAR",
            product_type="simple",
            status="active",
            metadata_json={},
        )
        db.add(product)
        db.flush()
        upsert_external_resource_map(
            db,
            company_id=company_id,
            resource_type="product",
            internal_id=product.id,
            external_id="777",
        )
        enqueue_product_video_sync(db, company_id=company_id, product=product)
        db.commit()

    payloads: list[dict[str, object]] = []

    def mock_request(
        method: str, url: str, json: dict | None = None, **kwargs: object
    ) -> httpx.Response:
        if method == "PUT" and url.endswith("/wp-json/wc/v3/products/777"):
            payloads.append(json or {})
            return httpx.Response(200, json={"id": 777})
        raise AssertionError(f"Unexpected empty-video request: {method} {url}")

    monkeypatch.setattr(httpx, "request", mock_request)
    with harness.session_factory() as db:
        assert process_sync_outbox(db, company_id)["pushed_videos"] == 1

    assert payloads == [
        {
            "meta_data": [
                {
                    "key": WOOCOMMERCE_VIDEO_META_KEY,
                    "value": {"schema_version": 1, "videos": []},
                }
            ]
        }
    ]


def test_video_only_api_updates_queue_video_outbox_without_new_product_push(
    harness: ApiHarness,
) -> None:
    token, company_id = complete_first_use_setup(harness.client)
    headers = bearer(token)
    configure_store(harness.client, headers)
    created = harness.client.post(
        "/api/v1/catalog/products",
        headers=headers,
        json={
            "name": "Video Queue Product",
            "sku": "ERP-VIDEO-QUEUE",
            "product_type": "simple",
            "status": "active",
            "regular_price_minor": 100,
            "videos": [
                {"url": "https://vimeo.com/123456", "name": "First", "sort_order": 0},
                {
                    "url": "https://cdn.example.test/demo.mp4",
                    "name": "Second",
                    "sort_order": 1,
                },
            ],
        },
    )
    assert created.status_code == 201, created.text
    product = created.json()
    product_id = product["id"]

    reordered = [
        {
            "id": video["id"],
            "url": video["url"],
            "name": video["name"],
            "sort_order": 1 - index,
        }
        for index, video in enumerate(product["videos"])
    ]
    updated = harness.client.patch(
        f"/api/v1/catalog/products/{product_id}",
        headers=headers,
        json={"videos": reordered},
    )
    assert updated.status_code == 200, updated.text

    with harness.session_factory() as db:
        product_pushes = db.scalars(
            select(SyncOutbox).where(
                SyncOutbox.company_id == company_id,
                SyncOutbox.resource_id == product_id,
                SyncOutbox.operation == "push",
            )
        ).all()
        video_pushes = db.scalars(
            select(SyncOutbox).where(
                SyncOutbox.company_id == company_id,
                SyncOutbox.resource_id == product_id,
                SyncOutbox.operation == "push_videos",
            )
        ).all()

    assert len(product_pushes) == 1
    expected_order = [video["id"] for video in reversed(product["videos"])]
    assert any(
        [video["id"] for video in record.payload["videos"]] == expected_order
        for record in video_pushes
    )

    removed = harness.client.patch(
        f"/api/v1/catalog/products/{product_id}",
        headers=headers,
        json={"videos": []},
    )
    assert removed.status_code == 200, removed.text
    with harness.session_factory() as db:
        video_pushes = db.scalars(
            select(SyncOutbox).where(
                SyncOutbox.company_id == company_id,
                SyncOutbox.resource_id == product_id,
                SyncOutbox.operation == "push_videos",
            )
        ).all()
    assert any(record.payload == {"videos": []} for record in video_pushes)


def test_uploaded_product_video_respects_wordpress_upload_limit(
    harness: ApiHarness,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    token, company_id = complete_first_use_setup(harness.client)
    headers = bearer(token)
    configure_store(harness.client, headers, wordpress_media=True)
    monkeypatch.setattr(
        woocommerce_services,
        "get_settings",
        lambda: SimpleNamespace(media_upload_dir=str(tmp_path)),
    )
    local_path = tmp_path / "products" / company_id / "limited-video" / "videos" / "demo.mp4"
    local_path.parent.mkdir(parents=True, exist_ok=True)
    local_path.write_bytes(b"too-large-for-one-byte-limit")

    with harness.session_factory() as db:
        product = Product(
            id="limited-video",
            company_id=company_id,
            name="Limited Video",
            slug="limited-video",
            sku="ERP-VIDEO-LIMIT",
            product_type="simple",
            status="active",
            metadata_json={},
        )
        db.add(product)
        db.flush()
        db.add(
            ProductVideo(
                company_id=company_id,
                product_id=product.id,
                source_type="uploaded",
                url=f"/media/products/{company_id}/{product.id}/videos/demo.mp4",
                name="demo.mp4",
                sort_order=0,
            )
        )
        upsert_external_resource_map(
            db,
            company_id=company_id,
            resource_type="product",
            internal_id=product.id,
            external_id="502",
        )
        db.flush()
        enqueue_product_video_sync(db, company_id=company_id, product=product)
        db.commit()

    def mock_request(method: str, url: str, **kwargs: object) -> httpx.Response:
        assert method == "GET"
        assert url.endswith("/wp-json/choiceoye-erp/v1/status")
        return httpx.Response(
            200,
            json={
                "plugin": "choiceoye-erp-product-videos",
                "version": "1.0.0",
                "schema_versions": [1],
                "woocommerce": True,
                "max_upload_bytes": 1,
            },
        )

    monkeypatch.setattr(httpx, "request", mock_request)
    with harness.session_factory() as db:
        result = process_sync_outbox(db, company_id)
        db.commit()
        record = db.scalar(
            select(SyncOutbox).where(
                SyncOutbox.company_id == company_id,
                SyncOutbox.operation == "push_videos",
                SyncOutbox.resource_id == "limited-video",
            )
        )

    assert result["failed"] == 1
    assert record is not None
    assert record.status == "failed"
    assert record.last_error is not None
    assert record.last_error.startswith(
        "Product video exceeds the WordPress upload limit (1 bytes)."
    )


def test_wordpress_video_plugin_status_is_saved_without_blocking_product_sync(
    harness: ApiHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token, company_id = complete_first_use_setup(harness.client)
    headers = bearer(token)
    configure_store(harness.client, headers)

    def mock_request(method: str, url: str, **kwargs: object) -> httpx.Response:
        assert method == "GET"
        assert kwargs.get("follow_redirects") is True
        assert url.endswith("/wp-json/choiceoye-erp/v1/status")
        return httpx.Response(
            200,
            json={
                "plugin": "choiceoye-erp-product-videos",
                "version": "1.0.0",
                "schema_versions": [1],
                "woocommerce": True,
                "max_upload_bytes": 50 * 1024 * 1024,
            },
        )

    monkeypatch.setattr(httpx, "request", mock_request)
    with harness.session_factory() as db:
        status = check_wordpress_video_plugin(db, company_id)
        db.commit()

    assert status == {
        "detected": True,
        "compatible": True,
        "version": "1.0.0",
        "max_upload_bytes": 50 * 1024 * 1024,
    }
    config = harness.client.get("/api/v1/woocommerce/config", headers=headers)
    assert config.status_code == 200
    assert config.json()["video_plugin_detected"] is True
    assert config.json()["video_plugin_compatible"] is True
    assert config.json()["wordpress_max_upload_bytes"] == 50 * 1024 * 1024


def test_wordpress_video_plugin_requires_woocommerce_for_compatibility(
    harness: ApiHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _token, company_id = complete_first_use_setup(harness.client)
    configure_store(harness.client, bearer(_token))

    def mock_request(method: str, url: str, **kwargs: object) -> httpx.Response:
        assert method == "GET"
        assert url.endswith("/wp-json/choiceoye-erp/v1/status")
        return httpx.Response(
            200,
            json={
                "plugin": "choiceoye-erp-product-videos",
                "version": "1.0.0",
                "schema_versions": [1],
                "woocommerce": False,
                "max_upload_bytes": 50 * 1024 * 1024,
            },
        )

    monkeypatch.setattr(httpx, "request", mock_request)
    with harness.session_factory() as db:
        status = check_wordpress_video_plugin(db, company_id)

    assert status["detected"] is True
    assert status["compatible"] is False


def test_woocommerce_product_pull_preserves_erp_owned_video_rows(harness: ApiHarness) -> None:
    _token, company_id = complete_first_use_setup(harness.client)
    with harness.session_factory() as db:
        product = Product(
            company_id=company_id,
            name="ERP Video Owner",
            slug="erp-video-owner",
            sku="ERP-VIDEO-PULL",
            product_type="simple",
            status="active",
            metadata_json={},
        )
        db.add(product)
        db.flush()
        db.add(
            ProductVideo(
                company_id=company_id,
                product_id=product.id,
                source_type="youtube",
                url="https://www.youtube.com/watch?v=abc123XYZ",
                name="ERP-owned video",
                sort_order=0,
                sync_status="synced",
            )
        )
        upsert_external_resource_map(
            db,
            company_id=company_id,
            resource_type="product",
            internal_id=product.id,
            external_id="901",
        )
        db.commit()
        product_id = product.id

    with harness.session_factory() as db:
        woocommerce_services.sync_single_product(
            db,
            company_id,
            {
                "id": 901,
                "name": "Remote product update",
                "sku": "ERP-VIDEO-PULL",
                "status": "publish",
                "regular_price": "10.00",
                "meta_data": [
                    {
                        "key": WOOCOMMERCE_VIDEO_META_KEY,
                        "value": {"schema_version": 1, "videos": []},
                    }
                ],
            },
        )
        db.commit()
        videos = db.scalars(
            select(ProductVideo).where(
                ProductVideo.company_id == company_id,
                ProductVideo.product_id == product_id,
            )
        ).all()

    assert len(videos) == 1
    assert videos[0].name == "ERP-owned video"
    assert videos[0].url == "https://www.youtube.com/watch?v=abc123XYZ"


def test_vendor_product_outbox_enqueue_is_scoped_to_vendor(harness: ApiHarness) -> None:
    _token, company_id = complete_first_use_setup(harness.client)
    with harness.session_factory() as db:
        vendor = Vendor(
            company_id=company_id,
            name="Scoped Vendor",
            slug="scoped-vendor",
            status="active",
        )
        owned = Product(
            company_id=company_id,
            vendor_id=None,
            name="Owned Product",
            slug="owned-product",
            status="active",
            metadata_json={},
        )
        other = Product(
            company_id=company_id,
            name="Other Product",
            slug="other-product",
            status="active",
            metadata_json={},
        )
        db.add_all([vendor, owned, other])
        db.flush()
        owned.vendor_id = vendor.id
        db.add(ProductChannelListing(
            company_id=company_id, product_id=owned.id, vendor_id=vendor.id,
            channel="woocommerce", listing_status="published", sync_status="pending",
        ))
        db.flush()

        assert enqueue_products_for_sync(db, company_id, vendor_id=vendor.id) == 1
        queued_ids = set(
            db.scalars(
                select(SyncOutbox.resource_id).where(
                    SyncOutbox.company_id == company_id,
                    SyncOutbox.resource_type == "product",
                )
            ).all()
        )

    assert queued_ids == {owned.id}


def test_woocommerce_config_is_encrypted_and_test_success_is_mocked(
    harness: ApiHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = harness.client
    assert client.get("/api/v1/woocommerce/config").status_code == 401
    token, _company_id = complete_first_use_setup(client)
    headers = bearer(token)

    empty_config = client.get("/api/v1/woocommerce/config", headers=headers)
    assert empty_config.status_code == 200
    assert empty_config.json() == {
        "configured": False,
        "site_url": None,
        "consumer_key_hint": None,
        "wordpress_username": None,
        "wordpress_media_configured": False,
        "webhook_secret_configured": False,
        "pending_product_pushes": 0,
        "pending_media_pushes": 0,
        "pending_video_pushes": 0,
        "failed_product_pushes": 0,
        "failed_media_pushes": 0,
        "failed_video_pushes": 0,
        "last_media_error": None,
        "last_video_error": None,
        "video_plugin_detected": False,
        "video_plugin_compatible": False,
        "video_plugin_version": None,
        "wordpress_max_upload_bytes": None,
        "queued_sync_runs": 0,
        "running_sync_runs": 0,
        "active_sync_run_id": None,
        "active_sync_worker_id": None,
        "updated_at": None,
    }

    configure_store(client, headers)
    config = client.get("/api/v1/woocommerce/config", headers=headers)
    assert config.status_code == 200
    assert config.json()["site_url"] == "https://shop.example.test"
    assert config.json()["consumer_key_hint"] == "ck_t...3456"
    assert config.json()["wordpress_username"] is None
    assert config.json()["wordpress_media_configured"] is False
    assert config.json()["webhook_secret_configured"] is False
    assert "consumer_secret" not in config.text
    assert "cs_test_123456" not in config.text

    with harness.session_factory() as db:
        setting = db.scalar(select(Setting).where(Setting.key == WOOCOMMERCE_SETTING_KEY))
        assert setting is not None
        encrypted_value = str(setting.value)
        assert "https://shop.example.test" not in encrypted_value
        assert "ck_test_123456" not in encrypted_value
        assert "cs_test_123456" not in encrypted_value

        legacy_value = dict(setting.value)
        legacy_value["site_url"] = encrypt_text("https://shop.example.test/")
        setting.value = legacy_value
        db.commit()

    normalized_config = client.get("/api/v1/woocommerce/config", headers=headers)
    assert normalized_config.status_code == 200
    assert normalized_config.json()["site_url"] == "https://shop.example.test"

    media_config = client.put(
        "/api/v1/woocommerce/config",
        headers=headers,
        json={
            "site_url": "https://shop.example.test",
            "consumer_key": "ck_test_123456",
            "consumer_secret": "cs_test_123456",
            "wordpress_username": "choiceoye",
            "wordpress_application_password": "wp-app-pass-123456",
        },
    )
    assert media_config.status_code == 200
    assert media_config.json()["wordpress_username"] == "choiceoye"
    assert media_config.json()["wordpress_media_configured"] is True
    assert media_config.json()["webhook_secret_configured"] is False
    assert "wp-app-pass-123456" not in media_config.text
    with harness.session_factory() as db:
        setting = db.scalar(select(Setting).where(Setting.key == WOOCOMMERCE_SETTING_KEY))
        assert setting is not None
        encrypted_value = str(setting.value)
        assert "wp-app-pass-123456" not in encrypted_value

    def fake_request(
        method: str,
        url: str,
        auth: tuple[str, str] | None = None,
        timeout: float | None = None,
        json: dict | None = None,
        **kwargs: object,
    ) -> httpx.Response:
        assert method == "GET"
        assert urlparse(url).netloc == "shop.example.test"
        assert woocommerce_resource_path(url) in {
            "/products",
            "/products/categories",
            "/products/brands",
            "/customers",
            "/orders",
        }
        assert query_params(url).get("per_page") == "1"
        assert auth == ("ck_test_123456", "cs_test_123456")
        assert timeout == 5.0
        assert json is None
        assert kwargs.get("params") is None
        assert kwargs.get("follow_redirects") is True
        return httpx.Response(200, json=[])

    monkeypatch.setattr(httpx, "request", fake_request)
    test_response = client.post("/api/v1/woocommerce/test-connection", headers=headers)
    assert test_response.status_code == 200
    assert test_response.json() == {
        "ok": True,
        "status": "ok",
        "detail": (
            "WooCommerce connection succeeded. "
            "Read access verified for products, categories, brands, customers, orders. "
            "ChoiceOye video plugin was not detected; video metadata can sync but will not "
            "render."
        ),
        "video_plugin_detected": False,
        "video_plugin_compatible": False,
        "video_plugin_version": None,
        "wordpress_max_upload_bytes": None,
    }
    with harness.session_factory() as db:
        setting = db.scalar(select(Setting).where(Setting.key == WOOCOMMERCE_SETTING_KEY))
        assert setting is not None
        assert setting.value["rest_api_mode"] == "pretty"


def test_woocommerce_connection_failures_are_mocked(
    harness: ApiHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = harness.client
    token, _company_id = complete_first_use_setup(client)
    headers = bearer(token)
    configure_store(client, headers)

    def auth_failure(
        method: str,
        url: str,
        auth: tuple[str, str],
        json: dict | None = None,
        timeout: float | None = None,
        **kwargs: object,
    ) -> httpx.Response:
        assert method == "GET"
        assert query_params(url).get("per_page") == "1"
        assert kwargs.get("params") is None
        assert kwargs.get("follow_redirects") is True
        return httpx.Response(
            401,
            json={
                "code": "woocommerce_rest_authentication_error",
                "message": "Invalid signature",
                "data": {"status": 401},
            },
        )

    monkeypatch.setattr(httpx, "request", auth_failure)
    auth_response = client.post("/api/v1/woocommerce/test-connection", headers=headers)
    assert auth_response.status_code == 200
    assert auth_response.json()["status"] == "auth_failed"
    assert "ck_test" not in auth_response.text
    assert "cs_test" not in auth_response.text
    assert "Invalid signature" in auth_response.json()["detail"]
    assert "status" in auth_response.json()["detail"]

    def network_failure(
        method: str,
        url: str,
        auth: tuple[str, str],
        json: dict | None = None,
        timeout: float | None = None,
        **kwargs: object,
    ) -> httpx.Response:
        assert method == "GET"
        assert kwargs.get("follow_redirects") is True
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx, "request", network_failure)
    network_response = client.post("/api/v1/woocommerce/test-connection", headers=headers)
    assert network_response.status_code == 200
    assert network_response.json()["status"] == "network_error"


def test_remote_request_retries_over_ipv4_after_unreachable_ipv6_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = "https://ipv6-unreachable.example.test/wp-json/wc/v3/products"
    origin = "https://ipv6-unreachable.example.test"
    woocommerce_services._REMOTE_FORCE_IPV4_ORIGINS.discard(origin)
    normal_calls: list[str] = []
    ipv4_calls: list[str] = []

    def unreachable_request(method: str, request_url: str, **_kwargs: object) -> httpx.Response:
        normal_calls.append(f"{method}:{request_url}")
        raise httpx.ConnectError("[Errno 101] Network is unreachable")

    def ipv4_request(method: str, request_url: str, **_kwargs: object) -> httpx.Response:
        ipv4_calls.append(f"{method}:{request_url}")
        return httpx.Response(200, json={"ok": True})

    monkeypatch.setattr(httpx, "request", unreachable_request)
    monkeypatch.setattr(woocommerce_services, "_remote_request_over_ipv4", ipv4_request)

    response = woocommerce_services._remote_request_with_retry("GET", url, timeout=1.0)

    assert response.status_code == 200
    assert normal_calls == [f"GET:{url}"]
    assert ipv4_calls == [f"GET:{url}"]
    assert origin in woocommerce_services._REMOTE_FORCE_IPV4_ORIGINS
    woocommerce_services._REMOTE_FORCE_IPV4_ORIGINS.discard(origin)


def test_woocommerce_connection_retries_query_auth_when_basic_auth_fails(
    harness: ApiHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = harness.client
    token, _company_id = complete_first_use_setup(client)
    headers = bearer(token)
    configure_store(client, headers)
    calls: list[tuple[str, tuple[str, str] | None]] = []

    def basic_auth_blocked(
        method: str,
        url: str,
        auth: tuple[str, str] | None = None,
        json: dict | None = None,
        timeout: float | None = None,
        **kwargs: object,
    ) -> httpx.Response:
        calls.append((url, auth))
        assert method == "GET"
        assert json is None
        assert kwargs.get("params") is None
        assert kwargs.get("follow_redirects") is True
        if auth is not None:
            return httpx.Response(
                401,
                json={
                    "code": "woocommerce_rest_cannot_view",
                    "message": "Sorry, you cannot list resources.",
                    "data": {"status": 401},
                },
            )

        params = query_params(url)
        assert params.get("consumer_key") == "ck_test_123456"
        assert params.get("consumer_secret") == "cs_test_123456"
        assert params.get("per_page") == "1"
        assert woocommerce_resource_path(url) in {
            "/products",
            "/products/categories",
            "/products/brands",
            "/customers",
            "/orders",
        }
        return httpx.Response(200, json=[])

    monkeypatch.setattr(httpx, "request", basic_auth_blocked)

    response = client.post("/api/v1/woocommerce/test-connection", headers=headers)

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert any(auth is not None for _url, auth in calls)
    assert any(auth is None for _url, auth in calls)


def test_woocommerce_connection_retries_after_basic_auth_timeout(
    harness: ApiHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = harness.client
    token, _company_id = complete_first_use_setup(client)
    headers = bearer(token)
    configure_store(client, headers)
    calls: list[tuple[str, tuple[str, str] | None]] = []

    def basic_auth_timeout_then_query_success(
        method: str,
        url: str,
        auth: tuple[str, str] | None = None,
        json: dict | None = None,
        timeout: float | None = None,
        **kwargs: object,
    ) -> httpx.Response:
        calls.append((url, auth))
        assert method == "GET"
        assert json is None
        assert kwargs.get("params") is None
        assert kwargs.get("follow_redirects") is True
        if auth is not None:
            raise httpx.ReadTimeout("timed out")

        params = query_params(url)
        assert params.get("consumer_key") == "ck_test_123456"
        assert params.get("consumer_secret") == "cs_test_123456"
        assert params.get("per_page") == "1"
        assert woocommerce_resource_path(url) in {
            "/products",
            "/products/categories",
            "/products/brands",
            "/customers",
            "/orders",
        }
        return httpx.Response(200, json=[])

    monkeypatch.setattr(httpx, "request", basic_auth_timeout_then_query_success)

    response = client.post("/api/v1/woocommerce/test-connection", headers=headers)

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert any(auth is not None for _url, auth in calls)
    assert any(auth is None for _url, auth in calls)


def test_woocommerce_bad_url_and_mapping_outbox_helpers(harness: ApiHarness) -> None:
    client = harness.client
    token, company_id = complete_first_use_setup(client)
    headers = bearer(token)

    bad_url = client.put(
        "/api/v1/woocommerce/config",
        headers=headers,
        json={
            "site_url": "not-a-url",
            "consumer_key": "ck_test_123456",
            "consumer_secret": "cs_test_123456",
        },
    )
    assert bad_url.status_code == 422

    with harness.session_factory() as db:
        mapping = upsert_external_resource_map(
            db,
            company_id=company_id,
            resource_type="product",
            internal_id="local-product-1",
            external_id="100",
            version="v1",
            metadata={"source": "test"},
        )
        updated_mapping = upsert_external_resource_map(
            db,
            company_id=company_id,
            resource_type="product",
            internal_id="local-product-2",
            external_id="100",
            version="v2",
            metadata={"source": "updated"},
        )
        assert updated_mapping.id == mapping.id
        found_mapping = get_external_resource_map(
            db,
            company_id=company_id,
            resource_type="product",
            external_id="100",
        )
        assert found_mapping is not None
        assert found_mapping.internal_resource_id == "local-product-2"

        outbox = enqueue_sync_outbox(
            db,
            company_id=company_id,
            operation="push",
            resource_type="product",
            resource_id="local-product-2",
            payload={"id": "local-product-2"},
            idempotency_key="woo:test:product:local-product-2",
        )
        duplicate_outbox = enqueue_sync_outbox(
            db,
            company_id=company_id,
            operation="push",
            resource_type="product",
            resource_id="local-product-2",
            payload={"id": "local-product-2"},
            idempotency_key="woo:test:product:local-product-2",
        )
        assert duplicate_outbox.id == outbox.id


def test_catalog_product_save_queues_woocommerce_push(harness: ApiHarness) -> None:
    client = harness.client
    token, company_id = complete_first_use_setup(client)
    headers = bearer(token)

    create_resp = client.post(
        "/api/v1/catalog/products",
        headers=headers,
        json={
            "name": "Queued ERP Product",
            "sku": "ERP-QUEUE-1",
            "variants": [
                {
                    "sku": "ERP-QUEUE-1-V",
                    "price_minor": 2500,
                }
            ],
        },
    )
    assert create_resp.status_code == 201
    product_id = create_resp.json()["id"]

    with harness.session_factory() as db:
        outbox = db.scalar(
            select(SyncOutbox).where(
                SyncOutbox.company_id == company_id,
                SyncOutbox.resource_type == "product",
                SyncOutbox.resource_id == product_id,
                SyncOutbox.operation == "push",
            )
        )
        assert outbox is not None
        assert outbox.status == "pending"
        assert outbox.payload["name"] == "Queued ERP Product"
        assert outbox.payload["status"] == "publish"
        assert outbox.payload["catalog_visibility"] == "visible"
        assert outbox.payload["regular_price"] == "25.00"


def test_product_push_crash_recovery_avoids_duplicate_remote_create(
    harness: ApiHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A crash after a remote product create must recover by SKU, not POST again."""

    client = harness.client
    token, company_id = complete_first_use_setup(client)
    headers = bearer(token)
    configure_store(client, headers)

    with harness.session_factory() as db:
        product = Product(
            company_id=company_id,
            name="Crash Recovery Product",
            slug="crash-recovery-product",
            sku="ERP-CRASH-RECOVERY",
            product_type="simple",
            status="active",
            metadata_json={},
        )
        db.add(product)
        db.flush()
        outbox = enqueue_product_sync(db, company_id=company_id, product=product)
        db.commit()
        outbox_id = outbox.id
        product_id = product.id

    post_count = 0

    def crash_after_remote_create(
        method: str,
        url: str,
        auth: tuple[str, str] | None = None,
        json: dict | None = None,
        timeout: float | None = None,
        **kwargs: object,
    ) -> httpx.Response:
        nonlocal post_count
        assert kwargs.get("follow_redirects") is True
        if method == "POST" and woocommerce_resource_path(url) == "/products":
            post_count += 1
            # The remote system accepted the product, then the ERP process died
            # before it could store the map or final outbox checkpoint.
            raise SystemExit("simulated process crash after remote product create")
        raise AssertionError(f"Unexpected request before recovery: {method} {url}")

    monkeypatch.setattr(httpx, "request", crash_after_remote_create)
    with harness.session_factory() as db:
        with pytest.raises(SystemExit, match="simulated process crash"):
            process_sync_outbox(db, company_id)

    with harness.session_factory() as db:
        outbox = db.get(SyncOutbox, outbox_id)
        assert outbox is not None
        assert outbox.status == "processing"
        assert outbox.attempts == 1
        # Make the durable claim old enough for ordinary restart recovery; the
        # retry is then eligible immediately at the worker's real clock.
        outbox.updated_at = utcnow() - timedelta(seconds=SYNC_OUTBOX_STALE_SECONDS + 1)
        db.commit()
        recovered = recover_stale_woocommerce_sync_records(db)
        assert recovered["recovered_outbox"] == 1
        db.commit()

    put_count = 0

    def recover_remote_product(
        method: str,
        url: str,
        auth: tuple[str, str] | None = None,
        json: dict | None = None,
        timeout: float | None = None,
        **kwargs: object,
    ) -> httpx.Response:
        nonlocal post_count, put_count
        assert kwargs.get("follow_redirects") is True
        resource_path = woocommerce_resource_path(url)
        if method == "GET" and resource_path == "/products":
            assert query_params(url).get("sku") == "ERP-CRASH-RECOVERY"
            return httpx.Response(200, json=[{"id": 711, "sku": "ERP-CRASH-RECOVERY"}])
        if method == "PUT" and url.endswith("/wp-json/wc/v3/products/711"):
            put_count += 1
            return httpx.Response(200, json={"id": 711, "name": "Crash Recovery Product"})
        if method == "POST" and resource_path == "/products":
            post_count += 1
            raise AssertionError("Recovery must not create a second remote product")
        raise AssertionError(f"Unexpected recovery request: {method} {url}")

    monkeypatch.setattr(httpx, "request", recover_remote_product)
    with harness.session_factory() as db:
        result = process_sync_outbox(db, company_id)
        assert result == {
            "pushed": 1,
            "pushed_media": 0,
            "pushed_videos": 0,
            "failed": 0,
            "deferred": 0,
            "deferred_videos": 0,
        }

    with harness.session_factory() as db:
        outbox = db.get(SyncOutbox, outbox_id)
        mapping = db.scalar(
            select(ExternalResourceMap).where(
                ExternalResourceMap.company_id == company_id,
                ExternalResourceMap.internal_resource_id == product_id,
                ExternalResourceMap.internal_resource_type == "product",
            )
        )
        assert outbox is not None
        assert outbox.status == "synced"
        assert outbox.attempts == 2
        assert mapping is not None
        assert mapping.external_resource_id == "711"
    assert post_count == 1
    assert put_count == 1


def test_paged_product_pull_renews_progress_for_remote_pages_and_local_batches(
    harness: ApiHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = harness.client
    token, company_id = complete_first_use_setup(client)
    configure_store(client, bearer(token))

    first_page = [
        {"id": index, "name": f"Paged Product {index}", "sku": f"PAGED-{index}"}
        for index in range(1, 101)
    ]
    second_page = [
        {"id": index, "name": f"Paged Product {index}", "sku": f"PAGED-{index}"}
        for index in range(101, 103)
    ]

    def mock_request(
        method: str,
        url: str,
        auth: tuple[str, str] | None = None,
        json: dict | None = None,
        timeout: float | None = None,
        **kwargs: object,
    ) -> httpx.Response:
        assert method == "GET"
        assert kwargs.get("follow_redirects") is True
        assert woocommerce_resource_path(url) == "/products"
        assert query_params(url).get("per_page") == "100"
        assert query_params(url).get("orderby") == "id"
        assert query_params(url).get("order") == "asc"
        assert "modified_after" not in query_params(url)
        if query_params(url).get("page") == "1":
            return httpx.Response(200, json=first_page)
        if query_params(url).get("page") == "2":
            return httpx.Response(200, json=second_page)
        raise AssertionError(f"Unexpected WooCommerce page: {url}")

    monkeypatch.setattr(httpx, "request", mock_request)
    checkpoint_count = 0
    with harness.session_factory() as db:

        def checkpoint() -> None:
            nonlocal checkpoint_count
            checkpoint_count += 1
            db.commit()

        result = pull_products(db, company_id, progress_callback=checkpoint)
        assert result == {"pulled": 102}
        db.commit()

    # Every downloaded page is processed and committed before the next one is
    # requested, so products are never accumulated in one in-memory list.
    assert checkpoint_count == 2
    with harness.session_factory() as db:
        product_ids = db.scalars(select(Product.id).where(Product.company_id == company_id)).all()
        assert len(product_ids) == 102
        assert get_woocommerce_last_sync(db, company_id, "product") is not None


def test_product_pull_uses_incremental_checkpoint_and_force_full_can_ignore_it(
    harness: ApiHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = harness.client
    token, company_id = complete_first_use_setup(client)
    headers = bearer(token)
    configure_store(client, headers)
    previous_timestamp = "2026-07-26T10:11:12.987654Z"
    sync_started_at = datetime(2026, 7, 27, 9, 8, 7, 654321, tzinfo=UTC)
    with harness.session_factory() as db:
        setting = db.scalar(select(Setting).where(Setting.key == WOOCOMMERCE_SETTING_KEY))
        assert setting is not None
        value = dict(setting.value)
        value["last_products_sync"] = previous_timestamp
        value["unrelated_connector_option"] = {"keep": True}
        setting.value = value
        db.commit()

    requests: list[dict[str, str]] = []

    def empty_products(
        method: str,
        url: str,
        auth: tuple[str, str] | None = None,
        json: dict | None = None,
        timeout: float | None = None,
        **kwargs: object,
    ) -> httpx.Response:
        assert method == "GET"
        assert woocommerce_resource_path(url) == "/products"
        requests.append(query_params(url))
        return httpx.Response(200, json=[])

    monkeypatch.setattr(httpx, "request", empty_products)
    monkeypatch.setattr(woocommerce_services, "utcnow", lambda: sync_started_at)
    with harness.session_factory() as db:
        assert pull_products(db, company_id) == {"pulled": 0}
        db.commit()
        incremental_timestamp = get_woocommerce_last_sync(db, company_id, "product")
        assert incremental_timestamp == "2026-07-27T09:08:07.654321Z"
        assert (
            woocommerce_services._woocommerce_incremental_after(incremental_timestamp)
            == "2026-07-27T09:08:06Z"
        )

    assert requests[-1]["modified_after"] == "2026-07-26T10:11:11Z"
    # The strict upper bound excludes the captured second, preventing records
    # modified after sync_start from entering and shifting later offset pages.
    # The next run's lower one-second overlap retrieves this deferred second.
    assert requests[-1]["modified_before"] == "2026-07-27T09:08:07Z"
    assert requests[-1]["dates_are_gmt"] == "true"
    assert requests[-1]["orderby"] == "modified"
    assert requests[-1]["order"] == "asc"
    with harness.session_factory() as db:
        setting = db.scalar(select(Setting).where(Setting.key == WOOCOMMERCE_SETTING_KEY))
        assert setting is not None
        assert setting.value["unrelated_connector_option"] == {"keep": True}

    with harness.session_factory() as db:
        assert pull_products(db, company_id, force_full=True) == {"pulled": 0}
        db.commit()

    assert "modified_after" not in requests[-1]
    assert requests[-1]["orderby"] == "id"
    assert requests[-1]["order"] == "asc"

    # Saving credentials again must preserve the existing inbound checkpoint.
    configure_store(client, headers)
    with harness.session_factory() as db:
        assert get_woocommerce_last_sync(db, company_id, "product") is not None


def test_failed_later_product_page_preserves_previous_checkpoint(
    harness: ApiHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = harness.client
    token, company_id = complete_first_use_setup(client)
    configure_store(client, bearer(token))
    previous_timestamp = "2026-07-25T01:02:03Z"
    with harness.session_factory() as db:
        setting = db.scalar(select(Setting).where(Setting.key == WOOCOMMERCE_SETTING_KEY))
        assert setting is not None
        value = dict(setting.value)
        value["last_products_sync"] = previous_timestamp
        setting.value = value
        db.commit()

    monkeypatch.setattr(woocommerce_services, "sync_single_product", lambda *_args: None)
    monkeypatch.setattr(woocommerce_services, "_woocommerce_product_exists", lambda *_args: False)
    requested_pages: list[dict[str, str]] = []

    def fail_second_page(
        method: str,
        url: str,
        auth: tuple[str, str] | None = None,
        json: dict | None = None,
        timeout: float | None = None,
        **kwargs: object,
    ) -> httpx.Response:
        params = query_params(url)
        requested_pages.append(params)
        if params["page"] == "1":
            return httpx.Response(200, json=[{"id": index} for index in range(100)])
        return httpx.Response(500, json={"message": "second page failed"})

    monkeypatch.setattr(httpx, "request", fail_second_page)
    checkpoint_count = 0
    with harness.session_factory() as db:

        def checkpoint() -> None:
            nonlocal checkpoint_count
            checkpoint_count += 1
            db.commit()

        with pytest.raises(woocommerce_services.ServiceError, match="second page failed"):
            pull_products(db, company_id, progress_callback=checkpoint)

    assert checkpoint_count == 1
    assert [params["modified_after"] for params in requested_pages] == [
        "2026-07-25T01:02:02Z",
        "2026-07-25T01:02:02Z",
    ]
    with harness.session_factory() as db:
        assert get_woocommerce_last_sync(db, company_id, "product") == previous_timestamp


def test_failed_product_item_preserves_previous_checkpoint(
    harness: ApiHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = harness.client
    token, company_id = complete_first_use_setup(client)
    configure_store(client, bearer(token))
    previous_timestamp = "2026-07-24T01:02:03Z"
    with harness.session_factory() as db:
        setting = db.scalar(select(Setting).where(Setting.key == WOOCOMMERCE_SETTING_KEY))
        assert setting is not None
        value = dict(setting.value)
        value["last_products_sync"] = previous_timestamp
        setting.value = value
        db.commit()

    def sync_item(_db: Session, _company_id: str, item: dict) -> None:
        if item["id"] == 2:
            raise ValueError("item import failed")

    monkeypatch.setattr(woocommerce_services, "sync_single_product", sync_item)
    monkeypatch.setattr(woocommerce_services, "_woocommerce_product_exists", lambda *_args: False)
    monkeypatch.setattr(
        httpx,
        "request",
        lambda *_args, **_kwargs: httpx.Response(200, json=[{"id": 1}, {"id": 2}]),
    )
    checkpoint_count = 0
    with harness.session_factory() as db:

        def checkpoint() -> None:
            nonlocal checkpoint_count
            checkpoint_count += 1
            db.commit()

        with pytest.raises(ValueError, match="item import failed"):
            pull_products(db, company_id, progress_callback=checkpoint)
        db.rollback()

    assert checkpoint_count == 0
    with harness.session_factory() as db:
        assert get_woocommerce_last_sync(db, company_id, "product") == previous_timestamp


def test_orders_are_incremental_but_customers_remain_full_sync(
    harness: ApiHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = harness.client
    token, company_id = complete_first_use_setup(client)
    configure_store(client, bearer(token))
    order_timestamp = "2026-07-23T04:05:06Z"
    legacy_customer_timestamp = "2026-07-22T03:04:05Z"
    with harness.session_factory() as db:
        setting = db.scalar(select(Setting).where(Setting.key == WOOCOMMERCE_SETTING_KEY))
        assert setting is not None
        value = dict(setting.value)
        value["last_orders_sync"] = order_timestamp
        value["last_customers_sync"] = legacy_customer_timestamp
        value["unrelated_connector_option"] = "preserved"
        setting.value = value
        db.commit()

    requests: list[tuple[str, dict[str, str]]] = []

    def empty_collections(
        method: str,
        url: str,
        auth: tuple[str, str] | None = None,
        json: dict | None = None,
        timeout: float | None = None,
        **kwargs: object,
    ) -> httpx.Response:
        resource_path = woocommerce_resource_path(url)
        requests.append((resource_path, query_params(url)))
        return httpx.Response(200, json=[])

    monkeypatch.setattr(httpx, "request", empty_collections)
    with harness.session_factory() as db:
        assert pull_orders(db, company_id) == {"pulled": 0}
        db.commit()
        new_order_timestamp = get_woocommerce_last_sync(db, company_id, "order")
        assert new_order_timestamp is not None
        assert new_order_timestamp != order_timestamp

    order_params = next(params for path, params in requests if path == "/orders")
    assert order_params["modified_after"] == "2026-07-23T04:05:05Z"
    assert order_params["modified_before"]
    assert order_params["dates_are_gmt"] == "true"
    assert order_params["orderby"] == "modified"
    assert order_params["order"] == "asc"

    with harness.session_factory() as db:
        assert pull_customers(db, company_id) == {"pulled": 0}
        db.commit()

    customer_params = next(params for path, params in requests if path == "/customers")
    assert "modified_after" not in customer_params
    assert "modified_before" not in customer_params
    assert customer_params["orderby"] == "id"
    assert customer_params["order"] == "asc"
    with harness.session_factory() as db:
        setting = db.scalar(select(Setting).where(Setting.key == WOOCOMMERCE_SETTING_KEY))
        assert setting is not None
        assert "last_customers_sync" not in setting.value
        assert setting.value["unrelated_connector_option"] == "preserved"
        assert get_woocommerce_last_sync(db, company_id, "customer") is None


def test_reconciliation_processes_all_id_pages_and_is_company_scoped(
    harness: ApiHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = harness.client
    token, company_id = complete_first_use_setup(client)
    configure_store(client, bearer(token))
    other_company_id = "other-reconciliation-company"
    with harness.session_factory() as db:
        db.add(Company(id=other_company_id, name="Other Reconciliation Co", status="active"))
        present = Product(company_id=company_id, name="Present", slug="present", sku="PRESENT")
        missing = Product(company_id=company_id, name="Missing", slug="missing", sku="MISSING")
        other = Product(
            company_id=other_company_id,
            name="Other Company Product",
            slug="other-company-product",
            sku="OTHER-COMPANY",
        )
        other_connector = Product(
            company_id=company_id,
            name="Other Connector Product",
            slug="other-connector-product",
            sku="OTHER-CONNECTOR",
        )
        wrong_resource_type = Product(
            company_id=company_id,
            name="Wrong Resource Type Product",
            slug="wrong-resource-type-product",
            sku="WRONG-RESOURCE-TYPE",
        )
        db.add_all([present, missing, other, other_connector, wrong_resource_type])
        db.flush()
        upsert_external_resource_map(
            db,
            company_id=company_id,
            resource_type="product",
            internal_id=present.id,
            external_id="1",
        )
        upsert_external_resource_map(
            db,
            company_id=company_id,
            resource_type="product",
            internal_id=missing.id,
            external_id="999",
        )
        upsert_external_resource_map(
            db,
            company_id=other_company_id,
            resource_type="product",
            internal_id=other.id,
            external_id="888",
        )
        db.add(
            ExternalResourceMap(
                company_id=company_id,
                connector="woocommerce-other-store",
                internal_resource_type="product",
                internal_resource_id=other_connector.id,
                external_resource_type="product",
                external_resource_id="777",
            )
        )
        db.add(
            ExternalResourceMap(
                company_id=company_id,
                connector="woocommerce",
                internal_resource_type="product",
                internal_resource_id=wrong_resource_type.id,
                external_resource_type="customer",
                external_resource_id="666",
            )
        )
        db.commit()
        present_id = present.id
        missing_id = missing.id
        other_id = other.id
        other_connector_id = other_connector.id
        wrong_resource_type_id = wrong_resource_type.id

    requested_pages: list[dict[str, str]] = []

    def product_id_pages(
        method: str,
        url: str,
        auth: tuple[str, str] | None = None,
        json: dict | None = None,
        timeout: float | None = None,
        **kwargs: object,
    ) -> httpx.Response:
        params = query_params(url)
        requested_pages.append(params)
        if params["page"] == "1":
            return httpx.Response(200, json=[{"id": index} for index in range(1, 101)])
        if params["page"] == "2":
            return httpx.Response(200, json=[{"id": 101}])
        raise AssertionError(f"Unexpected reconciliation page: {url}")

    monkeypatch.setattr(httpx, "request", product_id_pages)
    with harness.session_factory() as db:
        result = reconcile_products(db, company_id, progress_callback=db.commit)
        db.commit()

    assert result == {"remote_ids": 101, "archived": 1, "skipped": 0}
    assert [params["page"] for params in requested_pages] == ["1", "2"]
    assert all(params["_fields"] == "id" for params in requested_pages)
    assert all("modified_after" not in params for params in requested_pages)
    assert all(params["orderby"] == "id" for params in requested_pages)
    assert all(params["order"] == "asc" for params in requested_pages)
    with harness.session_factory() as db:
        assert db.get(Product, present_id).status != "archived"
        assert db.get(Product, missing_id).status == "archived"
        assert db.get(Product, other_id).status != "archived"
        assert db.get(Product, other_connector_id).status != "archived"
        assert db.get(Product, wrong_resource_type_id).status != "archived"


def test_manual_product_modes_are_available_without_changing_default_api(
    harness: ApiHarness,
) -> None:
    client = harness.client
    token, _company_id = complete_first_use_setup(client)
    headers = bearer(token)
    configure_store(client, headers)

    response = client.post(
        "/api/v1/woocommerce/sync?mode=full_products",
        headers=headers,
    )
    assert response.status_code == 202
    assert response.json()["direction"] == "inbound"
    assert response.json()["stats"]["sync_mode"] == "full_products"

    invalid = client.post("/api/v1/woocommerce/sync?mode=unknown", headers=headers)
    assert invalid.status_code == 422


def test_products_mode_pushes_catalog_before_admin_product_pull(
    harness: ApiHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = harness.client
    token, company_id = complete_first_use_setup(client)
    headers = bearer(token)
    configure_store(client, headers)

    with harness.session_factory() as db:
        category = Category(
            company_id=company_id,
            name="ERP Chargers",
            slug="erp-chargers",
            is_active=True,
        )
        brand = Brand(
            company_id=company_id,
            name="ERP Brand",
            slug="erp-brand",
            is_active=True,
        )
        db.add_all([category, brand])
        db.flush()
        product = Product(
            company_id=company_id,
            category_id=category.id,
            brand_id=brand.id,
            name="ERP Charger",
            slug="erp-charger",
            sku="ERP-CHARGER-1",
            product_type="simple",
            status="active",
            regular_price_minor=2500,
            metadata_json={},
        )
        db.add(product)
        db.flush()
        db.add(
            ProductCategoryLink(
                company_id=company_id,
                product_id=product.id,
                category_id=category.id,
                is_primary=True,
                sort_order=0,
            )
        )
        db.commit()

    requests: list[tuple[str, str]] = []
    product_payloads: list[dict[str, object]] = []

    def mock_request(
        method: str,
        url: str,
        auth: tuple[str, str] | None = None,
        json: dict | None = None,
        timeout: float | None = None,
        **kwargs: object,
    ) -> httpx.Response:
        assert kwargs.get("follow_redirects") is True
        resource_path = woocommerce_resource_path(url)
        requests.append((method, resource_path))
        params = query_params(url)
        if method == "GET" and resource_path in {"/products/categories", "/products/brands"}:
            if "slug" in params:
                return httpx.Response(200, json=[])
            return httpx.Response(200, json=[])
        if method == "POST" and resource_path == "/products/categories":
            return httpx.Response(201, json={"id": 901, "name": json["name"]})
        if method == "PUT" and resource_path == "/products/categories/901":
            return httpx.Response(200, json={"id": 901, "name": json["name"]})
        if method == "POST" and resource_path == "/products/brands":
            return httpx.Response(201, json={"id": 902, "name": json["name"]})
        if method == "PUT" and resource_path == "/products/brands/902":
            return httpx.Response(200, json={"id": 902, "name": json["name"]})
        if method == "POST" and resource_path == "/products":
            product_payloads.append(json or {})
            return httpx.Response(201, json={"id": 903, "name": json["name"]})
        if method == "GET" and resource_path == "/products":
            return httpx.Response(200, json=[])
        raise AssertionError(f"Unexpected request: {method} {url}")

    monkeypatch.setattr(httpx, "request", mock_request)
    queued, completed = queue_and_process_sync(harness, headers, mode="products")

    assert queued["direction"] == "both"
    assert completed["status"] == "success"
    assert completed["stats"]["pushed_records"] == 1
    assert completed["stats"]["synced_categories"] == 1
    assert completed["stats"]["synced_brands"] == 1
    assert product_payloads[0]["categories"] == [{"id": 901}]
    assert product_payloads[0]["brands"] == [{"id": 902}]
    assert ("POST", "/products") in requests
    assert ("GET", "/products") in requests

    with harness.session_factory() as db:
        taxonomy_maps = db.scalars(
            select(ExternalResourceMap).where(
                ExternalResourceMap.company_id == company_id,
                ExternalResourceMap.connector == "woocommerce",
                ExternalResourceMap.external_resource_type.in_({"category", "brand"}),
            )
        ).all()
        assert {mapping.external_resource_id for mapping in taxonomy_maps} == {"901", "902"}


def test_vendor_products_mode_pushes_only_vendor_catalog(
    harness: ApiHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = harness.client
    token, company_id = complete_first_use_setup(client)
    configure_store(client, bearer(token))

    with harness.session_factory() as db:
        vendor = Vendor(
            company_id=company_id,
            name="Scoped Vendor",
            slug="scoped-vendor",
            status="active",
        )
        category = Category(
            company_id=company_id,
            name="Vendor Chargers",
            slug="vendor-chargers",
            is_active=True,
        )
        brand = Brand(
            company_id=company_id,
            name="Vendor Brand",
            slug="vendor-brand",
            is_active=True,
        )
        db.add_all([vendor, category, brand])
        db.flush()
        owned = Product(
            company_id=company_id,
            vendor_id=vendor.id,
            category_id=category.id,
            brand_id=brand.id,
            name="Owned Product",
            slug="owned-product",
            sku="OWNED-1",
            product_type="simple",
            status="active",
            regular_price_minor=1000,
            metadata_json={},
        )
        other = Product(
            company_id=company_id,
            name="Other Product",
            slug="other-product",
            sku="OTHER-1",
            product_type="simple",
            status="active",
            regular_price_minor=2000,
            metadata_json={},
        )
        db.add_all([owned, other])
        db.flush()
        db.add(
            ProductChannelListing(
                company_id=company_id,
                product_id=owned.id,
                vendor_id=vendor.id,
                channel="woocommerce",
                listing_status="published",
                sync_status="pending",
            )
        )
        db.add(
            ProductCategoryLink(
                company_id=company_id,
                product_id=owned.id,
                category_id=category.id,
                is_primary=True,
                sort_order=0,
            )
        )
        db.commit()
        vendor_id = vendor.id

    pushed_names: list[str] = []

    def mock_request(
        method: str,
        url: str,
        auth: tuple[str, str] | None = None,
        json: dict | None = None,
        timeout: float | None = None,
        **kwargs: object,
    ) -> httpx.Response:
        assert kwargs.get("follow_redirects") is True
        resource_path = woocommerce_resource_path(url)
        params = query_params(url)
        if method == "GET" and resource_path in {"/products/categories", "/products/brands"}:
            return httpx.Response(200, json=[])
        if method == "POST" and resource_path == "/products/categories":
            return httpx.Response(201, json={"id": 911})
        if method == "PUT" and resource_path == "/products/categories/911":
            return httpx.Response(200, json={"id": 911})
        if method == "POST" and resource_path == "/products/brands":
            return httpx.Response(201, json={"id": 912})
        if method == "PUT" and resource_path == "/products/brands/912":
            return httpx.Response(200, json={"id": 912})
        if method == "POST" and resource_path == "/products":
            pushed_names.append(str(json["name"]))
            return httpx.Response(201, json={"id": 913, "name": json["name"]})
        if method == "GET" and resource_path == "/products":
            raise AssertionError(f"Vendor products mode must not pull products: {params}")
        raise AssertionError(f"Unexpected request: {method} {url}")

    monkeypatch.setattr(httpx, "request", mock_request)
    with harness.session_factory() as db:
        run = run_woocommerce_sync(
            db,
            company_id,
            sync_mode="products",
            vendor_id=vendor_id,
        )
        db.commit()

    assert run.status == "success"
    assert run.direction == "outbound"
    assert run.stats["pushed_records"] == 1
    assert run.stats["pulled_products"] == 0
    assert pushed_names == ["Owned Product"]


def test_products_mode_reports_failed_outbox_work(
    harness: ApiHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = harness.client
    token, company_id = complete_first_use_setup(client)
    headers = bearer(token)
    configure_store(client, headers)

    with harness.session_factory() as db:
        db.add(
            Product(
                company_id=company_id,
                name="Unpublishable Product",
                slug="unpublishable-product",
                sku="UNPUBLISHABLE-1",
                product_type="simple",
                status="active",
                regular_price_minor=1000,
                metadata_json={},
            )
        )
        db.commit()

    def failing_request(
        method: str,
        url: str,
        auth: tuple[str, str] | None = None,
        json: dict | None = None,
        timeout: float | None = None,
        **kwargs: object,
    ) -> httpx.Response:
        assert kwargs.get("follow_redirects") is True
        resource_path = woocommerce_resource_path(url)
        if method == "POST" and resource_path == "/products":
            return httpx.Response(500, json={"code": "store_error", "message": "Store failed."})
        if method == "GET" and resource_path in {
            "/products/categories",
            "/products/brands",
            "/products",
        }:
            return httpx.Response(200, json=[])
        raise AssertionError(f"Unexpected request: {method} {url}")

    monkeypatch.setattr(httpx, "request", failing_request)
    _queued, completed = queue_and_process_sync(harness, headers, mode="products")

    assert completed["status"] == "failed"
    assert completed["stats"]["failed_product_pushes"] == 1
    assert "unresolved outbound work" in completed["error"]


def test_taxonomy_sync_resolves_existing_and_term_exists_ids(
    harness: ApiHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = harness.client
    token, company_id = complete_first_use_setup(client)
    configure_store(client, bearer(token))

    with harness.session_factory() as db:
        category = Category(
            company_id=company_id,
            name="Existing Category",
            slug="existing-category",
            is_active=True,
        )
        brand = Brand(
            company_id=company_id,
            name="Existing Brand",
            slug="existing-brand",
            is_active=True,
        )
        db.add_all([category, brand])
        db.flush()
        category_id = category.id
        brand_id = brand.id
        db.commit()

    calls: list[tuple[str, str]] = []

    def mock_request(
        method: str,
        url: str,
        auth: tuple[str, str] | None = None,
        json: dict | None = None,
        timeout: float | None = None,
        **kwargs: object,
    ) -> httpx.Response:
        assert kwargs.get("follow_redirects") is True
        resource_path = woocommerce_resource_path(url)
        calls.append((method, resource_path))
        if method == "GET" and resource_path == "/products/categories":
            return httpx.Response(200, json=[{"id": 930, "name": "Existing Category"}])
        if method == "PUT" and resource_path == "/products/categories/930":
            return httpx.Response(200, json={"id": 930})
        if method == "GET" and resource_path == "/products/brands":
            return httpx.Response(200, json=[])
        if method == "POST" and resource_path == "/products/brands":
            return httpx.Response(
                400,
                json={"code": "term_exists", "data": {"resource_id": 931}},
            )
        if method == "PUT" and resource_path == "/products/brands/931":
            return httpx.Response(200, json={"id": 931})
        raise AssertionError(f"Unexpected request: {method} {url}")

    monkeypatch.setattr(httpx, "request", mock_request)
    with harness.session_factory() as db:
        category_row = db.get(Category, category_id)
        brand_row = db.get(Brand, brand_id)
        assert category_row is not None
        assert brand_row is not None
        assert ensure_remote_category(db, company_id=company_id, category=category_row) == "930"
        assert ensure_remote_brand(db, company_id=company_id, brand=brand_row) == "931"
        db.commit()

    with harness.session_factory() as db:
        mappings = db.scalars(
            select(ExternalResourceMap).where(
                ExternalResourceMap.company_id == company_id,
                ExternalResourceMap.external_resource_type.in_({"category", "brand"}),
            )
        ).all()
        assert {mapping.external_resource_id for mapping in mappings} == {"930", "931"}
    assert ("POST", "/products/categories") not in calls
    assert ("POST", "/products/brands") in calls


def test_woocommerce_sync_backfills_existing_catalog_products(
    harness: ApiHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = harness.client
    token, company_id = complete_first_use_setup(client)
    headers = bearer(token)

    local_image_path = Path(get_settings().media_upload_dir) / "products" / "local-only.jpg"
    local_image_path.parent.mkdir(parents=True, exist_ok=True)
    local_image_path.write_bytes(b"\x89PNG\r\n\x1a\nlocal")

    with harness.session_factory() as db:
        product = Product(
            company_id=company_id,
            name="Existing ERP Product",
            slug="existing-erp-product",
            sku="ERP-100",
            product_type="simple",
            status="active",
            metadata_json={},
        )
        db.add(product)
        db.flush()
        db.add(
            ProductVariant(
                company_id=company_id,
                product_id=product.id,
                name="Default",
                sku="ERP-100-1",
                price_minor=1299,
                currency="PKR",
                attributes={},
                is_active=True,
            )
        )
        db.add(
            ProductImage(
                company_id=company_id,
                product_id=product.id,
                url="https://assets.example.test/erp-product.jpg",
                alt_text="Existing ERP Product",
                sort_order=0,
            )
        )
        db.add(
            ProductImage(
                company_id=company_id,
                product_id=product.id,
                url="/media/products/local-only.jpg",
                alt_text="Local only",
                sort_order=1,
            )
        )
        db.commit()
        product_id = product.id

    configure_store(client, headers, wordpress_media=True)

    product_payloads: list[dict[str, object]] = []
    media_payloads: list[dict[str, object]] = []
    media_uploads: list[dict[str, object]] = []

    def mock_request(
        method: str,
        url: str,
        auth: tuple[str, str] | None = None,
        json: dict | None = None,
        timeout: float | None = None,
        **kwargs: object,
    ) -> httpx.Response:
        assert kwargs.get("follow_redirects") is True
        if method == "POST" and url.endswith("/wp-json/wp/v2/media"):
            media_uploads.append(
                {
                    "auth": auth,
                    "content": kwargs.get("content"),
                    "headers": kwargs.get("headers"),
                }
            )
            return httpx.Response(
                201,
                json={
                    "id": 701,
                    "source_url": "https://shop.example.test/wp-content/uploads/local-only.jpg",
                },
            )
        if method == "POST" and url.endswith("/wp-json/wc/v3/products"):
            product_payloads.append(json or {})
            return httpx.Response(
                201,
                json={
                    "id": 501,
                    "name": json.get("name"),
                    "sku": json.get("sku"),
                },
            )
        if method == "GET" and url.endswith("/wp-json/wc/v3/products/501"):
            return httpx.Response(
                200,
                json={
                    "id": 501,
                    "images": [
                        {
                            "id": 700,
                            "src": "https://assets.example.test/erp-product.jpg",
                        }
                    ],
                },
            )
        if method == "PUT" and url.endswith("/wp-json/wc/v3/products/501"):
            media_payloads.append(json or {})
            return httpx.Response(
                200,
                json={
                    "id": 501,
                    "images": [
                        {
                            "id": 700,
                            "src": "https://assets.example.test/erp-product.jpg",
                            "alt": "Existing ERP Product",
                        },
                        {
                            "id": 701,
                            "src": "https://shop.example.test/wp-content/uploads/local-only.jpg",
                            "alt": "Local only",
                        },
                    ],
                },
            )
        if method == "GET" and woocommerce_resource_path(url) == "/products":
            assert query_params(url).get("per_page") == "100"
            assert query_params(url).get("page") == "1"
            return httpx.Response(200, json=[])
        if method == "GET" and woocommerce_resource_path(url) == "/customers":
            assert query_params(url).get("per_page") == "100"
            assert query_params(url).get("page") == "1"
            return httpx.Response(200, json=[])
        if method == "GET" and woocommerce_resource_path(url) == "/orders":
            assert query_params(url).get("per_page") == "100"
            assert query_params(url).get("page") == "1"
            return httpx.Response(200, json=[])
        return httpx.Response(404, json={"code": "rest_no_route", "message": "No route."})

    monkeypatch.setattr(httpx, "request", mock_request)

    queued_sync, sync_data = queue_and_process_sync(harness, headers)
    assert queued_sync["status"] == "queued"
    assert sync_data["status"] == "success"
    assert sync_data["stats"]["pushed_records"] == 1
    assert sync_data["stats"]["pushed_media_records"] == 1
    assert product_payloads
    assert media_payloads

    payload = product_payloads[0]
    assert payload["name"] == "Existing ERP Product"
    assert payload["status"] == "publish"
    assert payload["catalog_visibility"] == "visible"
    assert payload["regular_price"] == "12.99"
    assert "images" not in payload
    assert len(media_uploads) == 1
    assert media_uploads[0]["auth"] == ("choiceoye", "wp-app-pass-123456")
    assert media_uploads[0]["content"] == b"\x89PNG\r\n\x1a\nlocal"
    assert media_payloads[0]["images"] == [
        {"id": 700, "alt": "Existing ERP Product"},
        {"id": 701, "alt": "Local only"},
    ]

    with harness.session_factory() as db:
        mapping = db.scalar(
            select(ExternalResourceMap).where(
                ExternalResourceMap.company_id == company_id,
                ExternalResourceMap.internal_resource_id == product_id,
                ExternalResourceMap.internal_resource_type == "product",
            )
        )
        assert mapping is not None
        assert mapping.external_resource_id == "501"
        uploaded_image = db.scalar(
            select(ProductImage).where(
                ProductImage.company_id == company_id,
                ProductImage.external_id == "701",
            )
        )
        assert uploaded_image is not None
        assert uploaded_image.url == "https://shop.example.test/wp-content/uploads/local-only.jpg"
        assert uploaded_image.sync_status == "synced"


def test_woocommerce_sync_processes_existing_pending_product_and_media_jobs(
    harness: ApiHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = harness.client
    token, company_id = complete_first_use_setup(client)
    headers = bearer(token)

    local_image_path = Path(get_settings().media_upload_dir) / "products" / "pending-recovery.png"
    local_image_path.parent.mkdir(parents=True, exist_ok=True)
    local_image_path.write_bytes(b"\x89PNG\r\n\x1a\nrecover")

    with harness.session_factory() as db:
        product = Product(
            company_id=company_id,
            name="Pending Media Product",
            slug="pending-media-product",
            sku="ERP-RECOVER",
            product_type="simple",
            status="active",
            metadata_json={},
        )
        db.add(product)
        db.flush()
        db.add(
            ProductVariant(
                company_id=company_id,
                product_id=product.id,
                name="Default",
                sku="ERP-RECOVER-1",
                price_minor=2199,
                currency="PKR",
                attributes={},
                is_active=True,
            )
        )
        db.add(
            ProductImage(
                company_id=company_id,
                product_id=product.id,
                url="/media/products/pending-recovery.png",
                name="pending-recovery.png",
                alt_text="Recover media",
                sort_order=0,
                sync_status="pending_add",
            )
        )
        db.flush()
        enqueue_product_sync(db, company_id=company_id, product=product)
        stale_media = enqueue_sync_outbox(
            db,
            company_id=company_id,
            operation="push_media",
            resource_type="product",
            resource_id=product.id,
            payload={"images": [{"stale": True}]},
            idempotency_key=f"test:stale-media:{product.id}",
        )
        stale_media.status = "failed"
        stale_media.attempts = 3
        stale_media.last_error = "Old stale media failure"
        db.commit()
        product_id = product.id

    configure_store(client, headers, wordpress_media=True)

    config_before = client.get("/api/v1/woocommerce/config", headers=headers)
    assert config_before.status_code == 200
    assert config_before.json()["pending_product_pushes"] == 1
    assert config_before.json()["pending_media_pushes"] == 1
    assert config_before.json()["failed_media_pushes"] == 1
    assert config_before.json()["last_media_error"] == "Old stale media failure"

    product_payloads: list[dict[str, object]] = []
    media_payloads: list[dict[str, object]] = []
    media_uploads: list[bytes] = []

    def mock_request(
        method: str,
        url: str,
        auth: tuple[str, str] | None = None,
        json: dict | None = None,
        timeout: float | None = None,
        **kwargs: object,
    ) -> httpx.Response:
        assert kwargs.get("follow_redirects") is True
        if method == "GET" and woocommerce_resource_path(url) in {
            "/products/categories",
            "/products/brands",
        }:
            return httpx.Response(200, json=[])
        if method == "POST" and url.endswith("/wp-json/wc/v3/products"):
            product_payloads.append(json or {})
            return httpx.Response(201, json={"id": 601, "name": json.get("name")})
        if method == "POST" and url.endswith("/wp-json/wp/v2/media"):
            assert auth == ("choiceoye", "wp-app-pass-123456")
            media_uploads.append(kwargs.get("content") or b"")
            return httpx.Response(
                201,
                json={
                    "id": 902,
                    "source_url": "https://shop.example.test/wp-content/uploads/recovered.png",
                },
            )
        if method == "GET" and url.endswith("/wp-json/wc/v3/products/601"):
            return httpx.Response(
                200,
                json={
                    "id": 601,
                    "images": [
                        {
                            "id": 901,
                            "src": "https://shop.example.test/wp-content/uploads/existing.jpg",
                        }
                    ],
                },
            )
        if method == "PUT" and url.endswith("/wp-json/wc/v3/products/601"):
            media_payloads.append(json or {})
            return httpx.Response(
                200,
                json={
                    "id": 601,
                    "images": [
                        {
                            "id": 901,
                            "src": "https://shop.example.test/wp-content/uploads/existing.jpg",
                            "alt": "Existing remote image",
                        },
                        {
                            "id": 902,
                            "src": "https://shop.example.test/wp-content/uploads/recovered.png",
                            "alt": "Recover media",
                        },
                    ],
                },
            )
        if method == "GET" and woocommerce_resource_path(url) == "/products":
            return httpx.Response(200, json=[])
        if method == "GET" and woocommerce_resource_path(url) == "/customers":
            return httpx.Response(200, json=[])
        if method == "GET" and woocommerce_resource_path(url) == "/orders":
            return httpx.Response(200, json=[])
        raise AssertionError(f"Unexpected request: {method} {url}")

    monkeypatch.setattr(httpx, "request", mock_request)

    queued_sync, sync_data = queue_and_process_sync(harness, headers)
    assert queued_sync["status"] == "queued"
    assert sync_data["status"] == "success"
    assert sync_data["stats"]["pushed_records"] == 1
    assert sync_data["stats"]["pushed_media_records"] == 1
    assert sync_data["stats"]["pending_media_pushes"] == 0
    assert sync_data["stats"]["failed_media_pushes"] == 0
    assert product_payloads and "images" not in product_payloads[0]
    assert media_uploads == [b"\x89PNG\r\n\x1a\nrecover"]
    assert media_payloads[0]["images"] == [
        {"id": 901},
        {"id": 902, "alt": "Recover media", "name": "pending-recovery.png"},
    ]

    with harness.session_factory() as db:
        mapping = db.scalar(
            select(ExternalResourceMap).where(
                ExternalResourceMap.company_id == company_id,
                ExternalResourceMap.internal_resource_id == product_id,
                ExternalResourceMap.internal_resource_type == "product",
            )
        )
        assert mapping is not None
        assert mapping.external_resource_id == "601"
        image = db.scalar(
            select(ProductImage).where(
                ProductImage.company_id == company_id,
                ProductImage.product_id == product_id,
                ProductImage.external_id == "902",
            )
        )
        assert image is not None
        assert image.sync_status == "synced"
        outbox_rows = db.scalars(
            select(SyncOutbox).where(
                SyncOutbox.company_id == company_id,
                SyncOutbox.resource_id == product_id,
            )
        ).all()
        assert {(row.operation, row.status) for row in outbox_rows} == {
            ("push", "synced"),
            ("push_media", "synced"),
        }

    config_after = client.get("/api/v1/woocommerce/config", headers=headers)
    assert config_after.status_code == 200
    assert config_after.json()["pending_media_pushes"] == 0
    assert config_after.json()["failed_media_pushes"] == 0
    assert config_after.json()["last_media_error"] is None


def test_woocommerce_sync_does_not_clear_remote_images_when_local_media_is_empty(
    harness: ApiHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = harness.client
    token, company_id = complete_first_use_setup(client)
    headers = bearer(token)

    with harness.session_factory() as db:
        product = Product(
            company_id=company_id,
            name="Mapped Product",
            slug="mapped-product",
            sku="ERP-200",
            product_type="simple",
            status="active",
            metadata_json={},
        )
        db.add(product)
        db.flush()
        db.add(
            ProductVariant(
                company_id=company_id,
                product_id=product.id,
                name="Default",
                sku="ERP-200-1",
                price_minor=1599,
                currency="PKR",
                attributes={},
                is_active=True,
            )
        )
        upsert_external_resource_map(
            db,
            company_id=company_id,
            resource_type="product",
            internal_id=product.id,
            external_id="801",
        )
        db.commit()

    configure_store(client, headers)

    product_payloads: list[dict[str, object]] = []
    media_payloads: list[dict[str, object]] = []

    def mock_request(
        method: str,
        url: str,
        auth: tuple[str, str] | None = None,
        json: dict | None = None,
        timeout: float | None = None,
        **kwargs: object,
    ) -> httpx.Response:
        assert kwargs.get("follow_redirects") is True
        if method == "GET" and woocommerce_resource_path(url) in {
            "/products/categories",
            "/products/brands",
        }:
            return httpx.Response(200, json=[])
        if method == "PUT" and url.endswith("/wp-json/wc/v3/products/801"):
            product_payloads.append(json or {})
            return httpx.Response(200, json={"id": 801, "name": "Mapped Product", "sku": "ERP-200"})
        if method == "GET" and woocommerce_resource_path(url) == "/products":
            return httpx.Response(200, json=[])
        if method == "GET" and woocommerce_resource_path(url) == "/customers":
            return httpx.Response(200, json=[])
        if method == "GET" and woocommerce_resource_path(url) == "/orders":
            return httpx.Response(200, json=[])
        if method == "GET" and url.endswith("/wp-json/wc/v3/products/801"):
            media_payloads.append(json or {})
            return httpx.Response(
                200,
                json={
                    "id": 801,
                    "images": [
                        {
                            "id": 901,
                            "src": "https://shop.example.test/wp-content/uploads/remote.jpg",
                        }
                    ],
                },
            )
        raise AssertionError(f"Unexpected request: {method} {url}")

    monkeypatch.setattr(httpx, "request", mock_request)

    queued_sync, sync_data = queue_and_process_sync(harness, headers)
    assert queued_sync["status"] == "queued"
    assert sync_data["status"] == "success"
    assert product_payloads[0] == {
            "name": "Mapped Product",
            "slug": "mapped-product",
            "sku": "ERP-200",
            "type": "simple",
            "status": "publish",
            "catalog_visibility": "visible",
            "featured": False,
            "regular_price": "15.99",
            "manage_stock": False,
            "stock_quantity": None,
            "stock_status": "instock",
            "backorders": "no",
            "sold_individually": False,
            "description": "",
            "short_description": "",
            "tax_status": "taxable",
            "tax_class": "",
            "weight": "",
            "dimensions": {"length": "", "width": "", "height": ""},
            "shipping_class": "",
            "reviews_allowed": True,
            "purchase_note": "",
            "menu_order": 0,
            "attributes": [],
            "default_attributes": [],
            "meta_data": [],
            "categories": [],
    }
    assert product_payloads[1] == {
        "meta_data": [
            {
                "key": WOOCOMMERCE_VIDEO_META_KEY,
                "value": {"schema_version": 1, "videos": []},
            }
        ]
    }


def test_woocommerce_full_sync_and_webhook_receiver(
    harness: ApiHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = harness.client
    token, company_id = complete_first_use_setup(client)
    headers = bearer(token)
    webhook_secret = "woo-webhook-secret-123456"
    configure_store(client, headers, webhook_secret=webhook_secret)

    request_urls: list[str] = []
    product_pull_count = {"count": 0}

    def mock_request(
        method: str,
        url: str,
        auth: tuple[str, str] | None = None,
        json: dict | None = None,
        timeout: float | None = None,
        **kwargs: object,
    ) -> httpx.Response:
        request_urls.append(url)
        assert kwargs.get("follow_redirects") is True
        resource_path = woocommerce_resource_path(url)
        params = query_params(url)
        if method == "GET" and urlparse(url).path.startswith("/wp-json/wc/v3"):
            assert kwargs.get("params") is None
            return httpx.Response(404, json={"code": "rest_no_route", "message": "No route."})
        if method == "GET" and params.get("per_page") == "1":
            return httpx.Response(200, json=[])
        if method == "GET" and resource_path == "/products":
            product_pull_count["count"] += 1
            assert params.get("per_page") == "100"
            assert params.get("page") == "1"
            if params.get("_fields") == "id":
                assert "modified_after" not in params
                return httpx.Response(200, json=[])
            if product_pull_count["count"] >= 2:
                return httpx.Response(200, json=[])
            return httpx.Response(
                200,
                json=[
                    {
                        "id": 101,
                        "name": "Woo Simple Product",
                        "sku": "woo-simple-sku",
                        "price": "15.99",
                        "regular_price": "15.99",
                        "stock_quantity": 7,
                        "stock_status": "instock",
                        "categories": [{"id": 11, "name": "Electronics", "slug": "electronics"}],
                        "brands": [{"id": 21, "name": "Apple", "slug": "apple"}],
                    }
                ],
            )
        if method == "GET" and resource_path == "/products/categories":
            return httpx.Response(
                200, json=[{"id": 11, "name": "Electronics", "slug": "electronics", "parent": 0}]
            )
        if method == "GET" and resource_path == "/products/brands":
            return httpx.Response(200, json=[{"id": 21, "name": "Apple", "slug": "apple"}])
        if method == "POST" and url.endswith("/?rest_route=/wc/v3/products"):
            return httpx.Response(
                201,
                json={"id": 102, "name": json.get("name"), "sku": json.get("sku")},
            )
        if method == "PUT" and "/?rest_route=/wc/v3/products/" in url:
            return httpx.Response(
                200,
                json={"id": 101, "name": "Updated Product", "sku": "woo-simple-sku"},
            )
        if method == "GET" and resource_path == "/customers":
            assert params.get("per_page") == "100"
            assert params.get("page") == "1"
            return httpx.Response(
                200,
                json=[
                    {
                        "id": 201,
                        "email": "woo-cust@example.com",
                        "first_name": "Woo",
                        "last_name": "Customer",
                        "billing": {
                            "phone": "12345678",
                            "address_1": "123 Woo St",
                            "city": "Lahore",
                            "country": "PK",
                        },
                    }
                ],
            )
        if method == "GET" and resource_path == "/orders":
            assert params.get("per_page") == "100"
            assert params.get("page") == "1"
            return httpx.Response(
                200,
                json=[
                    {
                        "id": 301,
                        "number": "1001",
                        "customer_id": 201,
                        "status": "processing",
                        "currency": "PKR",
                        "total": "45.00",
                        "shipping_total": "13.02",
                        "line_items": [
                            {
                                "product_id": 101,
                                "variation_id": 0,
                                "sku": "woo-simple-sku",
                                "name": "Woo Simple Product",
                                "quantity": 2,
                                "price": "15.99",
                            }
                        ],
                    }
                ],
            )
        if method == "PUT" and "/?rest_route=/wc/v3/orders/" in url:
            return httpx.Response(200, json={"id": 301, "status": "completed"})
        return httpx.Response(404)

    monkeypatch.setattr(httpx, "request", mock_request)

    test_conn_resp = client.post("/api/v1/woocommerce/test-connection", headers=headers)
    assert test_conn_resp.status_code == 200
    assert test_conn_resp.json()["status"] == "ok"

    with harness.session_factory() as db:
        setting = db.scalar(select(Setting).where(Setting.key == WOOCOMMERCE_SETTING_KEY))
        assert setting is not None
        assert setting.value["rest_api_mode"] == "query"

    queued_sync, sync_data = queue_and_process_sync(harness, headers)
    assert queued_sync["status"] == "queued"
    assert sync_data["status"] == "success"
    assert sync_data["stats"]["pulled_products"] == 1
    assert sync_data["stats"]["pulled_customers"] == 1
    assert sync_data["stats"]["pulled_orders"] == 1
    assert any("/?rest_route=/wc/v3/products" in url for url in request_urls)
    assert any("/?rest_route=/wc/v3/customers" in url for url in request_urls)
    assert any("/?rest_route=/wc/v3/orders" in url for url in request_urls)

    with harness.session_factory() as db:
        prod_map = db.scalar(
            select(ExternalResourceMap).where(ExternalResourceMap.external_resource_id == "101")
        )
        assert prod_map is not None
        assert prod_map.internal_resource_type == "product"
        product = db.get(Product, prod_map.internal_resource_id)
        assert product is not None
        assert db.get(Category, product.category_id).name == "Electronics"
        assert db.get(Brand, product.brand_id).name == "Apple"

        warehouse = db.scalar(
            select(Warehouse).where(
                Warehouse.company_id == company_id,
                Warehouse.code == "WOO",
            )
        )
        assert warehouse is not None
        movement = db.scalar(
            select(StockMovement).where(
                StockMovement.company_id == company_id,
                StockMovement.warehouse_id == warehouse.id,
                StockMovement.reference_type == "woocommerce_product",
                StockMovement.reference_id == "101",
            )
        )
        assert movement is not None
        assert movement.quantity_delta == 7

        cust_map = db.scalar(
            select(ExternalResourceMap).where(ExternalResourceMap.external_resource_id == "201")
        )
        assert cust_map is not None
        assert cust_map.internal_resource_type == "customer"

        order_map = db.scalar(
            select(ExternalResourceMap).where(ExternalResourceMap.external_resource_id == "301")
        )
        assert order_map is not None
        assert order_map.internal_resource_type == "order"
        setting = db.scalar(select(Setting).where(Setting.key == WOOCOMMERCE_SETTING_KEY))
        assert setting is not None
        assert {
            "last_products_sync",
            "last_orders_sync",
        }.issubset(setting.value)
        assert "last_customers_sync" not in setting.value

    runs_resp = client.get("/api/v1/woocommerce/sync-runs", headers=headers)
    assert runs_resp.status_code == 200
    assert len(runs_resp.json()) >= 1
    assert {run["company_id"] for run in runs_resp.json()} == {company_id}

    with harness.session_factory() as db:
        other_company = Company(id="other-sync-company", name="Other Company", status="active")
        db.add(other_company)
        db.add(
            SyncRunLog(
                company_id=other_company.id,
                connector="woocommerce",
                direction="both",
                status="success",
                stats={"pulled_products": 99},
            )
        )
        db.commit()

    tenant_runs_resp = client.get("/api/v1/woocommerce/sync-runs", headers=headers)
    assert tenant_runs_resp.status_code == 200
    assert {run["company_id"] for run in tenant_runs_resp.json()} == {company_id}

    webhook_payload = {
        "id": 302,
        "number": "1002",
        "customer_id": 201,
        "status": "completed",
        "currency": "PKR",
        "total": "20.00",
        "shipping_total": "4.01",
        "line_items": [
            {
                "product_id": 101,
                "variation_id": 0,
                "sku": "woo-simple-sku",
                "name": "Woo Simple Product",
                "quantity": 1,
                "price": "15.99",
            }
        ],
    }
    webhook_raw_body = jsonlib.dumps(webhook_payload, separators=(",", ":")).encode("utf-8")
    webhook_headers = {
        "X-WC-Webhook-Topic": "order.created",
        "X-WC-Webhook-Delivery-Id": "webhook-del-unique-123",
        "X-WC-Webhook-Source": "https://shop.example.test",
        "X-WC-Webhook-Signature": woo_webhook_signature(webhook_raw_body, webhook_secret),
        "Content-Type": "application/json",
    }

    wh_resp1 = client.post(
        "/api/v1/woocommerce/webhooks",
        content=webhook_raw_body,
        headers=webhook_headers,
    )
    assert wh_resp1.status_code == 200
    assert wh_resp1.json() == {"ok": True}

    with harness.session_factory() as db:
        order_map_2 = db.scalar(
            select(ExternalResourceMap).where(ExternalResourceMap.external_resource_id == "302")
        )
        assert order_map_2 is not None

        log = db.scalar(
            select(SyncInboxLog).where(SyncInboxLog.external_event_id == "webhook-del-unique-123")
        )
        assert log is not None
        assert log.status == "processed"

    wh_resp2 = client.post(
        "/api/v1/woocommerce/webhooks",
        content=webhook_raw_body,
        headers=webhook_headers,
    )
    assert wh_resp2.status_code == 200
    assert wh_resp2.json() == {"ok": True}

    queued_sync_2, sync_data_2 = queue_and_process_sync(harness, headers)
    assert queued_sync_2["status"] == "queued"
    assert sync_data_2["status"] == "success"
    for resource_path in ("/products", "/orders"):
        assert any(
            woocommerce_resource_path(url) == resource_path
            and "modified_after" in query_params(url)
            for url in request_urls
        )
    assert all(
        "modified_after" not in query_params(url)
        for url in request_urls
        if woocommerce_resource_path(url) == "/customers"
    )

    with harness.session_factory() as db:
        active_product = db.get(Product, prod_map.internal_resource_id)
        assert active_product is not None
        assert active_product.status != "archived"

    queued_reconciliation, reconciliation_data = queue_and_process_sync(
        harness,
        headers,
        mode="reconcile_products",
    )
    assert queued_reconciliation["stats"]["sync_mode"] == "reconcile_products"
    assert reconciliation_data["status"] == "success"
    assert reconciliation_data["stats"]["archived_products"] == 1

    with harness.session_factory() as db:
        archived_product = db.get(Product, prod_map.internal_resource_id)
        assert archived_product is not None
        assert archived_product.status == "archived"

    with harness.session_factory() as db:
        from erp.packages.core.catalog_services import create_product
        from erp.packages.core.schemas import ProductCreate, ProductVariantCreate

        deleted_product = create_product(
            db,
            company_id=company_id,
            user_id=None,
            payload=ProductCreate(
                name="Woo Deleted Product",
                sku="woo-deleted-sku",
                variants=[
                    ProductVariantCreate(
                        sku="woo-deleted-variant-sku",
                        price_minor=1250,
                    )
                ],
            ),
        )
        upsert_external_resource_map(
            db,
            company_id=company_id,
            resource_type="product",
            internal_id=deleted_product.id,
            external_id="999",
        )
        db.commit()

    delete_payload = {"id": 999, "name": "Woo Deleted Product"}
    delete_raw_body = jsonlib.dumps(delete_payload, separators=(",", ":")).encode("utf-8")
    delete_headers = {
        "X-WC-Webhook-Topic": "product.deleted",
        "X-WC-Webhook-Delivery-Id": "webhook-del-product-999",
        "X-WC-Webhook-Source": "https://shop.example.test",
        "X-WC-Webhook-Signature": woo_webhook_signature(delete_raw_body, webhook_secret),
        "Content-Type": "application/json",
    }

    delete_resp = client.post(
        "/api/v1/woocommerce/webhooks",
        content=delete_raw_body,
        headers=delete_headers,
    )
    assert delete_resp.status_code == 200
    assert delete_resp.json() == {"ok": True}

    with harness.session_factory() as db:
        archived_product = db.scalar(
            select(Product).where(Product.sku == "woo-deleted-sku")
        )
        assert archived_product is not None
        assert archived_product.status == "archived"

    with harness.session_factory() as db:
        from erp.packages.core.catalog_services import create_product
        from erp.packages.core.schemas import ProductCreate, ProductVariantCreate

        p_val = create_product(
            db,
            company_id=company_id,
            user_id=None,
            payload=ProductCreate(
                name="Local Outbox Product",
                sku=None,
                variants=[
                    ProductVariantCreate(
                        sku="local-out-sku",
                        price_minor=1000,
                    )
                ],
            ),
        )
        from erp.packages.core.woocommerce_services import enqueue_sync_outbox

        enqueue_sync_outbox(
            db,
            company_id=company_id,
            operation="push",
            resource_type="product",
            resource_id=p_val.id,
            payload={"name": p_val.name, "sku": p_val.sku},
        )
        db.commit()

    queued_worker_sync = client.post("/api/v1/woocommerce/sync", headers=headers)
    assert queued_worker_sync.status_code == 202
    worker_state = worker_run_once(session_factory=harness.session_factory)
    assert worker_state["status"] == "success"
    assert "finished: success" in worker_state["message"]

    with harness.session_factory() as db:
        outbox_recs = db.scalars(
            select(SyncOutbox).where(SyncOutbox.company_id == company_id)
        ).all()
        assert any(r.status == "synced" for r in outbox_recs)

    with harness.session_factory() as db:
        from erp.packages.core.woocommerce_services import create_sync_conflict

        conflict = create_sync_conflict(
            db,
            company_id=company_id,
            resource_type="product",
            resource_id="local-product-1",
            external_resource_id="101",
            conflict_type="sku_already_mapped",
            local_payload={"name": "Local Product Name"},
            remote_payload={"name": "Remote Product Name"},
        )
        db.commit()
        conflict_id = conflict.id

    conflicts_resp = client.get("/api/v1/woocommerce/conflicts", headers=headers)
    assert conflicts_resp.status_code == 200
    assert len(conflicts_resp.json()) >= 1

    resolve_resp = client.post(
        f"/api/v1/woocommerce/conflicts/{conflict_id}/resolve",
        headers=headers,
        json={"resolution": "Resolved manually", "strategy": "use_local"},
    )
    assert resolve_resp.status_code == 200
    assert resolve_resp.json()["status"] == "resolved"
    assert resolve_resp.json()["resolution"] == "Resolved manually"
    with harness.session_factory() as db:
        actor_id = db.scalar(
            select(User.id).where(User.company_id == company_id, User.username == "admin")
        )
        audit_actor_id = db.scalar(
            select(AuditLog.user_id).where(
                AuditLog.company_id == company_id,
                AuditLog.action == "woocommerce.conflict_resolved",
                AuditLog.entity_id == conflict_id,
            )
        )
        assert audit_actor_id == actor_id


def test_woocommerce_failed_sync_run_is_persisted_and_visible(
    harness: ApiHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = harness.client
    token, _company_id = complete_first_use_setup(client)
    headers = bearer(token)
    configure_store(client, headers)

    def failing_request(
        method: str,
        url: str,
        auth: tuple[str, str] | None = None,
        json: dict | None = None,
        timeout: float | None = None,
        **kwargs: object,
    ) -> httpx.Response:
        assert kwargs.get("follow_redirects") is True
        if method == "GET" and woocommerce_resource_path(url) == "/products":
            return httpx.Response(404, json={"code": "rest_no_route", "message": "No route."})
        return httpx.Response(404, json={"code": "rest_no_route", "message": "No route."})

    monkeypatch.setattr(httpx, "request", failing_request)

    queued_sync, sync_data = queue_and_process_sync(harness, headers)
    assert queued_sync["status"] == "queued"
    assert sync_data["status"] == "failed"
    assert "remote HTTP 404" in str(sync_data["error"])
    assert "/products" in str(sync_data["error"])

    runs_resp = client.get("/api/v1/woocommerce/sync-runs", headers=headers)
    assert runs_resp.status_code == 200
    assert any(run["status"] == "failed" for run in runs_resp.json())


def test_company_wide_active_sync_key_coalesces_vendor_requests(harness: ApiHarness) -> None:
    _token, company_id = complete_first_use_setup(harness.client)
    with harness.session_factory() as db:
        company_run, created = enqueue_woocommerce_sync_run(
            db, company_id=company_id, sync_mode="products"
        )
        vendor_run, vendor_created = enqueue_woocommerce_sync_run(
            db,
            company_id=company_id,
            sync_mode="products",
            vendor_id="vendor-a",
        )

        assert created is True
        assert vendor_created is False
        assert vendor_run.id == company_run.id
        assert company_run.active_key == f"woocommerce:{company_id}"


def test_rate_limited_outbox_run_is_deferred_without_losing_work(
    harness: ApiHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = harness.client
    token, company_id = complete_first_use_setup(client)
    headers = bearer(token)
    configure_store(client, headers)
    with harness.session_factory() as db:
        category = Category(
            company_id=company_id,
            name="Rate limited category",
            slug="rate-limited-category",
            is_active=True,
        )
        db.add(category)
        db.flush()
        product = Product(
            company_id=company_id,
            category_id=category.id,
            name="Rate limited product",
            slug="rate-limited-product",
            sku="RATE-LIMIT-1",
            product_type="simple",
            status="active",
            metadata_json={},
        )
        db.add(product)
        db.flush()
        enqueue_product_sync(db, company_id=company_id, product=product)
        db.commit()

    def rate_limited_request(method: str, url: str, **_kwargs: object) -> httpx.Response:
        assert method == "GET"
        assert woocommerce_resource_path(url) == "/products/categories"
        return httpx.Response(429, headers={"Retry-After": "120"}, text="Too Many Requests")

    monkeypatch.setattr(httpx, "request", rate_limited_request)
    state = worker_run_once(session_factory=harness.session_factory)

    with harness.session_factory() as db:
        run = db.scalar(select(SyncRunLog).where(SyncRunLog.company_id == company_id))
        outbox = db.scalar(select(SyncOutbox).where(SyncOutbox.company_id == company_id))
        assert run is not None
        assert state["status"] == "queued", run.error
        assert run.status == "queued"
        assert run.next_attempt_at is not None
        assert run.active_key == f"woocommerce:{company_id}"
        assert run.stats["rate_limited"] is True
        assert outbox is not None
        assert outbox.status == "pending"
