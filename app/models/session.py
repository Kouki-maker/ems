from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from enum import Enum


class SessionStatus(str, Enum):
    ACTIVE = "active"
    CHARGING = "charging"
    COMPLETED = "completed"
    STOPPED = "stopped"


class SessionCreate(BaseModel):
    chargerId: str
    connectorId: int
    vehicleMaxPower: float = Field(..., description="Vehicle max accepted power in kW")


class SessionCreateResponse(BaseModel):
    sessionId: str
    allocatedPower: float = Field(..., description="Initially allocated power in kW")


class SessionStop(BaseModel):
    consumedEnergy: float = Field(..., description="Total energy consumed in kWh")
    duration: Optional[int] = Field(None, description="Session duration in seconds")


class PowerUpdate(BaseModel):
    consumedPower: float = Field(..., description="Currently consumed power in kW")
    vehicleMaxPower: float = Field(..., description="Vehicle max power acceptance in kW")


class PowerUpdateResponse(BaseModel):
    newAllocatedPower: float = Field(..., description="New allocated power in kW")


class ChargingSession(BaseModel):
    sessionId: str
    chargerId: str
    connectorId: int
    status: SessionStatus
    startTime: datetime
    endTime: Optional[datetime] = None

    # Power metrics
    vehicleMaxPower: float
    allocatedPower: float
    consumedPower: float
    offeredPower: float = Field(..., description="Power offered by charger (≥ consumed)")

    # Energy metrics
    totalEnergy: float = Field(0.0, description="Total energy delivered in kWh")

    # Vehicle info
    vehicleSoc: Optional[float] = Field(None, description="Vehicle SOC if available")


class PowerAllocation(BaseModel):
    sessionId: str
    chargerId: str
    connectorId: int
    allocatedPower: float
    consumedPower: float
    vehicleMaxPower: float