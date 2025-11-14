from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.services.session_service_mqtt import (
    SessionServiceMQTT,
)
from app.models.station import StationConfig
from app.database.connection import get_db
from app.database.repositories import (
    StationRepository,
    ChargerRepository,
    ConnectorRepository,
    SessionRepository,
    PowerMetricRepository,
    BESSStatusRepository,
    EventRepository
)
import logging

logger = logging.getLogger(__name__)

_station_config: StationConfig = None


def set_station_config(config: StationConfig):
    """Définir la configuration de la station au démarrage"""
    global _station_config
    _station_config = config
    logger.info(f"Station config set: {config.stationId}")


def get_station_config() -> StationConfig:
    """Récupérer la configuration de la station"""
    if _station_config is None:
        raise RuntimeError("Station config not initialized")
    return _station_config


async def get_session_service(
        db: AsyncSession = Depends(get_db)
) -> SessionServiceMQTT:
    """
    Dependency injection pour le SessionService
    Utilise les instances globales partagées
    """
    try:
        from app.services.session_service_mqtt import (
            _global_load_manager,
            _global_bess_controller,
            _global_station_db_id,
            _global_station_config,
            _global_mqtt_service
        )

        # Vérifier que tout est initialisé
        if _global_station_config is None:
            raise RuntimeError("Global station config not initialized")

        if _global_mqtt_service is None:
            raise RuntimeError("Global MQTT service not initialized")

        if _global_load_manager is None:
            raise RuntimeError("Global load manager not initialized")

        service = SessionServiceMQTT.__new__(SessionServiceMQTT)
        service.config = _global_station_config
        service.db = db
        service.mqtt = _global_mqtt_service
        service.load_manager = _global_load_manager
        service.bess_controller = _global_bess_controller
        service.station_db_id = _global_station_db_id

        service.station_repo = StationRepository(db)
        service.charger_repo = ChargerRepository(db)
        service.connector_repo = ConnectorRepository(db)
        service.session_repo = SessionRepository(db)
        service.power_metric_repo = PowerMetricRepository(db)
        service.event_repo = EventRepository(db)

        if service.bess_controller:
            service.bess_repo = BESSStatusRepository(db)
        else:
            service.bess_repo = None

        logger.debug("Session service created for request")
        return service

    except Exception as e:
        logger.error(f"Error creating session service: {e}", exc_info=True)
        raise
