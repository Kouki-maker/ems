from pydantic import BaseModel, Field
from typing import List, Optional
from app.models.connector import ConnectorType

class ConnectorConfig(BaseModel):
    """Configuration d'un connecteur"""
    connector_id: int = Field(..., description="Numéro du connecteur (1, 2, etc.)")
    connector_type: ConnectorType = Field(..., description="Type de connecteur")
    max_power: float = Field(..., description="Puissance max du connecteur en kW")

class ChargerConfig(BaseModel):
    """Configuration d'un chargeur"""
    id: str = Field(..., description="Charger ID (e.g., CP001)")
    maxPower: int = Field(..., description="Max power in kW shared between connectors")
    connectors: List[ConnectorConfig] = Field(..., description="Liste des connecteurs")
    manufacturer: Optional[str] = None
    model: Optional[str] = None

class BatteryConfig(BaseModel):
    initialCapacity: float = Field(..., description="Battery capacity in kWh")
    power: int = Field(..., description="Max charge/discharge power in kW")
    minSOC: float = Field(10.0, description="Minimum State of Charge in %")
    maxSOC: float = Field(100.0, description="Maximum State of Charge in %")

class StationConfig(BaseModel):
    stationId: str
    gridCapacity: int = Field(..., description="Grid connection capacity in kW")
    chargers: List[ChargerConfig]
    battery: Optional[BatteryConfig] = None
    staticLoad: float = Field(3.0, description="Station auxiliaries in kW")

class StationStatus(BaseModel):
    stationId: str
    timestamp: str
    gridPower: float = Field(..., description="Current grid power consumption in kW")
    bessPower: float = Field(0.0, description="BESS power (positive=discharge, negative=charge)")
    bessSOC: Optional[float] = Field(None, description="Battery SOC in %")
    totalAllocated: float
    totalConsumed: float
    activeSessions: int
    availablePower: float