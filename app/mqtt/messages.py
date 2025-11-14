from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


# Messages des Chargeurs vers EMS

class ChargerTelemetryMessage(BaseModel):
    """Télémétrie envoyée par le chargeur"""
    timestamp: datetime
    charger_id: str
    connector_id: int

    # Power data
    voltage: float = Field(..., description="Tension en V")
    current: float = Field(..., description="Courant en A")
    power: float = Field(..., description="Puissance instantanée en W")

    # Session info
    session_id: Optional[str] = None
    vehicle_soc: Optional[float] = Field(None, ge=0, le=100)

    # Status
    status: str = Field(..., description="available, charging, faulted, etc.")
    temperature: Optional[float] = None


class SessionStartMessage(BaseModel):
    """Message de démarrage de session depuis le chargeur"""
    timestamp: datetime
    charger_id: str
    connector_id: int
    session_id: str
    vehicle_max_power: float = Field(..., description="Puissance max acceptée par le véhicule en kW")
    user_id: Optional[str] = None
    rfid_tag: Optional[str] = None


class SessionStopMessage(BaseModel):
    """Message d'arrêt de session depuis le chargeur"""
    timestamp: datetime
    charger_id: str
    connector_id: int
    session_id: str
    total_energy: float = Field(..., description="Énergie totale délivrée en kWh")
    reason: str = Field(..., description="user_stop, vehicle_full, error, etc.")


class SessionUpdateMessage(BaseModel):
    """Mise à jour de session depuis le chargeur"""
    timestamp: datetime
    charger_id: str
    connector_id: int
    session_id: str
    consumed_power: float = Field(..., description="Puissance consommée en kW")
    vehicle_max_power: float = Field(..., description="Puissance max acceptée en kW")
    vehicle_soc: Optional[float] = None
    energy_delivered: float = Field(..., description="Énergie délivrée depuis le début en kWh")


# Messages de l'EMS vers les Chargeurs

class PowerLimitCommand(BaseModel):
    """Commande de limitation de puissance vers un connecteur"""
    timestamp: datetime
    charger_id: str
    connector_id: int
    power_limit: float = Field(..., description="Limite de puissance en kW")
    priority: str = Field("normal", description="normal, high, low")


class ChargerCommand(BaseModel):
    """Commande générique vers un chargeur"""
    timestamp: datetime
    charger_id: str
    command: str = Field(..., description="reset, start_session, stop_session, etc.")
    parameters: Optional[dict] = None


# Messages BESS

class BESSStatusMessage(BaseModel):
    """Statut BESS envoyé par la batterie"""
    timestamp: datetime
    soc: float = Field(..., ge=0, le=100, description="State of Charge en %")
    voltage: float = Field(..., description="Tension en V")
    current: float = Field(..., description="Courant en A (+ = décharge, - = charge)")
    power: float = Field(..., description="Puissance en kW (+ = décharge, - = charge)")
    temperature: float = Field(..., description="Température en °C")
    status: str = Field(..., description="idle, charging, discharging, faulted")
    available_capacity: float = Field(..., description="Capacité disponible en kWh")


class BESSCommandMessage(BaseModel):
    """Commande vers le BESS"""
    timestamp: datetime
    command: str = Field(..., description="charge, discharge, idle")
    power: float = Field(..., description="Puissance cible en kW")
    priority: str = Field("normal", description="normal, high, emergency")
