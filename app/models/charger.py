from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from enum import Enum
from app.models.connector import ConnectorResponse, ConnectorType


class ChargerStatus(str, Enum):
    AVAILABLE = "available"
    CHARGING = "charging"
    OFFLINE = "offline"
    FAULTED = "faulted"
    MAINTENANCE = "maintenance"


class ChargerBase(BaseModel):
    charger_id: str = Field(..., description="ID du chargeur (ex: CP001)")
    max_power: float = Field(..., description="Puissance max totale du chargeur en kW")
    num_connectors: int = Field(..., description="Nombre de connecteurs")


class ChargerCreate(ChargerBase):
    station_id: int
    manufacturer: Optional[str] = None
    model: Optional[str] = None
    serial_number: Optional[str] = None


class ChargerUpdate(BaseModel):
    max_power: Optional[float] = None
    is_active: Optional[bool] = None
    firmware_version: Optional[str] = None


class ChargerResponse(ChargerBase):
    id: int
    station_id: int
    is_active: bool
    manufacturer: Optional[str] = None
    model: Optional[str] = None
    serial_number: Optional[str] = None
    firmware_version: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ChargerWithConnectors(ChargerResponse):
    connectors: List[ConnectorResponse] = []

    class Config:
        from_attributes = True


class ChargerInfo(BaseModel):
    """Informations simplifiées sur un chargeur pour l'API"""
    charger_id: str
    status: ChargerStatus
    max_power: float
    active_connectors: int
    available_connectors: int
    current_power: float = 0.0
