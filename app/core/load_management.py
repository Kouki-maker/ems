from typing import List, Dict, Tuple
from app.models.session import ChargingSession, PowerAllocation
from app.models.station import StationConfig
from app.models.bess import BESSStatus
import logging

logger = logging.getLogger(__name__)


class LoadManagementAlgorithm:
    """
    Core Load Management Algorithm pour Electra EMS

    Responsabilités:
    - Respecter les contraintes du réseau (gridCapacity)
    - Optimiser l'allocation de puissance entre les sessions
    - Gérer l'intégration BESS (battery boost)
    - Réagir en temps réel (<1s) aux événements
    """

    def __init__(self, station_config: StationConfig):
        self.config = station_config
        self.sessions: Dict[str, ChargingSession] = {}

    def calculate_power_allocation(
            self,
            sessions: Dict[str, ChargingSession],
            bess_status: BESSStatus = None
    ) -> List[PowerAllocation]:
        """
        Calculer l'allocation optimale de puissance pour toutes les sessions actives

        Algorithme:
        1. Calculer la puissance disponible totale (grid + BESS)
        2. Déterminer la demande totale des véhicules
        3. Distribuer équitablement si demande > disponible
        4. Respecter les contraintes des chargeurs
        """

        if not sessions:
            return []

        # 1. Calculer la puissance disponible
        available_grid = self.config.gridCapacity - self.config.staticLoad
        available_bess = 0

        if bess_status and self.config.battery:
            available_bess = bess_status.availableDischarge

        total_available = available_grid + available_bess

        # 2. Calculer la demande totale
        total_demand = sum(
            min(s.vehicleMaxPower, self._get_charger_connector_limit(s))
            for s in sessions.values()
        )

        # 3. Déterminer le facteur de limitation
        if total_demand <= total_available:
            # Assez de puissance pour tout le monde
            allocation_factor = 1.0
        else:
            # Distribution proportionnelle
            allocation_factor = total_available / total_demand

        # 4. Calculer les allocations individuelles
        allocations = []

        for session in sessions.values():
            # Puissance maximale que ce connecteur peut recevoir
            connector_limit = self._get_charger_connector_limit(session)

            # Demande du véhicule limitée par le connecteur
            session_demand = min(session.vehicleMaxPower, connector_limit)

            # Allocation finale
            allocated = session_demand * allocation_factor

            # Arrondir à 0.1 kW près
            allocated = round(allocated, 1)

            allocations.append(PowerAllocation(
                sessionId=session.sessionId,
                chargerId=session.chargerId,
                connectorId=session.connectorId,
                allocatedPower=allocated,
                consumedPower=session.consumedPower,
                vehicleMaxPower=session.vehicleMaxPower
            ))

        logger.info(f"Power allocation calculated: {len(allocations)} sessions, "
                    f"total available: {total_available}kW, total allocated: "
                    f"{sum(a.allocatedPower for a in allocations)}kW")

        return allocations

    def _get_charger_connector_limit(self, session: ChargingSession) -> float:
        """
        Obtenir la limite de puissance pour un connecteur spécifique

        La puissance d'un chargeur est partagée entre ses connecteurs.
        Si plusieurs connecteurs sont actifs, la puissance est divisée.
        """
        charger_config = next(
            (c for c in self.config.chargers if c.id == session.chargerId),
            None
        )

        if not charger_config:
            logger.warning(f"Charger {session.chargerId} not found in config")
            return 0

        # Compter combien de connecteurs du même chargeur sont actifs
        active_connectors = sum(
            1 for s in self.sessions.values()
            if s.chargerId == session.chargerId and s.status == "active"
        )

        if active_connectors == 0:
            active_connectors = 1

        # Diviser la puissance du chargeur par le nombre de connecteurs actifs
        return charger_config.maxPower / active_connectors

    def handle_session_start(
            self,
            session_id: str,
            charger_id: str,
            connector_id: int,
            vehicle_max_power: float
    ) -> float:
        """
        Gérer le démarrage d'une nouvelle session

        Returns:
            float: Puissance initialement allouée en kW
        """
        from datetime import datetime

        # Créer la nouvelle session
        new_session = ChargingSession(
            sessionId=session_id,
            chargerId=charger_id,
            connectorId=connector_id,
            status="active",
            startTime=datetime.now(),
            vehicleMaxPower=vehicle_max_power,
            allocatedPower=0.0,
            consumedPower=0.0,
            offeredPower=0.0,
            totalEnergy=0.0
        )

        self.sessions[session_id] = new_session

        # Recalculer l'allocation pour toutes les sessions
        allocations = self.calculate_power_allocation(self.sessions)

        # Mettre à jour les sessions avec les nouvelles allocations
        for alloc in allocations:
            if alloc.sessionId in self.sessions:
                self.sessions[alloc.sessionId].allocatedPower = alloc.allocatedPower

        # Retourner la puissance allouée à la nouvelle session
        new_allocation = next(
            (a for a in allocations if a.sessionId == session_id),
            None
        )

        if new_allocation:
            logger.info(f"Session {session_id} started, allocated {new_allocation.allocatedPower}kW")
            return new_allocation.allocatedPower

        return 0.0

    def handle_session_stop(self, session_id: str, consumed_energy: float) -> bool:
        """
        Gérer l'arrêt d'une session

        Returns:
            bool: True si la session a été arrêtée avec succès
        """
        if session_id not in self.sessions:
            logger.warning(f"Session {session_id} not found")
            return False

        from datetime import datetime

        # Mettre à jour la session
        session = self.sessions[session_id]
        session.status = "completed"
        session.endTime = datetime.now()
        session.totalEnergy = consumed_energy

        # Retirer la session des sessions actives
        del self.sessions[session_id]

        # Recalculer l'allocation pour les sessions restantes
        if self.sessions:
            allocations = self.calculate_power_allocation(self.sessions)

            # Mettre à jour les allocations
            for alloc in allocations:
                if alloc.sessionId in self.sessions:
                    self.sessions[alloc.sessionId].allocatedPower = alloc.allocatedPower

        logger.info(f"Session {session_id} stopped, total energy: {consumed_energy}kWh")
        return True

    def handle_power_update(
            self,
            session_id: str,
            consumed_power: float,
            vehicle_max_power: float,
            bess_status: BESSStatus = None
    ) -> float:
        """
        Gérer une mise à jour de puissance consommée

        Retourne la nouvelle puissance allouée après optimisation
        """
        if session_id not in self.sessions:
            logger.warning(f"Session {session_id} not found")
            return 0.0

        # Mettre à jour les informations de la session
        session = self.sessions[session_id]
        session.consumedPower = consumed_power
        session.vehicleMaxPower = vehicle_max_power

        # Recalculer l'allocation globale
        allocations = self.calculate_power_allocation(self.sessions, bess_status)

        # Mettre à jour toutes les sessions
        for alloc in allocations:
            if alloc.sessionId in self.sessions:
                self.sessions[alloc.sessionId].allocatedPower = alloc.allocatedPower
                self.sessions[alloc.sessionId].offeredPower = alloc.allocatedPower

        # Retourner la nouvelle allocation pour cette session
        new_allocation = next(
            (a for a in allocations if a.sessionId == session_id),
            None
        )

        if new_allocation:
            logger.debug(f"Session {session_id} power update: consumed={consumed_power}kW, "
                         f"allocated={new_allocation.allocatedPower}kW")
            return new_allocation.allocatedPower

        return 0.0

    def get_current_allocations(self) -> List[PowerAllocation]:
        """Obtenir les allocations actuelles pour toutes les sessions"""
        return [
            PowerAllocation(
                sessionId=s.sessionId,
                chargerId=s.chargerId,
                connectorId=s.connectorId,
                allocatedPower=s.allocatedPower,
                consumedPower=s.consumedPower,
                vehicleMaxPower=s.vehicleMaxPower
            )
            for s in self.sessions.values()
        ]

    def get_total_consumption(self) -> float:
        """Calculer la consommation totale actuelle"""
        return sum(s.consumedPower for s in self.sessions.values()) + self.config.staticLoad

    def is_grid_compliant(self) -> bool:
        """Vérifier si la consommation respecte la limite du réseau"""
        total = self.get_total_consumption()
        return total <= self.config.gridCapacity