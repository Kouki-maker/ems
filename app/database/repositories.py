from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, desc, func, case
from sqlalchemy.orm import selectinload
from app.database.models import (
    Station, Charger, ChargingSession, Connector, SessionPowerUpdate,
    PowerMetric, BESSStatusLog, LoadManagementEvent,
    SessionStatusEnum
)
from typing import List, Optional
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)


class StationRepository:
    """Repository pour les stations"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, station_id: str, grid_capacity: float,
                     static_load: float, config: dict) -> Station:
        """Créer une nouvelle station"""
        station = Station(
            station_id=station_id,
            grid_capacity=grid_capacity,
            static_load=static_load,
            config=config
        )
        self.db.add(station)
        await self.db.commit()
        await self.db.refresh(station)
        return station

    async def get_by_station_id(self, station_id: str) -> Optional[Station]:
        """Récupérer une station par son ID"""
        result = await self.db.execute(
            select(Station)
            .where(Station.station_id == station_id)
            .options(selectinload(Station.chargers))
        )
        return result.scalar_one_or_none()

    async def get_or_create(self, station_id: str, grid_capacity: float,
                            static_load: float, config: dict) -> Station:
        """Récupérer ou créer une station"""
        station = await self.get_by_station_id(station_id)
        if not station:
            station = await self.create(station_id, grid_capacity, static_load, config)
        return station


class SessionRepository:
    """Repository pour les sessions de charge"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, session_id: str, station_db_id: int,
                     charger_db_id: int, connector_id: int,
                     vehicle_max_power: float) -> ChargingSession:
        """Créer une nouvelle session"""
        session = ChargingSession(
            session_id=session_id,
            station_id=station_db_id,
            charger_id=charger_db_id,
            connector_id=connector_id,
            vehicle_max_power=vehicle_max_power,
            status=SessionStatusEnum.ACTIVE
        )
        self.db.add(session)
        await self.db.commit()
        await self.db.refresh(session)
        return session

    async def get_by_session_id(self, session_id: str) -> Optional[ChargingSession]:
        """Récupérer une session par son ID"""
        result = await self.db.execute(
            select(ChargingSession)
            .where(ChargingSession.session_id == session_id)
            .options(
                selectinload(ChargingSession.station),
                selectinload(ChargingSession.charger)
            )
        )
        return result.scalar_one_or_none()

    async def get_active_sessions(self, station_db_id: int) -> List[ChargingSession]:
        """Récupérer toutes les sessions actives d'une station"""
        result = await self.db.execute(
            select(ChargingSession)
            .where(
                and_(
                    ChargingSession.station_id == station_db_id,
                    ChargingSession.status == SessionStatusEnum.ACTIVE
                )
            )
            .options(selectinload(ChargingSession.charger))
        )
        return list(result.scalars().all())

    async def update_power(self, session_id: str, consumed_power: float,
                           allocated_power: float, vehicle_max_power: float,
                           total_energy: float = None, vehicle_soc: float = None):
        """
        Mettre à jour les données de puissance d'une session
        """
        session = await self.get_by_session_id(session_id)
        if session:
            session.consumed_power = consumed_power
            session.allocated_power = allocated_power
            session.vehicle_max_power = vehicle_max_power
            session.offered_power = allocated_power

            # Mettre à jour l'énergie si fournie
            if total_energy is not None:
                session.total_energy = total_energy

            # Mettre à jour le SOC si fourni
            if vehicle_soc is not None:
                session.vehicle_soc = vehicle_soc

            # Ajouter un log de mise à jour
            update_log = SessionPowerUpdate(
                session_id=session.id,
                consumed_power=consumed_power,
                allocated_power=allocated_power,
                vehicle_max_power=vehicle_max_power
            )
            self.db.add(update_log)

            await self.db.commit()
            await self.db.refresh(session)
            return session
        return None


