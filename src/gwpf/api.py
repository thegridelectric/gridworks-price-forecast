"""HTTP / FastAPI read façade — the service's one delivery path.

Public, read-only, CORS-open, TLS at the fronting proxy. The forecast is
served at two paths: the house-pattern route under the service's
hyphenated GNodeAlias, and the legacy route the LTN has hard-coded. The
response body is the sema word itself, byte-identical to `to_dict()`
wire form, so `/docs` documents the real schema.

Run: `uv run uvicorn gwpf.api:app --factory` (env-configured).
"""

from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi

from gwpf.config import GwpfSettings, load_settings
from gwpf.forecast import ForecastKeeper
from gwpf.isone import IsoneClient
from gwpf.sema.types import StopgapPriceForecast

SEMA_DEFINITION_URL = (
    "https://github.com/thegridelectric/sema/blob/dev/"
    "definitions/types/{type_name}/{version}.yaml"
)


def create_app(settings: GwpfSettings, keeper: ForecastKeeper) -> FastAPI:
    """Build the read façade over a forecast keeper."""
    party = settings.service_alias.replace(".", "-")

    app = FastAPI(
        title="gridworks-price-forecast — read API",
        description=(
            "Public read-only pull path for the GridWorks price forecast. "
            "The response body is a sema word."
        ),
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET"],
        allow_headers=["*"],
    )

    @app.get("/ping")
    def ping() -> dict[str, str]:
        return {"status": "ok"}

    def latest_forecast() -> StopgapPriceForecast:
        """The current 48-hour forecast (503 when none can be served)."""
        forecast = keeper.current()
        if forecast is None:
            raise HTTPException(status_code=503, detail="no price forecast available")
        return forecast

    app.get(f"/{party}/latest-forecast", response_model_exclude_none=True)(
        latest_forecast
    )
    app.get(settings.ltn_route, response_model_exclude_none=True)(latest_forecast)

    def openapi_with_sema_links() -> dict[str, Any]:
        if app.openapi_schema:
            return app.openapi_schema
        schema = get_openapi(
            title=app.title,
            version=app.version,
            description=app.description,
            routes=app.routes,
        )
        for component in schema.get("components", {}).get("schemas", {}).values():
            properties = component.get("properties", {})
            type_name = properties.get("TypeName", {}).get("default")
            version = properties.get("Version", {}).get("default")
            if type_name and version:
                url = SEMA_DEFINITION_URL.format(type_name=type_name, version=version)
                note = f"Sema word [`{type_name}` v{version}]({url})."
                component["description"] = (
                    f"{component.get('description', '')}\n\n{note}".strip()
                )
        app.openapi_schema = schema
        return schema

    app.openapi = openapi_with_sema_links  # type: ignore[method-assign]
    return app


def app() -> FastAPI:
    """uvicorn factory: `uvicorn gwpf.api:app --factory` (env settings)."""
    import dotenv

    dotenv.load_dotenv(dotenv.find_dotenv())
    settings = load_settings()
    client = IsoneClient(
        settings.isone_user,
        settings.isone_api_pass.get_secret_value(),
        settings.isone_location_id,
    )
    return create_app(settings, ForecastKeeper(settings, client))
