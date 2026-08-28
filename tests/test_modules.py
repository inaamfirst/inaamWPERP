from __future__ import annotations

from erp.packages.core.modules.manifest import load_module_manifests


def test_required_module_manifests_load() -> None:
    manifests = load_module_manifests()
    ids = {manifest.id for manifest in manifests}

    assert ids == {
        "audit",
        "backup",
        "catalog",
        "accounting",
        "core",
        "customers",
        "identity",
        "inventory",
        "licensing",
        "marketplace",
        "orders",
        "reports",
        "settings",
        "support",
        "tenancy",
        "woocommerce",
        "whatsapp",
    }


def test_manifest_dependencies_are_validated() -> None:
    manifests = load_module_manifests()
    ids = {manifest.id for manifest in manifests}

    for manifest in manifests:
        assert set(manifest.dependencies).issubset(ids)


def test_implemented_and_scaffold_module_statuses() -> None:
    manifests = {manifest.id: manifest for manifest in load_module_manifests()}

    assert manifests["core"].status == "implemented"
    assert manifests["catalog"].status == "implemented"
    assert manifests["customers"].status == "implemented"
    assert manifests["inventory"].status == "implemented"
    assert manifests["orders"].status == "implemented"
    assert manifests["marketplace"].status == "implemented"
    assert manifests["accounting"].status == "implemented"
    assert manifests["woocommerce"].status == "implemented"
    assert manifests["whatsapp"].status == "implemented"
    assert manifests["reports"].status == "implemented"
    assert manifests["backup"].status == "implemented"
    assert manifests["licensing"].status == "implemented"
    assert manifests["support"].status == "implemented"
    assert manifests["tenancy"].status == "implemented"
    assert manifests["marketplace"].enabled_by_default is False
    assert manifests["accounting"].enabled_by_default is False
    assert manifests["woocommerce"].enabled_by_default is False
    assert manifests["whatsapp"].enabled_by_default is False
