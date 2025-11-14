from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Enum, Boolean, JSON
from sqlalchemy.orm import relationship, declarative_base
from datetime import datetime
import enum

Base = declarative_base()


class SessionStatusEnum(str, enum.Enum):
    PENDING = "pending"
    ACTIVE = "active"
    CHARGING = "charging"
    COMPLETED = "completed"
    STOPPED = "stopped"
    FAILED = "failed"


class BESSModeEnum(str, enum.Enum):
    IDLE = "idle"
    CHARGING = "charging"
    DISCHARGING = "discharging"
    BOOST = "boost"


class ConnectorTypeEnum(str, enum.Enum):
    """Types de connecteurs standards"""
    CCS2 = "CCS2"  # Combined Charging System (Europe)
    CHADEMO = "CHAdeMO"  # Standard japonais
    TYPE2 = "Type2"  # Mennekes (AC)
    TYPE1 = "Type1"  # SAE J1772 (AC)
    GB_T = "GB/T"  # Standard chinois
    TESLA = "Tesla"  # Supercharger Tesla


class ConnectorStatusEnum(str, enum.Enum):
    AVAILABLE = "available"
    OCCUPIED = "occupied"
    RESERVED = "reserved"
    UNAVAILABLE = "unavailable"
    FAULTED = "faulted"


class Station(Base):
    """Table des stations de recharge"""
    __tablename__ = "stations"

    id = Column(Integer, primary_key=True, index=True)
    station_id = Column(String, unique=True, index=True, nullable=False)
    grid_capacity = Column(Float, nullable=False)
    static_load = Column(Float, default=3.0)
    config = Column(JSON)  # Configuration complète de la station
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relations
    chargers = relationship("Charger", back_populates="station", cascade="all, delete-orphan")
    sessions = relationship("ChargingSession", back_populates="station")
    power_metrics = relationship("PowerMetric", back_populates="station", cascade="all, delete-orphan")
    bess_status = relationship("BESSStatusLog", back_populates="station", cascade="all, delete-orphan")


class Charger(Base):
    """Table des chargeurs"""
    __tablename__ = "chargers"

    id = Column(Integer, primary_key=True, index=True)
    station_id = Column(Integer, ForeignKey("stations.id"), nullable=False)
    charger_id = Column(String, index=True, nullable=False)
    max_power = Column(Float, nullable=False, comment="Puissance max totale du chargeur en kW")
    num_connectors = Column(Integer, nullable=False)
    is_active = Column(Boolean, default=True)
    manufacturer = Column(String, nullable=True)
    model = Column(String, nullable=True)
    serial_number = Column(String, nullable=True)
    firmware_version = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relations
    station = relationship("Station", back_populates="chargers")
    connectors = relationship("Connector", back_populates="charger", cascade="all, delete-orphan")
    sessions = relationship("ChargingSession", back_populates="charger")


class Connector(Base):
    """Table des connecteurs - chaque chargeur peut avoir plusieurs connecteurs"""
    __tablename__ = "connectors"

    id = Column(Integer, primary_key=True, index=True)
    charger_id = Column(Integer, ForeignKey("chargers.id"), nullable=False, index=True)
    connector_id = Column(Integer, nullable=False, comment="Numéro du connecteur (1, 2, etc.)")
    connector_type = Column(Enum(ConnectorTypeEnum), nullable=False)
    max_power = Column(Float, nullable=False, comment="Puissance max de ce connecteur en kW")
    status = Column(Enum(ConnectorStatusEnum), default=ConnectorStatusEnum.AVAILABLE)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relations
    charger = relationship("Charger", back_populates="connectors")
    sessions = relationship("ChargingSession", back_populates="connector")

    # Contrainte unique : un seul connecteur avec un ID donné par chargeur
    __table_args__ = (
        # UniqueConstraint('charger_id', 'connector_id', name='uq_charger_connector'),
    )


class ChargingSession(Base):
    """Table des sessions de charge"""
    __tablename__ = "charging_sessions"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(String, unique=True, index=True, nullable=False)
    station_id = Column(Integer, ForeignKey("stations.id"), nullable=False)
    charger_id = Column(Integer, ForeignKey("chargers.id"), nullable=False)
    connector_id = Column(Integer, ForeignKey("connectors.id"), nullable=False)

    # Status
    status = Column(Enum(SessionStatusEnum), default=SessionStatusEnum.PENDING, index=True)

    # Timestamps
    start_time = Column(DateTime, default=datetime.utcnow, nullable=False)
    end_time = Column(DateTime, nullable=True)

    # Power metrics
    vehicle_max_power = Column(Float, nullable=False)
    allocated_power = Column(Float, default=0.0)
    consumed_power = Column(Float, default=0.0)
    offered_power = Column(Float, default=0.0)

    # Energy
    total_energy = Column(Float, default=0.0)  # kWh

    # Vehicle info
    vehicle_soc = Column(Float, nullable=True)
    vehicle_id = Column(String, nullable=True)

    # User info
    user_id = Column(String, nullable=True)
    rfid_tag = Column(String, nullable=True)

    # Relations
    station = relationship("Station", back_populates="sessions")
    charger = relationship("Charger", back_populates="sessions")
    connector = relationship("Connector", back_populates="sessions")
    power_updates = relationship("SessionPowerUpdate", back_populates="session", cascade="all, delete-orphan")


class SessionPowerUpdate(Base):
    """Historique des mises à jour de puissance par session"""
    __tablename__ = "session_power_updates"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("charging_sessions.id"), nullable=False, index=True)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    consumed_power = Column(Float, nullable=False)
    allocated_power = Column(Float, nullable=False)
    vehicle_max_power = Column(Float, nullable=False)

    # Relations
    session = relationship("ChargingSession", back_populates="power_updates")


class PowerMetric(Base):
    """Métriques de puissance de la station (time-series)"""
    __tablename__ = "power_metrics"

    id = Column(Integer, primary_key=True, index=True)
    station_id = Column(Integer, ForeignKey("stations.id"), nullable=False, index=True)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    # Power data
    grid_power = Column(Float, nullable=False)
    bess_power = Column(Float, default=0.0)
    total_allocated = Column(Float, nullable=False)
    total_consumed = Column(Float, nullable=False)
    available_power = Column(Float, nullable=False)

    # Session info
    active_sessions = Column(Integer, default=0)

    # Relations
    station = relationship("Station", back_populates="power_metrics")


class BESSStatusLog(Base):
    """Historique du statut BESS (time-series)"""
    __tablename__ = "bess_status_logs"

    id = Column(Integer, primary_key=True, index=True)
    station_id = Column(Integer, ForeignKey("stations.id"), nullable=False, index=True)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    mode = Column(Enum(BESSModeEnum), nullable=False)
    power = Column(Float, nullable=False)  # Positive = discharge, Negative = charge
    soc = Column(Float, nullable=False)
    capacity = Column(Float, nullable=False)
    available_energy = Column(Float, nullable=False)
    available_discharge = Column(Float, nullable=False)
    available_charge = Column(Float, nullable=False)

    # Relations
    station = relationship("Station", back_populates="bess_status")


class LoadManagementEvent(Base):
    """Log des événements du Load Management Algorithm"""
    __tablename__ = "load_management_events"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    event_type = Column(String, nullable=False)  # session_start, session_stop, power_update, reallocation
    description = Column(String, nullable=False)
    data = Column(JSON)  # Données additionnelles en JSON
