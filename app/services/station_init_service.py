from sqlalchemy.ext.asyncio import AsyncSession
from app.models.station import StationConfig
from app.database.repositories import (
    StationRepository, ChargerRepository, ConnectorRepository
)
import logging

logger = logging.getLogger(__name__)


class StationInitService:
    """Service pour initialiser la station dans la base de données"""

    @staticmethod
    async def initialize_station(db: AsyncSession, config: StationConfig):
        """
        Initialiser ou mettre à jour la station dans la base de données
        à partir de la configuration
        """
        station_repo = StationRepository(db)
        charger_repo = ChargerRepository(db)
        connector_repo = ConnectorRepository(db)

        # Créer ou récupérer la station
        station = await station_repo.get_or_create(
            station_id=config.stationId,
            grid_capacity=config.gridCapacity,
            static_load=config.staticLoad,
            config=config.dict()
        )

        logger.info(f"Station {config.stationId} initialized with ID {station.id}")

        # Créer les chargeurs et connecteurs
        for charger_config in config.chargers:
            # Vérifier si le chargeur existe déjà
            charger = await charger_repo.get_by_charger_id(
                station.id,
                charger_config.id
            )

            if not charger:
                # Créer le chargeur
                charger = await charger_repo.create(
                    station_db_id=station.id,
                    charger_id=charger_config.id,
                    max_power=charger_config.maxPower,
                    num_connectors=len(charger_config.connectors),
                    manufacturer=charger_config.manufacturer,
                    model=charger_config.model
                )
                logger.info(f"  Charger {charger_config.id} created")
            else:
                logger.info(f"  Charger {charger_config.id} already exists")

            # Créer les connecteurs
            for connector_config in charger_config.connectors:
                # Vérifier si le connecteur existe déjà
                connector = await connector_repo.get_by_charger_and_connector_id(
                    charger.id,
                    connector_config.connector_id
                )

                if not connector:
                    connector = await connector_repo.create(
                        charger_db_id=charger.id,
                        connector_id=connector_config.connector_id,
                        connector_type=connector_config.connector_type.value,
                        max_power=connector_config.max_power
                    )
                    logger.info(f"    Connector {connector_config.connector_id} "
                                f"({connector_config.connector_type}) created")
                else:
                    logger.info(f"    Connector {connector_config.connector_id} "
                                f"already exists")

        return station
