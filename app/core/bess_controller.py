from app.models.bess import BESSStatus, BESSMode, BESSCommand
from app.models.station import BatteryConfig
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class BESSController:
    """
    Contrôleur pour le Battery Energy Storage System

    Responsabilités:
    - Gérer le boost de puissance pour les sessions de charge
    - Optimiser la charge/décharge de la batterie
    - Maintenir le SOC au-dessus du minimum (10%)
    - Charger la batterie pendant les périodes de faible demande
    """

    def __init__(self, battery_config: BatteryConfig):
        self.config = battery_config
        self.current_soc = 100.0  # Commencer avec batterie pleine
        self.current_power = 0.0  # Positive = discharge, Negative = charge
        self.mode = BESSMode.IDLE

    def get_status(self) -> BESSStatus:
        """Obtenir le statut actuel de la batterie"""
        available_energy = self._calculate_available_energy()

        return BESSStatus(
            timestamp=datetime.now(),
            mode=self.mode,
            power=self.current_power,
            soc=self.current_soc,
            capacity=self.config.initialCapacity,
            availableEnergy=available_energy,
            availableDischarge=self._calculate_available_discharge(),
            availableCharge=self._calculate_available_charge()
        )

    def _calculate_available_energy(self) -> float:
        """
        Calculer l'énergie disponible au-dessus du SOC minimum
        """
        usable_soc = max(0, self.current_soc - self.config.minSOC)
        return (usable_soc / 100) * self.config.initialCapacity

    def _calculate_available_discharge(self) -> float:
        """
        Calculer la puissance de décharge disponible

        Limitée par:
        - La puissance max de la batterie
        - L'énergie disponible au-dessus du SOC minimum
        """
        if self.current_soc <= self.config.minSOC:
            return 0.0

        # Puissance maximale théorique
        max_power = self.config.power

        # Limiter par l'énergie disponible (en supposant décharge sur 1 heure)
        available_energy = self._calculate_available_energy()
        energy_limited_power = available_energy  # kWh -> kW pour 1h

        return min(max_power, energy_limited_power)

    def _calculate_available_charge(self) -> float:
        """
        Calculer la puissance de charge disponible

        Limitée par:
        - La puissance max de la batterie
        - L'espace disponible jusqu'au SOC maximum
        """
        if self.current_soc >= self.config.maxSOC:
            return 0.0

        # Puissance maximale théorique
        max_power = self.config.power

        # Limiter par l'espace disponible
        available_capacity = ((self.config.maxSOC - self.current_soc) / 100) * self.config.initialCapacity
        capacity_limited_power = available_capacity  # kWh -> kW pour 1h

        return min(max_power, capacity_limited_power)

    def calculate_boost_power(
            self,
            grid_available: float,
            total_demand: float
    ) -> float:
        """
        Calculer la puissance de boost nécessaire depuis la batterie

        Args:
            grid_available: Puissance disponible du réseau (kW)
            total_demand: Demande totale des sessions de charge (kW)

        Returns:
            float: Puissance à fournir depuis la batterie (kW)
        """
        # Si la demande dépasse la capacité du réseau
        shortage = max(0, total_demand - grid_available)

        if shortage == 0:
            return 0.0

        # Limiter par la puissance de décharge disponible
        available_discharge = self._calculate_available_discharge()
        boost_power = min(shortage, available_discharge)

        logger.info(f"BESS boost calculated: shortage={shortage}kW, "
                    f"available={available_discharge}kW, boost={boost_power}kW")

        return boost_power

    def calculate_charge_opportunity(
            self,
            grid_available: float,
            current_load: float
    ) -> float:
        """
        Calculer l'opportunité de charger la batterie

        Charge la batterie quand il y a de la puissance disponible
        et que le SOC est en dessous du maximum

        Returns:
            float: Puissance de charge recommandée (valeur positive en kW)
        """
        if self.current_soc >= self.config.maxSOC:
            return 0.0

        # Puissance disponible sur le réseau après la charge actuelle
        spare_power = grid_available - current_load

        if spare_power <= 0:
            return 0.0

        # Limiter par la capacité de charge
        available_charge = self._calculate_available_charge()
        charge_power = min(spare_power, available_charge)

        # Seuil minimum pour ne pas démarrer la charge pour rien
        MIN_CHARGE_POWER = 5.0  # kW

        if charge_power < MIN_CHARGE_POWER:
            return 0.0

        logger.info(f"BESS charge opportunity: spare={spare_power}kW, "
                    f"available={available_charge}kW, charge={charge_power}kW")

        return charge_power

    def apply_power(self, power: float, duration_seconds: float = 1.0):
        """
        Appliquer une puissance à la batterie et mettre à jour le SOC

        Args:
            power: Puissance en kW (positive=discharge, negative=charge)
            duration_seconds: Durée de l'application en secondes
        """
        # Calculer l'énergie transférée (en kWh)
        energy_kwh = (power * duration_seconds) / 3600

        # Mettre à jour le SOC
        soc_change = (energy_kwh / self.config.initialCapacity) * 100

        # Décharge = diminution du SOC
        # Charge = augmentation du SOC
        new_soc = self.current_soc - soc_change

        # Contraindre entre min et max
        self.current_soc = max(
            self.config.minSOC,
            min(self.config.maxSOC, new_soc)
        )

        self.current_power = power

        # Déterminer le mode
        if abs(power) < 0.1:
            self.mode = BESSMode.IDLE
        elif power > 0:
            self.mode = BESSMode.DISCHARGING
        else:
            self.mode = BESSMode.CHARGING

        logger.debug(f"BESS power applied: {power}kW for {duration_seconds}s, "
                     f"SOC: {self.current_soc:.1f}%")

    def set_discharge(self, power: float) -> BESSCommand:
        """
        Commander une décharge de la batterie

        Args:
            power: Puissance de décharge souhaitée en kW

        Returns:
            BESSCommand: Commande à envoyer à la batterie
        """
        available = self._calculate_available_discharge()
        actual_power = min(power, available)

        if actual_power < 0.1:
            return self.set_idle()

        self.mode = BESSMode.BOOST

        return BESSCommand(
            command="discharge",
            power=actual_power
        )

    def set_charge(self, power: float) -> BESSCommand:
        """
        Commander une charge de la batterie

        Args:
            power: Puissance de charge souhaitée en kW (valeur positive)

        Returns:
            BESSCommand: Commande à envoyer à la batterie
        """
        available = self._calculate_available_charge()
        actual_power = min(power, available)

        if actual_power < 0.1:
            return self.set_idle()

        self.mode = BESSMode.CHARGING

        return BESSCommand(
            command="charge",
            power=actual_power
        )

    def set_idle(self) -> BESSCommand:
        """Mettre la batterie en mode idle"""
        self.mode = BESSMode.IDLE
        self.current_power = 0.0

        return BESSCommand(
            command="idle",
            power=0.0
        )

    def update_from_telemetry(self, soc: float, power: float):
        """
        Mettre à jour l'état depuis la télémétrie réelle

        Args:
            soc: State of Charge en %
            power: Puissance actuelle (positive=discharge, negative=charge)
        """
        self.current_soc = soc
        self.current_power = power

        if abs(power) < 0.1:
            self.mode = BESSMode.IDLE
        elif power > 0:
            self.mode = BESSMode.DISCHARGING
        else:
            self.mode = BESSMode.CHARGING
