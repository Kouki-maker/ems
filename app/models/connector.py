from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from enum import Enum


class ConnectorType(str, Enum):
    CCS2 = "CCS2"
    CHADEMO = "CHAdeMO"
    TYPE2 = "Type2"
    TYPE1 = "Type1"
    GB_T = "GB/T"
    TESLA = "Tesla"


class ConnectorStatus(str, Enum):
    AVAILABLE = "available"
    OCCUPIED = "occupied"
    RESERVED = "reserved"
    UNAVAILABLE = "unavailable"
    FAULTED = "faulted"


class ConnectorBase(BaseModel):
    connector_id: int = Field(..., description="Numéro du connecteur (1, 2, etc.)")
    connector_type: ConnectorType = Field(..., description="Type de connecteur")
    max_power: float = Field(..., description="Puissance max du connecteur en kW")


class ConnectorCreate(ConnectorBase):
    charger_id: int = Field(..., description="ID du chargeur parent")


class ConnectorUpdate(BaseModel):
    status: Optional[ConnectorStatus] = None
    max_power: Optional[float] = None
    is_active: Optional[bool] = None


class ConnectorResponse(ConnectorBase):
    id: int
    charger_id: int
    status: ConnectorStatus
    is_active: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ConnectorWithCharger(ConnectorResponse):
    charger_name: str
    station_id: str