class PowerMetricRepository:
    """Repository pour les métriques de puissance"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, station_db_id: int, grid_power: float,
                     bess_power: float, total_allocated: float,
                     total_consumed: float, available_power: float,
                     active_sessions: int) -> PowerMetric:
        """Enregistrer une métrique de puissance"""
        metric = PowerMetric(
            station_id=station_db_id,
            grid_power=grid_power,
            bess_power=bess_power,
            total_allocated=total_allocated,
            total_consumed=total_consumed,
            available_power=available_power,
            active_sessions=active_sessions
        )
        self.db.add(metric)
        await self.db.commit()
        return metric

    async def get_recent_metrics(self, station_db_id: int,
                                 minutes: int = 60) -> List[PowerMetric]:
        """Récupérer les métriques récentes"""
        cutoff = datetime.utcnow() - timedelta(minutes=minutes)

        result = await self.db.execute(
            select(PowerMetric)
            .where(
                and_(
                    PowerMetric.station_id == station_db_id,
                    PowerMetric.timestamp >= cutoff
                )
            )
            .order_by(PowerMetric.timestamp)
        )
        return list(result.scalars().all())

    async def get_average_metrics(self, station_db_id: int,
                                  start_date: datetime,
                                  end_date: datetime) -> dict:
        """Calculer les métriques moyennes sur une période"""
        result = await self.db.execute(
            select(
                func.avg(PowerMetric.grid_power).label('avg_grid_power'),
                func.max(PowerMetric.grid_power).label('peak_grid_power'),
                func.avg(PowerMetric.bess_power).label('avg_bess_power'),
                func.avg(PowerMetric.total_consumed).label('avg_consumption'),
                func.avg(PowerMetric.active_sessions).label('avg_active_sessions')
            )
            .where(
                and_(
                    PowerMetric.station_id == station_db_id,
                    PowerMetric.timestamp >= start_date,
                    PowerMetric.timestamp <= end_date
                )
            )
        )
        stats = result.one()

        return {
            'avg_grid_power': float(stats.avg_grid_power or 0),
            'peak_grid_power': float(stats.peak_grid_power or 0),
            'avg_bess_power': float(stats.avg_bess_power or 0),
            'avg_consumption': float(stats.avg_consumption or 0),
            'avg_active_sessions': float(stats.avg_active_sessions or 0)
        }


class BESSStatusRepository:
    """Repository pour le statut BESS"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, station_db_id: int, mode: str, power: float,
                     soc: float, capacity: float, available_energy: float,
                     available_discharge: float, available_charge: float) -> BESSStatusLog:
        """Enregistrer un statut BESS"""
        log = BESSStatusLog(
            station_id=station_db_id,
            mode=mode,
            power=power,
            soc=soc,
            capacity=capacity,
            available_energy=available_energy,
            available_discharge=available_discharge,
            available_charge=available_charge
        )
        self.db.add(log)
        await self.db.commit()
        return log

    async def get_latest(self, station_db_id: int) -> Optional[BESSStatusLog]:
        """Récupérer le dernier statut BESS"""
        result = await self.db.execute(
            select(BESSStatusLog)
            .where(BESSStatusLog.station_id == station_db_id)
            .order_by(desc(BESSStatusLog.timestamp))
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_soc_history(self, station_db_id: int,
                              hours: int = 24) -> List[BESSStatusLog]:
        """Récupérer l'historique du SOC"""
        cutoff = datetime.utcnow() - timedelta(hours=hours)

        result = await self.db.execute(
            select(BESSStatusLog)
            .where(
                and_(
                    BESSStatusLog.station_id == station_db_id,
                    BESSStatusLog.timestamp >= cutoff
                )
            )
            .order_by(BESSStatusLog.timestamp)
        )
        return list(result.scalars().all())


class EventRepository:
    """Repository pour les événements du Load Management"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, event_type: str, description: str,
                     data: dict = None) -> LoadManagementEvent:
        """Enregistrer un événement"""
        event = LoadManagementEvent(
            event_type=event_type,
            description=description,
            data=data
        )
        self.db.add(event)
        await self.db.commit()
        return event

    async def get_recent_events(self, limit: int = 100) -> List[LoadManagementEvent]:
        """Récupérer les événements récents"""
        result = await self.db.execute(
            select(LoadManagementEvent)
            .order_by(desc(LoadManagementEvent.timestamp))
            .limit(limit)
        )
        return list(result.scalars().all())


class ConnectorRepository:
    """Repository pour les connecteurs"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, charger_db_id: int, connector_id: int,
                     connector_type: str, max_power: float) -> Connector:
        """Créer un nouveau connecteur"""
        from app.database.models import Connector, ConnectorTypeEnum, ConnectorStatusEnum

        connector = Connector(
            charger_id=charger_db_id,
            connector_id=connector_id,
            connector_type=ConnectorTypeEnum(connector_type),
            max_power=max_power,
            status=ConnectorStatusEnum.AVAILABLE
        )
        self.db.add(connector)
        await self.db.commit()
        await self.db.refresh(connector)
        return connector

    async def get_by_id(self, connector_db_id: int) -> Optional[Connector]:
        """Récupérer un connecteur par son ID de base de données"""
        from app.database.models import Connector

        result = await self.db.execute(
            select(Connector)
            .where(Connector.id == connector_db_id)
            .options(selectinload(Connector.charger))
        )
        return result.scalar_one_or_none()

    async def get_by_charger_and_connector_id(self, charger_db_id: int,
                                              connector_id: int) -> Optional[Connector]:
        """Récupérer un connecteur par son chargeur et son numéro"""
        from app.database.models import Connector

        result = await self.db.execute(
            select(Connector)
            .where(
                and_(
                    Connector.charger_id == charger_db_id,
                    Connector.connector_id == connector_id
                )
            )
        )
        return result.scalar_one_or_none()

    async def get_connectors_by_charger(self, charger_db_id: int) -> List[Connector]:
        """Récupérer tous les connecteurs d'un chargeur"""
        from app.database.models import Connector

        result = await self.db.execute(
            select(Connector)
            .where(Connector.charger_id == charger_db_id)
            .order_by(Connector.connector_id)
        )
        return list(result.scalars().all())

    async def update_status(self, connector_db_id: int,
                            status: str) -> Optional[Connector]:
        """Mettre à jour le statut d'un connecteur"""
        from app.database.models import Connector, ConnectorStatusEnum

        connector = await self.get_by_id(connector_db_id)
        if connector:
            connector.status = ConnectorStatusEnum(status)
            connector.updated_at = datetime.utcnow()
            await self.db.commit()
            await self.db.refresh(connector)
            return connector
        return None

    async def get_available_connectors(self, station_db_id: int) -> List[Connector]:
        """Récupérer tous les connecteurs disponibles d'une station"""
        from app.database.models import Connector, Charger, ConnectorStatusEnum

        result = await self.db.execute(
            select(Connector)
            .join(Charger)
            .where(
                and_(
                    Charger.station_id == station_db_id,
                    Connector.status == ConnectorStatusEnum.AVAILABLE,
                    Connector.is_active == True
                )
            )
            .options(selectinload(Connector.charger))
        )
        return list(result.scalars().all())

    async def get_connector_utilization(self, charger_db_id: int) -> dict:
        """Obtenir le taux d'utilisation des connecteurs d'un chargeur"""
        from app.database.models import Connector, ConnectorStatusEnum

        result = await self.db.execute(
            select(
                func.count(Connector.id).label('total'),
                func.sum(
                    case((Connector.status == ConnectorStatusEnum.OCCUPIED, 1), else_=0)
                ).label('occupied'),
                func.sum(
                    case((Connector.status == ConnectorStatusEnum.AVAILABLE, 1), else_=0)
                ).label('available')
            )
            .where(Connector.charger_id == charger_db_id)
        )
        stats = result.one()

        total = stats.total or 0
        occupied = stats.occupied or 0
        available = stats.available or 0

        return {
            'total_connectors': total,
            'occupied': occupied,
            'available': available,
            'utilization_rate': (occupied / total * 100) if total > 0 else 0
        }


