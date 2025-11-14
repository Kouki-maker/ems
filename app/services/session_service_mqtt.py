from typing import Dict, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.session import ChargingSession, SessionStatus
from app.models.station import StationConfig
from app.core.load_management import LoadManagementAlgorithm
from app.core.bess_controller import BESSController
from app.database.repositories import (
    StationRepository,
    ChargerRepository,
    ConnectorRepository,
    SessionRepository,
    PowerMetricRepository,
    BESSStatusRepository,
    EventRepository
)
from app.services.mqtt_service import MQTTService
from app.mqtt.messages import (
    ChargerTelemetryMessage,
    SessionStartMessage,
    SessionStopMessage,
    SessionUpdateMessage,
    BESSStatusMessage
)
from app.database.connection import AsyncSessionLocal
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# Variables globales pour partager l'état entre les handlers
_global_load_manager: Optional[LoadManagementAlgorithm] = None
_global_bess_controller: Optional[BESSController] = None
_global_station_db_id: Optional[int] = None
_global_station_config: Optional[StationConfig] = None
_global_mqtt_service: Optional[MQTTService] = None


class SessionServiceMQTT:
    """
    Service de gestion des sessions avec communication MQTT
    """

    def __init__(self, station_config: StationConfig, db: AsyncSession, mqtt_service: MQTTService):
        global _global_load_manager, _global_bess_controller, _global_station_config, _global_mqtt_service

        self.config = station_config
        self.db = db
        self.mqtt = mqtt_service

        # Utiliser les instances globales ou en créer de nouvelles
        if _global_load_manager is None:
            _global_load_manager = LoadManagementAlgorithm(station_config)
        self.load_manager = _global_load_manager

        # Repositories
        self.station_repo = StationRepository(db)
        self.charger_repo = ChargerRepository(db)
        self.connector_repo = ConnectorRepository(db)
        self.session_repo = SessionRepository(db)
        self.power_metric_repo = PowerMetricRepository(db)
        self.event_repo = EventRepository(db)

        # BESS
        if _global_bess_controller is None and station_config.battery:
            _global_bess_controller = BESSController(station_config.battery)
        self.bess_controller = _global_bess_controller

        if self.bess_controller:
            self.bess_repo = BESSStatusRepository(db)
        else:
            self.bess_repo = None

        self.station_db_id = _global_station_db_id

        # Sauvegarder les références globales
        _global_station_config = station_config
        _global_mqtt_service = mqtt_service

        # Enregistrer les handlers MQTT (une seule fois)
        if not hasattr(mqtt_service, '_handlers_registered'):
            self._register_mqtt_handlers()
            mqtt_service._handlers_registered = True

    def _register_mqtt_handlers(self):
        """Enregistrer les handlers pour les messages MQTT"""
        # Utiliser des fonctions statiques qui accèdent aux variables globales
        self.mqtt.register_telemetry_handler(handle_charger_telemetry_global)
        self.mqtt.register_session_start_handler(handle_session_start_global)
        self.mqtt.register_session_stop_handler(handle_session_stop_global)
        self.mqtt.register_session_update_handler(handle_session_update_global)
        self.mqtt.register_bess_status_handler(handle_bess_status_global)

        logger.info("MQTT handlers registered (global)")

    async def initialize(self):
        """Initialiser le service"""
        global _global_station_db_id

        station = await self.station_repo.get_by_station_id(self.config.stationId)
        if station:
            self.station_db_id = station.id
            _global_station_db_id = station.id
            logger.info(
                f"SessionServiceMQTT initialized for station {self.config.stationId} (DB ID: {self.station_db_id})")
        else:
            raise ValueError(f"Station {self.config.stationId} not found")

    async def create_session(
        self,
        session_id: str,
        charger_id: str,
        connector_id: int,
        vehicle_max_power: float,
        user_id: str = None
    ) -> float:
        """Créer une nouvelle session de charge"""
        logger.info(f"Creating session {session_id} on {charger_id}:{connector_id}")

        # Récupérer le chargeur et le connecteur
        charger = await self.charger_repo.get_by_charger_id(self.station_db_id, charger_id)
        if not charger:
            raise ValueError(f"Charger {charger_id} not found")

        connector = await self.connector_repo.get_by_charger_and_connector_id(
            charger.id,
            connector_id
        )
        if not connector:
            raise ValueError(f"Connector {connector_id} not found")

        # Mettre à jour le statut du connecteur
        await self.connector_repo.update_status(connector.id, "occupied")

        # Créer la session dans la DB
        db_session = await self.session_repo.create(
            session_id=session_id,
            station_db_id=self.station_db_id,
            charger_db_id=charger.id,
            connector_id=connector.id,
            vehicle_max_power=vehicle_max_power
        )

        # Obtenir le statut BESS
        bess_status = None
        if self.bess_controller:
            bess_status = self.bess_controller.get_status()

        # Créer la session dans le load manager
        allocated = self.load_manager.handle_session_start(
            session_id=session_id,
            charger_id=charger_id,
            connector_id=connector_id,
            vehicle_max_power=vehicle_max_power
        )

        # Mettre à jour la DB
        await self.session_repo.update_power(
            session_id=session_id,
            consumed_power=0.0,
            allocated_power=allocated,
            vehicle_max_power=vehicle_max_power
        )

        # Log de l'événement
        await self.event_repo.create(
            event_type="session_start",
            description=f"Session {session_id} started",
            data={
                "session_id": session_id,
                "charger_id": charger_id,
                "connector_id": connector_id,
                "allocated_power": allocated
            }
        )

        # Optimiser BESS et envoyer commandes si nécessaire
        await self._optimize_and_publish_bess()

        return allocated

    async def stop_session(self, session_id: str, consumed_energy: float) -> bool:
        """Arrêter une session de charge"""
        logger.info(f"Stopping session {session_id}")

        # Arrêter dans le load manager
        success = self.load_manager.handle_session_stop(session_id, consumed_energy)
        if not success:
            return False

        # Mettre à jour la DB
        db_session = await self.session_repo.complete_session(session_id, consumed_energy)
        if not db_session:
            return False

        # Libérer le connecteur
        await self.connector_repo.update_status(db_session.connector_id, "available")

        # Log
        await self.event_repo.create(
            event_type="session_stop",
            description=f"Session {session_id} stopped",
            data={"session_id": session_id, "energy": consumed_energy}
        )

        # Réallouer la puissance aux sessions restantes
        await self._reallocate_all_sessions()

        # Optimiser BESS
        await self._optimize_and_publish_bess()

        return True

    async def update_power_and_energy(
            self,
            session_id: str,
            consumed_power: float,
            vehicle_max_power: float,
            total_energy: float,
            vehicle_soc: float = None
    ) -> float:
        """
        Mettre à jour la consommation ET l'énergie d'une session
        """
        logger.info(
            f"UPDATE_POWER_AND_ENERGY called: session={session_id}, "
            f"power={consumed_power:.1f}kW, energy={total_energy:.3f}kWh, soc={vehicle_soc}"
        )

        # Mettre à jour dans le load manager
        session = self.load_manager.sessions.get(session_id)
        if not session:
            logger.warning(f"Session {session_id} not found in load manager")
            return 0.0

        logger.info(f"Before update: power={session.consumedPower}, energy={session.totalEnergy}")

        # Mettre à jour les valeurs
        session.consumedPower = consumed_power
        session.vehicleMaxPower = vehicle_max_power
        session.totalEnergy = total_energy
        if vehicle_soc is not None:
            session.vehicleSoc = vehicle_soc
        logger.info(f"After update: power={session.consumedPower}, energy={session.totalEnergy}")

        # Recalculer l'allocation
        bess_status = None
        if self.bess_controller:
            bess_status = self.bess_controller.get_status()

        allocations = self.load_manager.calculate_power_allocation(
            self.load_manager.sessions,
            bess_status
        )

        # Appliquer les allocations
        for alloc in allocations:
            if alloc.sessionId in self.load_manager.sessions:
                self.load_manager.sessions[alloc.sessionId].allocatedPower = alloc.allocatedPower
                self.load_manager.sessions[alloc.sessionId].offeredPower = alloc.allocatedPower

        # Obtenir la nouvelle allocation pour cette session
        new_allocated = next(
            (a.allocatedPower for a in allocations if a.sessionId == session_id),
            0.0
        )

        # Mettre à jour dans la DB
        await self.session_repo.update_power(
            session_id=session_id,
            consumed_power=consumed_power,
            allocated_power=new_allocated,
            vehicle_max_power=vehicle_max_power,
            total_energy=total_energy,
            vehicle_soc=vehicle_soc
        )

        return new_allocated

    async def _reallocate_all_sessions(self):
        """Réallouer la puissance pour toutes les sessions actives"""
        allocations = self.load_manager.get_current_allocations()

        for allocation in allocations:
            session = self.load_manager.sessions.get(allocation.sessionId)
            if session:
                # Publier la nouvelle allocation via MQTT
                self.mqtt.publish_power_limit(
                    charger_id=allocation.chargerId,
                    connector_id=allocation.connectorId,
                    power_limit=allocation.allocatedPower
                )

        logger.info(f"Reallocated power to {len(allocations)} sessions")

    async def _optimize_and_publish_bess(self):
        """Optimiser l'utilisation du BESS et publier les commandes via MQTT"""
        if not self.bess_controller:
            return

        grid_available = self.config.gridCapacity - self.config.staticLoad

        total_consumed = sum(s.consumedPower for s in self.load_manager.sessions.values())
        total_demand = sum(
            min(s.vehicleMaxPower, self.load_manager._get_charger_connector_limit(s))
            for s in self.load_manager.sessions.values()
        )

        if total_demand > grid_available:
            boost_power = self.bess_controller.calculate_boost_power(
                grid_available=grid_available,
                total_demand=total_demand
            )

            if boost_power > 0:
                command = self.bess_controller.set_discharge(boost_power)
                self.mqtt.publish_bess_command("discharge", command.power)
                logger.info(f"BESS command: discharge {command.power}kW")

        elif total_consumed < grid_available * 0.7:
            charge_power = self.bess_controller.calculate_charge_opportunity(
                grid_available=grid_available,
                current_load=total_consumed
            )

            if charge_power > 0:
                command = self.bess_controller.set_charge(charge_power)
                self.mqtt.publish_bess_command("charge", command.power)
                logger.info(f"BESS command: charge {command.power}kW")
        else:
            self.bess_controller.set_idle()
            self.mqtt.publish_bess_command("idle", 0.0)

    def get_all_sessions(self) -> Dict[str, ChargingSession]:
        """Récupérer toutes les sessions actives"""
        return self.load_manager.sessions.copy()

    async def get_station_status(self) -> dict:
        """Obtenir le statut complet de la station"""
        try:
            # Vérifications de sécurité
            if not self.load_manager:
                logger.error("Load manager is None")
                return {
                    "stationId": self.config.stationId if self.config else "unknown",
                    "timestamp": datetime.now().isoformat(),
                    "error": "Load manager not initialized",
                    "gridCapacity": self.config.gridCapacity if self.config else 0,
                    "activeSessions": 0,
                    "sessions": [],
                    "powerAllocation": []
                }

            total_consumed = self.load_manager.get_total_consumption()
            allocations = self.load_manager.get_current_allocations()

            bess_power = 0.0
            bess_soc = None

            if self.bess_controller:
                try:
                    bess_status = self.bess_controller.get_status()
                    bess_power = bess_status.power
                    bess_soc = bess_status.soc
                except Exception as e:
                    logger.error(f"Error getting BESS status: {e}")

            # Construire la liste des sessions avec toutes les données
            sessions_data = []
            try:
                for session in self.load_manager.sessions.values():
                    session_dict = {
                        "sessionId": session.sessionId,
                        "chargerId": session.chargerId,
                        "connectorId": session.connectorId,
                        "status": session.status,
                        "startTime": session.startTime.isoformat() if session.startTime else None,
                        "vehicleMaxPower": float(session.vehicleMaxPower) if session.vehicleMaxPower else 0.0,
                        "allocatedPower": float(session.allocatedPower) if session.allocatedPower else 0.0,
                        "consumedPower": float(session.consumedPower) if session.consumedPower else 0.0,
                        "offeredPower": float(session.offeredPower) if session.offeredPower else 0.0,
                        "totalEnergy": float(session.totalEnergy) if session.totalEnergy else 0.0,
                        "vehicleSoc": float(session.vehicleSoc) if session.vehicleSoc else 0.0
                    }
                    sessions_data.append(session_dict)
            except Exception as e:
                logger.error(f"Error building sessions data: {e}", exc_info=True)

            # Construire les allocations
            power_allocation_data = []
            try:
                for a in allocations:
                    allocation_dict = {
                        "sessionId": a.sessionId,
                        "chargerId": a.chargerId,
                        "connectorId": a.connectorId,
                        "allocatedPower": float(a.allocatedPower) if a.allocatedPower else 0.0,
                        "consumedPower": float(a.consumedPower) if a.consumedPower else 0.0,
                        "vehicleMaxPower": float(a.vehicleMaxPower) if a.vehicleMaxPower else 0.0
                    }
                    power_allocation_data.append(allocation_dict)
            except Exception as e:
                logger.error(f"Error building allocation data: {e}", exc_info=True)

            return {
                "stationId": self.config.stationId,
                "timestamp": datetime.now().isoformat(),
                "gridCapacity": float(self.config.gridCapacity),
                "gridPower": float(total_consumed - bess_power),
                "bessPower": float(bess_power),
                "bessSOC": float(bess_soc) if bess_soc is not None else None,
                "totalAllocated": float(sum(a.allocatedPower for a in allocations)),
                "totalConsumed": float(total_consumed),
                "activeSessions": len(self.load_manager.sessions),
                "availablePower": float(self.config.gridCapacity - total_consumed + bess_power),
                "mqttConnected": self.mqtt.connected if self.mqtt else False,
                "sessions": sessions_data,
                "powerAllocation": power_allocation_data
            }

        except Exception as e:
            logger.error(f"Error in get_station_status: {e}", exc_info=True)
            raise


