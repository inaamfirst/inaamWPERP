from __future__ import annotations

import uvicorn

from erp.packages.core.config import get_settings


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "erp.apps.license_server.main:app",
        host=settings.api_host,
        port=settings.api_port + 1,
        reload=not settings.is_production,
    )


if __name__ == "__main__":
    main()