class ChargerRepository:
    """Repository pour les chargeurs"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, station_db_id: int, charger_id: str,
                     max_power: float, num_connectors: int,
                     manufacturer: str = None, model: str = None,
                     serial_number: str = None) -> Charger:
        """Créer un nouveau chargeur"""
        charger = Charger(
            station_id=station_db_id,
            charger_id=charger_id,
            max_power=max_power,
            num_connectors=num_connectors,
            manufacturer=manufacturer,
            model=model,
            serial_number=serial_number
        )
        self.db.add(charger)
        await self.db.commit()
        await self.db.refresh(charger)
        return charger

    async def get_by_charger_id(self, station_db_id: int,
                                charger_id: str) -> Optional[Charger]:
        """Récupérer un chargeur par son ID avec ses connecteurs"""
        result = await self.db.execute(
            select(Charger)
            .where(
                and_(
                    Charger.station_id == station_db_id,
                    Charger.charger_id == charger_id
                )
            )
            .options(selectinload(Charger.connectors))
        )
        return result.scalar_one_or_none()

    async def get_with_connectors(self, charger_db_id: int) -> Optional[Charger]:
        """Récupérer un chargeur avec tous ses connecteurs"""
        result = await self.db.execute(
            select(Charger)
            .where(Charger.id == charger_db_id)
            .options(selectinload(Charger.connectors))
        )
        return result.scalar_one_or_none()

    async def get_all_by_station(self, station_db_id: int) -> List[Charger]:
        """Récupérer tous les chargeurs d'une station avec leurs connecteurs"""
        result = await self.db.execute(
            select(Charger)
            .where(Charger.station_id == station_db_id)
            .options(selectinload(Charger.connectors))
            .order_by(Charger.charger_id)
        )
        return list(result.scalars().all())