# ============================================================================
# Handlers MQTT Globaux
# ============================================================================

async def handle_charger_telemetry_global(message: ChargerTelemetryMessage):
    """Handler global pour la télémétrie"""
    global _global_load_manager

    if not _global_load_manager:
        return

    logger.debug(
        f"Telemetry: {message.charger_id}:{message.connector_id} - "
        f"{message.power / 1000:.1f}kW"
    )

    # Mettre à jour la session en mémoire
    if message.session_id and message.session_id in _global_load_manager.sessions:
        session = _global_load_manager.sessions[message.session_id]
        session.consumedPower = message.power / 1000  # W vers kW

        if message.vehicle_soc is not None:
            session.vehicleSoc = message.vehicle_soc


async def handle_session_start_global(message: SessionStartMessage):
    """Handler global pour le démarrage de session"""
    global _global_station_config, _global_mqtt_service, _global_station_db_id

    logger.info(f"Session start: {message.session_id}")

    try:
        async with AsyncSessionLocal() as db:
            service = SessionServiceMQTT(_global_station_config, db, _global_mqtt_service)
            service.station_db_id = _global_station_db_id

            allocated_power = await service.create_session(
                session_id=message.session_id,
                charger_id=message.charger_id,
                connector_id=message.connector_id,
                vehicle_max_power=message.vehicle_max_power,
                user_id=message.user_id
            )

            # Envoyer la limite de puissance
            _global_mqtt_service.publish_power_limit(
                charger_id=message.charger_id,
                connector_id=message.connector_id,
                power_limit=allocated_power
            )

            logger.info(f"Session {message.session_id} started with {allocated_power:.1f}kW")

    except Exception as e:
        logger.error(f"Error handling session start: {e}", exc_info=True)


