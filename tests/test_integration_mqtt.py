import pytest
import asyncio
import json
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from app.database.connection import AsyncSessionLocal
from app.database.repositories import SessionRepository, PowerMetricRepository
from app.services.mqtt_service import initialize_mqtt_service, get_mqtt_service
from app.services.session_service_mqtt import SessionServiceMQTT
from app.models.station import StationConfig
import paho.mqtt.client as mqtt

STATION_ID = "ELECTRA_PARIS_15"
MQTT_BROKER = "localhost"
MQTT_PORT = 1883


@pytest.fixture
async def db_session():
    """Fixture pour la session DB"""
    async with AsyncSessionLocal() as session:
        yield session


@pytest.fixture
def station_config():
    """Configuration de test"""
    return StationConfig(
        stationId=STATION_ID,
        gridCapacity=400.0,
        staticLoad=3.0,
        chargers=[
            {
                "id": "CP001",
                "maxPower": 200.0,
                "connectors": [
                    {"connector_id": 1, "connector_type": "CCS2", "max_power": 150.0},
                    {"connector_id": 2, "connector_type": "CCS2", "max_power": 150.0}
                ]
            }
        ],
        battery={"initialCapacity": 200.0, "power": 100.0}
    )


class MQTTTestClient:
    """Client MQTT de test"""

    def __init__(self, station_id: str):
        self.station_id = station_id
        self.client = mqtt.Client(client_id=f"test_{int(datetime.now().timestamp())}")
        self.client.connect(MQTT_BROKER, MQTT_PORT, 60)
        self.client.loop_start()

    def publish_session_start(self, charger_id: str, connector_id: int,
                              session_id: str, vehicle_max_power: float):
        """Publier un démarrage de session"""
        topic = f"electra/{self.station_id}/charger/{charger_id}/session/start"
        message = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "charger_id": charger_id,
            "connector_id": connector_id,
            "session_id": session_id,
            "vehicle_max_power": vehicle_max_power,
            "user_id": "test_user"
        }
        self.client.publish(topic, json.dumps(message), qos=1)

    def publish_session_update(self, charger_id: str, connector_id: int,
                               session_id: str, consumed_power: float,
                               vehicle_max_power: float, energy_delivered: float,
                               vehicle_soc: float):
        """Publier une mise à jour de session"""
        topic = f"electra/{self.station_id}/charger/{charger_id}/session/update"
        message = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "charger_id": charger_id,
            "connector_id": connector_id,
            "session_id": session_id,
            "consumed_power": consumed_power,
            "vehicle_max_power": vehicle_max_power,
            "vehicle_soc": vehicle_soc,
            "energy_delivered": energy_delivered
        }
        self.client.publish(topic, json.dumps(message), qos=1)

    def publish_telemetry(self, charger_id: str, connector_id: int,
                          session_id: str, power: float, vehicle_soc: float):
        """Publier la télémétrie"""
        topic = f"electra/{self.station_id}/charger/{charger_id}/telemetry"
        message = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "charger_id": charger_id,
            "connector_id": connector_id,
            "voltage": 400.0,
            "current": power * 1000 / 400,
            "power": power * 1000,  # Watts
            "session_id": session_id,
            "vehicle_soc": vehicle_soc,
            "status": "charging",
            "temperature": 30.0
        }
        self.client.publish(topic, json.dumps(message), qos=1)

    def publish_session_stop(self, charger_id: str, connector_id: int,
                             session_id: str, total_energy: float):
        """Publier un arrêt de session"""
        topic = f"electra/{self.station_id}/charger/{charger_id}/session/stop"
        message = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "charger_id": charger_id,
            "connector_id": connector_id,
            "session_id": session_id,
            "total_energy": total_energy,
            "reason": "user_stop"
        }
        self.client.publish(topic, json.dumps(message), qos=1)

    def disconnect(self):
        """Déconnexion"""
        self.client.loop_stop()
        self.client.disconnect()


