"""ss-sens FastAPI service: /site/sensors, /site/mesh, MQTT subscriber."""

import asyncio
from contextlib import asynccontextmanager
from typing import Any

from fastapi import APIRouter, Depends, FastAPI, Request

from ss_kit.logging import configure_logging, get_logger
from ss_kit.web import SecurityHeadersMiddleware, api_key_dependency

from .config import settings
from .mesh.fusion import SensorMeshFusion, SiteMesh
from .mesh.site_state import SiteState, SiteStateAggregator
from .runtime import run_mesh

logger = get_logger(__name__)

_require_api_key = api_key_dependency(
    lambda: settings.api_key, required=lambda: bool(settings.api_key)
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start the sensor aggregator, mesh, and MQTT subscriber."""
    configure_logging()
    try:
        settings.validate()
    except ValueError as exc:
        logger.warning("ss-sens settings: %s", exc)

    aggregator = SiteStateAggregator()
    fusion = SensorMeshFusion(aggregator)
    app.state.site_state_aggregator = aggregator
    app.state.sensor_mesh_fusion = fusion

    mqtt_task = asyncio.create_task(run_mesh(aggregator), name="ss_sens_mqtt")
    logger.info(
        "ss-sens started (broker %s, site_id=%s)",
        settings.mqtt.describe(),
        settings.site_id,
    )
    try:
        yield
    finally:
        if not mqtt_task.done():
            mqtt_task.cancel()
            await asyncio.gather(mqtt_task, return_exceptions=True)


app = FastAPI(title="ss_sens", lifespan=lifespan)
app.add_middleware(SecurityHeadersMiddleware)

router = APIRouter(dependencies=[Depends(_require_api_key)])


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/site/sensors", response_model=SiteState)
async def site_sensors(request: Request) -> SiteState:
    aggregator: SiteStateAggregator = request.app.state.site_state_aggregator
    return await aggregator.get_state()


@router.get("/site/mesh", response_model=SiteMesh)
async def site_mesh(request: Request) -> SiteMesh:
    fusion: SensorMeshFusion = request.app.state.sensor_mesh_fusion
    return await fusion.get_mesh()


app.include_router(router)


def create_app(
    *,
    aggregator: SiteStateAggregator | None = None,
    fusion: SensorMeshFusion | None = None,
    start_mqtt: bool = True,
) -> FastAPI:
    """Build an app instance, optionally with injected state (tests)."""
    if aggregator is None and fusion is None and start_mqtt:
        return app

    site_aggregator = aggregator or SiteStateAggregator()
    site_fusion = fusion or SensorMeshFusion(site_aggregator)

    @asynccontextmanager
    async def _lifespan(instance: FastAPI):
        instance.state.site_state_aggregator = site_aggregator
        instance.state.sensor_mesh_fusion = site_fusion
        mqtt_task: asyncio.Task[Any] | None = None
        if start_mqtt:
            mqtt_task = asyncio.create_task(run_mesh(site_aggregator), name="ss_sens_mqtt")
        try:
            yield
        finally:
            if mqtt_task is not None and not mqtt_task.done():
                mqtt_task.cancel()
                await asyncio.gather(mqtt_task, return_exceptions=True)

    instance = FastAPI(title="ss_sens", lifespan=_lifespan)
    instance.add_middleware(SecurityHeadersMiddleware)
    instance.include_router(router)
    instance.state.site_state_aggregator = site_aggregator
    instance.state.sensor_mesh_fusion = site_fusion
    return instance
