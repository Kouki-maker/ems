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
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


class SessionService:
    """
    Service de gestion des sessions de charge avec persistance en base de données
    """

    def __init__(self, station_config: StationConfig, db: AsyncSession):
        self.config = station_config
        self.db = db
        self.load_manager = LoadManagementAlgorithm(station_config)

        # Repositories
        self.station_repo = StationRepository(db)
        self.charger_repo = ChargerRepository(db)
        self.connector_repo = ConnectorRepository(db)
        self.session_repo = SessionRepository(db)
        self.power_metric_repo = PowerMetricRepository(db)
        self.event_repo = EventRepository(db)

        # Initialiser le BESS si présent dans la config
        self.bess_controller: Optional[BESSController] = None
        self.bess_repo: Optional[BESSStatusRepository] = None

        if station_config.battery:
            self.bess_controller = BESSController(station_config.battery)
            self.bess_repo = BESSStatusRepository(db)

        # Station DB ID (sera chargé lors de l'initialisation)
        self.station_db_id: Optional[int] = None

    async def initialize(self):
        """Initialiser le service et charger l'ID de la station"""
        station = await self.station_repo.get_by_station_id(self.config.stationId)
        if station:
            self.station_db_id = station.id
            logger.info(f"SessionService initialized for station {self.config.stationId} (DB ID: {self.station_db_id})")
        else:
            logger.error(f"Station {self.config.stationId} not found in database")
            raise ValueError(f"Station {self.config.stationId} not found")

    def get_all_sessions(self) -> Dict[str, ChargingSession]:
        """Récupérer toutes les sessions actives (en mémoire)"""
        return self.load_manager.sessions.copy()

    async def create_session(
            self,
            session_id: str,
            charger_id: str,
            connector_id: int,
            vehicle_max_power: float,
            user_id: str = None
    ) -> float:
        """
        Créer une nouvelle session de charge

        Returns:
            float: Puissance initialement allouée
        """
        logger.info(f"Creating session {session_id} on {charger_id}:{connector_id}, "
                    f"vehicle max: {vehicle_max_power}kW")

        # Récupérer le chargeur depuis la DB
        charger = await self.charger_repo.get_by_charger_id(
            self.station_db_id,
            charger_id
        )

        if not charger:
            raise ValueError(f"Charger {charger_id} not found")

        # Récupérer le connecteur
        connector = await self.connector_repo.get_by_charger_and_connector_id(
            charger.id,
            connector_id
        )

        if not connector:
            raise ValueError(f"Connector {connector_id} not found on charger {charger_id}")

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

        # Obtenir le statut BESS si disponible
        bess_status = None
        if self.bess_controller:
            bess_status = self.bess_controller.get_status()
            # Sauvegarder le statut BESS
            await self.bess_repo.create(
                station_db_id=self.station_db_id,
                mode=bess_status.mode.value,
                power=bess_status.power,
                soc=bess_status.soc,
                capacity=bess_status.capacity,
                available_energy=bess_status.availableEnergy,
                available_discharge=bess_status.availableDischarge,
                available_charge=bess_status.availableCharge
            )

        # Créer la session via le load manager (en mémoire pour calculs rapides)
        allocated = self.load_manager.handle_session_start(
            session_id=session_id,
            charger_id=charger_id,
            connector_id=connector_id,
            vehicle_max_power=vehicle_max_power
        )

        # Mettre à jour l'allocation dans la DB
        await self.session_repo.update_power(
            session_id=session_id,
            consumed_power=0.0,
            allocated_power=allocated,
            vehicle_max_power=vehicle_max_power
        )

        # Log de l'événement
        await self.event_repo.create(
            event_type="session_start",
            description=f"Session {session_id} started on {charger_id}:{connector_id}",
            data={
                "session_id": session_id,
                "charger_id": charger_id,
                "connector_id": connector_id,
                "vehicle_max_power": vehicle_max_power,
                "allocated_power": allocated
            }
        )

        # Optimiser l'utilisation de la BESS si nécessaire
        await self._optimize_bess_usage()

        # Sauvegarder les métriques de puissance
        await self._save_power_metrics()

        return allocated

    async def stop_session(
            self,
            session_id: str,
            consumed_energy: float
    ) -> bool:
        """
        Arrêter une session de charge

        Returns:
            bool: True si succès
        """
        logger.info(f"Stopping session {session_id}, energy: {consumed_energy}kWh")

        # Arrêter la session dans le load manager
        success = self.load_manager.handle_session_stop(
            session_id=session_id,
            consumed_energy=consumed_energy
        )

        if not success:
            return False

        # Mettre à jour dans la DB
        db_session = await self.session_repo.complete_session(
            session_id=session_id,
            total_energy=consumed_energy
        )

        if not db_session:
            logger.warning(f"Session {session_id} not found in database")
            return False

        # Libérer le connecteur
        await self.connector_repo.update_status(db_session.connector_id, "available")

        # Log de l'événement
        await self.event_repo.create(
            event_type="session_stop",
            description=f"Session {session_id} stopped",
            data={
                "session_id": session_id,
                "consumed_energy": consumed_energy,
                "duration": (datetime.utcnow() - db_session.start_time).total_seconds()
            }
        )

        # Réévaluer l'utilisation de la BESS
        await self._optimize_bess_usage()

        # Sauvegarder les métriques
        await self._save_power_metrics()

        return True

    async def update_power(
            self,
            session_id: str,
            consumed_power: float,
            vehicle_max_power: float
    ) -> float:
        """
        Mettre à jour la consommation d'une session

        Returns:
            float: Nouvelle puissance allouée
        """
        # Obtenir le statut BESS si disponible
        bess_status = None
        if self.bess_controller:
            bess_status = self.bess_controller.get_status()

        # Mettre à jour via le load manager
        new_allocated = self.load_manager.handle_power_update(
            session_id=session_id,
            consumed_power=consumed_power,
            vehicle_max_power=vehicle_max_power,
            bess_status=bess_status
        )

        # Mettre à jour dans la DB
        await self.session_repo.update_power(
            session_id=session_id,
            consumed_power=consumed_power,
            allocated_power=new_allocated,
            vehicle_max_power=vehicle_max_power
        )

        # Optimiser l'utilisation de la BESS
        await self._optimize_bess_usage()

        # Appliquer la puissance BESS (simulation du temps qui passe)
        if self.bess_controller and self.bess_controller.current_power != 0:
            # Simuler 1 seconde d'écoulement
            self.bess_controller.apply_power(
                self.bess_controller.current_power,
                duration_seconds=1.0
            )

            # Sauvegarder le nouveau statut BESS
            if self.bess_repo:
                bess_status = self.bess_controller.get_status()
                await self.bess_repo.create(
                    station_db_id=self.station_db_id,
                    mode=bess_status.mode.value,
                    power=bess_status.power,
                    soc=bess_status.soc,
                    capacity=bess_status.capacity,
                    available_energy=bess_status.availableEnergy,
                    available_discharge=bess_status.availableDischarge,
                    available_charge=bess_status.availableCharge
                )

        # Sauvegarder les métriques périodiquement (tous les 5 updates)
        # Pour éviter trop d'écritures en DB
        if hash(session_id) % 5 == 0:
            await self._save_power_metrics()

        return new_allocated

    async def _optimize_bess_usage(self):
        """
        Optimiser l'utilisation de la BESS
        """
        if not self.bess_controller:
            return

        # Calculer la puissance disponible du réseau
        grid_available = self.config.gridCapacity - self.config.staticLoad

        # Calculer la demande totale actuelle
        total_consumed = sum(
            s.consumedPower for s in self.load_manager.sessions.values()
        )

        total_demand = sum(
            min(s.vehicleMaxPower, self.load_manager._get_charger_connector_limit(s))
            for s in self.load_manager.sessions.values()
        )

        # Décision: Boost ou Charge ?
        if total_demand > grid_available:
            # Besoin de boost
            boost_power = self.bess_controller.calculate_boost_power(
                grid_available=grid_available,
                total_demand=total_demand
            )

            if boost_power > 0:
                command = self.bess_controller.set_discharge(boost_power)
                logger.info(f"BESS command: discharge {command.power}kW")

                # Log de l'événement
                await self.event_repo.create(
                    event_type="bess_boost",
                    description=f"BESS boost activated: {command.power}kW",
                    data={
                        "power": command.power,
                        "mode": "discharge",
                        "reason": "demand_exceeds_grid"
                    }
                )

        elif total_consumed < grid_available * 0.7:
            # Opportunité de charger (utilisation < 70%)
            charge_power = self.bess_controller.calculate_charge_opportunity(
                grid_available=grid_available,
                current_load=total_consumed
            )

            if charge_power > 0:
                command = self.bess_controller.set_charge(charge_power)
                logger.info(f"BESS command: charge {command.power}kW")

                # Log de l'événement
                await self.event_repo.create(
                    event_type="bess_charge",
                    description=f"BESS charging: {command.power}kW",
                    data={
                        "power": command.power,
                        "mode": "charge",
                        "reason": "spare_capacity"
                    }
                )

        else:
            # Idle
            self.bess_controller.set_idle()

    async def _save_power_metrics(self):
        """
        Sauvegarder les métriques de puissance actuelles
        """
        total_consumed = self.load_manager.get_total_consumption()
        allocations = self.load_manager.get_current_allocations()

        bess_power = 0.0
        if self.bess_controller:
            bess_power = self.bess_controller.current_power

        await self.power_metric_repo.create(
            station_db_id=self.station_db_id,
            grid_power=total_consumed - bess_power,
            bess_power=bess_power,
            total_allocated=sum(a.allocatedPower for a in allocations),
            total_consumed=total_consumed,
            available_power=self.config.gridCapacity - total_consumed + bess_power,
            active_sessions=len(self.load_manager.sessions)
        )

    async def get_station_status(self) -> dict:
        """Obtenir le statut complet de la station"""
        total_consumed = self.load_manager.get_total_consumption()
        allocations = self.load_manager.get_current_allocations()

        bess_power = 0.0
        bess_soc = None

        if self.bess_controller:
            bess_status = self.bess_controller.get_status()
            bess_power = bess_status.power
            bess_soc = bess_status.soc

        return {
            "stationId": self.config.stationId,
            "timestamp": datetime.now().isoformat(),
            "gridCapacity": self.config.gridCapacity,
            "gridPower": total_consumed - bess_power,
            "bessPower": bess_power,
            "bessSOC": bess_soc,
            "totalAllocated": sum(a.allocatedPower for a in allocations),
            "totalConsumed": total_consumed,
            "activeSessions": len(self.load_manager.sessions),
            "availablePower": self.config.gridCapacity - total_consumed + bess_power,
            "sessions": [s.dict() for s in self.load_manager.sessions.values()],
            "powerAllocation": [a.dict() for a in allocations]
        }

    async def get_session_statistics(self, days: int = 7) -> dict:
        """Obtenir les statistiques des sessions"""
        from datetime import timedelta

        start_date = datetime.utcnow() - timedelta(days=days)
        stats = await self.session_repo.get_session_statistics(
            station_db_id=self.station_db_id,
            start_date=start_date
        )

        return stats

    async def get_power_history(self, minutes: int = 60) -> list:
        """Obtenir l'historique de puissance"""
        metrics = await self.power_metric_repo.get_recent_metrics(
            station_db_id=self.station_db_id,
            minutes=minutes
        )

        return [
            {
                "timestamp": m.timestamp.isoformat(),
                "grid_power": m.grid_power,
                "bess_power": m.bess_power,
                "total_consumed": m.total_consumed,
                "active_sessions": m.active_sessions
            }
            for m in metrics
        ]