@pytest.mark.asyncio
async def test_complete_session_lifecycle(db_session: AsyncSession, station_config):
    """Test du cycle complet d'une session avec MQTT"""

    # Setup
    mqtt_client = MQTTTestClient(STATION_ID)
    session_repo = SessionRepository(db_session)

    session_id = f"test_session_{int(datetime.now().timestamp())}"
    charger_id = "CP001"
    connector_id = 1
    vehicle_max_power = 150.0

    try:
        # 1. Publier le démarrage de session
        print(f"\n1. Publishing session start: {session_id}")
        mqtt_client.publish_session_start(
            charger_id=charger_id,
            connector_id=connector_id,
            session_id=session_id,
            vehicle_max_power=vehicle_max_power
        )

        # Attendre que le message soit traité
        await asyncio.sleep(3)

        # Vérifier en DB
        db_session_obj = await session_repo.get_by_session_id(session_id)
        assert db_session_obj is not None, "Session not created in DB"
        assert db_session_obj.status.value == "active"
        print(f"   ✓ Session created in DB: {db_session_obj.session_id}")

        # 2. Simuler la charge avec télémétrie
        print(f"\n2. Simulating charging (30 seconds)")

        consumed_power = 0.0
        energy_delivered = 0.0
        vehicle_soc = 20.0

        for i in range(30):
            # Augmenter progressivement
            consumed_power = min(140.0, consumed_power + 5.0)
            energy_delivered += consumed_power / 3600  # kWh
            vehicle_soc += 0.5  # +0.5% par seconde

            # Publier télémétrie
            mqtt_client.publish_telemetry(
                charger_id=charger_id,
                connector_id=connector_id,
                session_id=session_id,
                power=consumed_power,
                vehicle_soc=vehicle_soc
            )

            # Publier session update
            mqtt_client.publish_session_update(
                charger_id=charger_id,
                connector_id=connector_id,
                session_id=session_id,
                consumed_power=consumed_power,
                vehicle_max_power=vehicle_max_power,
                energy_delivered=energy_delivered,
                vehicle_soc=vehicle_soc
            )

            if i % 10 == 0:
                print(f"   t={i}s: {consumed_power:.1f}kW, {energy_delivered:.3f}kWh, SOC={vehicle_soc:.1f}%")

            await asyncio.sleep(1)

        # Attendre traitement
        await asyncio.sleep(2)

        # 3. Vérifier les mises à jour en DB
        print(f"\n3. Verifying DB updates")
        await db_session.refresh(db_session_obj)

        assert db_session_obj.consumed_power > 0, "Consumed power not updated"
        assert db_session_obj.total_energy > 0, "Total energy not updated"
        assert db_session_obj.vehicle_soc > 20, "Vehicle SOC not updated"

        print(f"   ✓ Consumed Power: {db_session_obj.consumed_power:.1f}kW")
        print(f"   ✓ Total Energy: {db_session_obj.total_energy:.3f}kWh")
        print(f"   ✓ Vehicle SOC: {db_session_obj.vehicle_soc:.1f}%")

        # 4. Arrêter la session
        print(f"\n4. Stopping session")
        mqtt_client.publish_session_stop(
            charger_id=charger_id,
            connector_id=connector_id,
            session_id=session_id,
            total_energy=energy_delivered
        )

        await asyncio.sleep(2)

        # 5. Vérifier l'arrêt en DB
        await db_session.refresh(db_session_obj)
        assert db_session_obj.status.value == "completed", "Session not completed"
        assert db_session_obj.end_time is not None, "End time not set"

        print(f"   ✓ Session completed")
        print(f"   ✓ Final energy: {db_session_obj.total_energy:.3f}kWh")

        print(f"\n✓ Integration test passed!")

    finally:
        mqtt_client.disconnect()


@pytest.mark.asyncio
async def test_multiple_sessions_power_allocation(db_session: AsyncSession, station_config):
    """Test de l'allocation de puissance avec plusieurs sessions"""

    mqtt_client = MQTTTestClient(STATION_ID)
    session_repo = SessionRepository(db_session)

    session1_id = f"test_s1_{int(datetime.now().timestamp())}"
    session2_id = f"test_s2_{int(datetime.now().timestamp())}"

    try:
        # 1. Démarrer 2 sessions
        print(f"\n1. Starting 2 sessions")

        mqtt_client.publish_session_start("CP001", 1, session1_id, 150.0)
        await asyncio.sleep(2)

        mqtt_client.publish_session_start("CP001", 2, session2_id, 150.0)
        await asyncio.sleep(2)

        # Vérifier en DB
        s1 = await session_repo.get_by_session_id(session1_id)
        s2 = await session_repo.get_by_session_id(session2_id)

        assert s1 is not None, "Session 1 not created"
        assert s2 is not None, "Session 2 not created"

        print(f"   ✓ Session 1: {s1.allocated_power}kW allocated")
        print(f"   ✓ Session 2: {s2.allocated_power}kW allocated")

        # 2. Simuler consommation
        print(f"\n2. Simulating power consumption")

        for i in range(15):
            mqtt_client.publish_session_update(
                "CP001", 1, session1_id, 140.0, 150.0, i * 0.04, 30.0 + i
            )
            mqtt_client.publish_session_update(
                "CP001", 2, session2_id, 140.0, 150.0, i * 0.04, 25.0 + i
            )

            await asyncio.sleep(1)

        await asyncio.sleep(2)

        # 3. Vérifier les allocations
        await db_session.refresh(s1)
        await db_session.refresh(s2)

        assert s1.consumed_power == 140.0, "Session 1 power not updated"
        assert s2.consumed_power == 140.0, "Session 2 power not updated"

        total_allocated = s1.allocated_power + s2.allocated_power
        print(f"   ✓ Total allocated: {total_allocated:.1f}kW")
        assert total_allocated <= station_config.gridCapacity, "Over capacity!"

        # 4. Arrêter les sessions
        print(f"\n3. Stopping sessions")
        mqtt_client.publish_session_stop("CP001", 1, session1_id, 0.58)
        mqtt_client.publish_session_stop("CP001", 2, session2_id, 0.58)

        await asyncio.sleep(2)

        await db_session.refresh(s1)
        await db_session.refresh(s2)

        assert s1.status.value == "completed"
        assert s2.status.value == "completed"

        print(f"   ✓ Both sessions completed")
        print(f"\n✓ Integration test passed!")

    finally:
        mqtt_client.disconnect()


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
