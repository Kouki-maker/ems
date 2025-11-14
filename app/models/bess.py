from pydantic import BaseModel, Field
from datetime import datetime
from enum import Enum

class BESSMode(str, Enum):
    IDLE = "idle"
    CHARGING = "charging"
    DISCHARGING = "discharging"
    BOOST = "boost"  # Actively boosting charging sessions

class BESSStatus(BaseModel):
    timestamp: datetime
    mode: BESSMode
    power: float = Field(..., description="Current power (positive=discharge, negative=charge) in kW")
    soc: float = Field(..., description="State of Charge in %")
    capacity: float = Field(..., description="Total capacity in kWh")
    availableEnergy: float = Field(..., description="Available energy above minSOC in kWh")
    availableDischarge: float = Field(..., description="Available discharge power in kW")
    availableCharge: float = Field(..., description="Available charge power in kW")

class BESSCommand(BaseModel):
    command: str = Field(..., description="charge, discharge, idle")
    power: float = Field(..., description="Target power in kW")