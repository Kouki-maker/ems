from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import logging
import json
import asyncio

from app.models.station import StationConfig
from app.api.routes import station, sessions, connectors, chargers
from app.database.connection import init_db, close_db, AsyncSessionLocal
from app.services.station_init_service import StationInitService
from app.services.mqtt_service import initialize_mqtt_service, get_mqtt_service
from app.services.session_service_mqtt import SessionServiceMQTT

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Variables globales
_station_config: StationConfig = None
_session_service: SessionServiceMQTT = None


def load_station_config(config_path: str = "station_config.json") -> StationConfig:
    """Charger la configuration de la station"""
    try:
        with open(config_path, 'r') as f:
            config_data = json.load(f)

        config = StationConfig(**config_data)
        logger.info(f"Loaded station config: {config.stationId}")
        return config
    except FileNotFoundError:
        logger.error(f"Config file {config_path} not found")
        raise


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle events"""
    global _station_config, _session_service

    # Startup
    logger.info("=" * 60)
    logger.info("Starting Electra EMS API with MQTT")
    logger.info("=" * 60)

    # 1. Initialiser la base de données
    await init_db()
    logger.info("✓ Database initialized")

    # 2. Charger la configuration de la station
    _station_config = load_station_config()
    logger.info(f"✓ Station config loaded: {_station_config.stationId}")

    # 3. Initialiser la station dans la DB
    async with AsyncSessionLocal() as db:
        await StationInitService.initialize_station(db, _station_config)
    logger.info("✓ Station initialized in database")

    # 4. Initialiser le service MQTT
    mqtt_service = initialize_mqtt_service(_station_config.stationId)

    # 5. Obtenir l'event loop et le passer au service MQTT
    loop = asyncio.get_event_loop()
    mqtt_service.set_event_loop(loop)
    logger.info("✓ MQTT service initialized with event loop")

    # 6. Initialiser le SessionService avec MQTT
    async with AsyncSessionLocal() as db:
        _session_service = SessionServiceMQTT(_station_config, db, mqtt_service)
        await _session_service.initialize()
    logger.info("✓ Session service initialized with MQTT")

    logger.info("=" * 60)
    logger.info("Electra EMS API started successfully")
    logger.info(f"MQTT Connected: {mqtt_service.connected}")
    logger.info("=" * 60)

    yield

    # Shutdown
    logger.info("Shutting down Electra EMS API...")
    mqtt_service.disconnect()
    await close_db()
    logger.info("✓ Shutdown complete")


app = FastAPI(
    title="Electra EMS API",
    description="Energy Management System with MQTT Communication",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Inclure les routers
app.include_router(station.router)
app.include_router(sessions.router)
app.include_router(chargers.router)
app.include_router(connectors.router)


@app.get("/")
async def root():
    """Route racine"""
    mqtt = get_mqtt_service()
    return {
        "name": "Electra EMS API",
        "version": "1.0.0",
        "status": "running",
        "mqtt_connected": mqtt.connected,
        "station": _station_config.stationId if _station_config else None,
        "endpoints": {
            "docs": "/docs",
            "station_status": "/station/status",
            "sessions": "/sessions"
        }
    }


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    mqtt = get_mqtt_service()

    return {
        "status": "healthy",
        "mqtt_connected": mqtt.connected,
        "station": _station_config.stationId if _station_config else None,
        "active_sessions": len(_session_service.get_all_sessions()) if _session_service else 0
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True
    )