async def handle_session_stop_global(message: SessionStopMessage):
    """Handler global pour l'arrêt de session"""
    global _global_station_config, _global_mqtt_service, _global_station_db_id

    logger.info(f"Session stop: {message.session_id}")

    try:
        async with AsyncSessionLocal() as db:
            service = SessionServiceMQTT(_global_station_config, db, _global_mqtt_service)
            service.station_db_id = _global_station_db_id

            await service.stop_session(
                session_id=message.session_id,
                consumed_energy=message.total_energy
            )

            logger.info(f"Session {message.session_id} stopped")

    except Exception as e:
        logger.error(f"Error handling session stop: {e}", exc_info=True)


async def handle_session_update_global(message: SessionUpdateMessage):
    """Handler global pour la mise à jour de session"""
    global _global_station_config, _global_mqtt_service, _global_station_db_id, _global_load_manager

    logger.debug(f"Session update: {message.session_id}")

    try:
        async with AsyncSessionLocal() as db:
            service = SessionServiceMQTT(_global_station_config, db, _global_mqtt_service)
            service.station_db_id = _global_station_db_id

            # Mettre à jour la puissance ET l'énergie
            new_allocated = await service.update_power_and_energy(
                session_id=message.session_id,
                consumed_power=message.consumed_power,
                vehicle_max_power=message.vehicle_max_power,
                total_energy=message.energy_delivered,
                vehicle_soc=message.vehicle_soc
            )

            # Si l'allocation a changé, envoyer la nouvelle limite
            session = _global_load_manager.sessions.get(message.session_id)
            if session and abs(session.allocatedPower - new_allocated) > 0.5:
                _global_mqtt_service.publish_power_limit(
                    charger_id=message.charger_id,
                    connector_id=message.connector_id,
                    power_limit=new_allocated
                )
                logger.info(f"Power limit updated: {message.session_id} -> {new_allocated:.1f}kW")

            logger.debug(
                f"Session {message.session_id}: "
                f"power={message.consumed_power:.1f}kW, "
                f"energy={message.energy_delivered:.2f}kWh, "
                f"soc={message.vehicle_soc:.1f}%"
            )

    except Exception as e:
        logger.error(f"Error handling session update: {e}", exc_info=True)


async def handle_bess_status_global(message: BESSStatusMessage):
    """Handler global pour le statut BESS"""
    global _global_bess_controller, _global_station_db_id, _global_station_config, _global_mqtt_service

    logger.debug(f"BESS status: SOC={message.soc:.1f}%, Power={message.power:.1f}kW")

    if _global_bess_controller:
        # Mettre à jour le contrôleur BESS
        _global_bess_controller.update_from_telemetry(
            soc=message.soc,
            power=message.power
        )

        # Sauvegarder en DB
        try:
            async with AsyncSessionLocal() as db:
                bess_repo = BESSStatusRepository(db)
                bess_status = _global_bess_controller.get_status()

                await bess_repo.create(
                    station_db_id=_global_station_db_id,
                    mode=bess_status.mode.value,
                    power=bess_status.power,
                    soc=bess_status.soc,
                    capacity=bess_status.capacity,
                    available_energy=bess_status.availableEnergy,
                    available_discharge=bess_status.availableDischarge,
                    available_charge=bess_status.availableCharge
                )
        except Exception as e:
            logger.error(f"Error saving BESS status: {e}", exc_info=True)
