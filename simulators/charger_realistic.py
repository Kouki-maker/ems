#!/usr/bin/env python3
"""
Simulateur de chargeur réaliste avec communication bidirectionnelle
"""

import paho.mqtt.client as mqtt
import json
import time
import random
import argparse
from datetime import datetime
from typing import Optional
import logging
import requests

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class RealisticChargerSimulator:
    """
    Simulateur de chargeur réaliste
    - Reçoit les commandes de démarrage de session via MQTT
    - Envoie les updates de puissance à l'API REST
    - Arrête automatiquement quand la batterie est pleine
    """

    def __init__(self, station_id: str, charger_id: str, num_connectors: int = 2,
                 mqtt_broker: str = "localhost", mqtt_port: int = 1883,
                 api_url: str = "http://localhost:8000"):
        self.station_id = station_id
        self.charger_id = charger_id
        self.num_connectors = num_connectors
        self.mqtt_broker = mqtt_broker
        self.mqtt_port = mqtt_port
        self.api_url = api_url

        # État des connecteurs
        self.connectors = {}
        for i in range(1, num_connectors + 1):
            self.connectors[i] = {
                "status": "available",
                "session_id": None,
                "power_limit": 0.0,
                "vehicle_max_power": 0.0,
                "current_power": 0.0,
                "voltage": 400.0,
                "current": 0.0,
                "energy_delivered": 0.0,
                "vehicle_soc": 0.0,
                "start_time": None
            }

        # Client MQTT
        self.client = mqtt.Client(client_id=f"charger_{charger_id}")
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self.client.on_subscribe = self._on_subscribe
        self.connected = False
        self.running = True

    def connect(self):
        """Connexion au broker MQTT"""
        try:
            logger.info(f"Attempting connection to {self.mqtt_broker}:{self.mqtt_port}")
            self.client.connect(self.mqtt_broker, self.mqtt_port, 60)
            self.client.loop_start()
            logger.info("loop_start() called")
            time.sleep(5)  # Augmenter à 5 secondes
            logger.info(f"Connection status: self.connected={self.connected}")
            logger.info(f"MQTT Broker: {self.mqtt_broker}:{self.mqtt_port}")
            logger.info(f"Station ID: {self.station_id}")
        except Exception as e:
            logger.error(f"Failed to connect: {e}", exc_info=True)
            raise

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            self.connected = True
            logger.info(f"✓ Charger {self.charger_id} connected to MQTT broker")

            # Topic d'abonnement
            start_topic = f"electra/{self.station_id}/charger/{self.charger_id}/session/start_command"
            self.client.subscribe(start_topic, qos=1)
            logger.info(f"  Subscribed to: {start_topic}")

    def _on_subscribe(self, client, userdata, mid, granted_qos):
        logger.info(f"✓ Subscription confirmed! mid={mid}, qos={granted_qos}")

    def _on_message(self, client, userdata, msg):
        """Callback pour les messages reçus"""
        logger.info(f"!!! _on_message CALLED !!! Topic: {msg.topic}")
        logger.info(f"!!! MESSAGE RECEIVED !!! Topic: {msg.topic}, Payload: {msg.payload.decode()}")

        try:
            payload = json.loads(msg.payload.decode())
            topic = msg.topic

            logger.info(f"Parsed payload: {payload}")
            logger.info(f"Checking topic: {topic}")

            if "/session/start_command" in topic:
                logger.info("Calling _handle_start_command")
                self._handle_start_command(payload)
            elif "/power_limit" in topic:
                parts = topic.split("/")
                connector_id = int(parts[-2])
                self._handle_power_limit(connector_id, payload)
            else:
                logger.warning(f"Unhandled topic: {topic}")

        except Exception as e:
            logger.error(f"Error handling message: {e}", exc_info=True)

    def _handle_start_command(self, payload: dict):
        """
        Gérer une commande de démarrage de session depuis l'EMS
        """
        logger.info(f"_handle_start_command called with payload: {payload}")

        session_id = payload.get("session_id")
        connector_id = payload.get("connector_id")
        vehicle_max_power = payload.get("vehicle_max_power")

        logger.info(f"Extracted: session={session_id}, connector={connector_id}, power={vehicle_max_power}")

        if connector_id not in self.connectors:
            logger.error(f"Invalid connector: {connector_id}")
            return

        logger.info(f"Connector {connector_id} found, starting session...")

        connector = self.connectors[connector_id]

        if connector["status"] != "available":
            logger.error(f"Connector {connector_id} not available")
            return

        # Démarrer la session
        connector["status"] = "charging"
        connector["session_id"] = session_id
        connector["vehicle_max_power"] = vehicle_max_power
        connector["power_limit"] = vehicle_max_power
        connector["current_power"] = 0.0
        connector["energy_delivered"] = 0.0
        connector["vehicle_soc"] = random.uniform(10, 40)
        connector["start_time"] = time.time()

        logger.info(f"✓ Session {session_id} started on connector {connector_id}")
        logger.info(f"  Vehicle max: {vehicle_max_power}kW, Initial SOC: {connector['vehicle_soc']:.1f}%")

    def _handle_power_limit(self, connector_id: int, payload: dict):
        """Gérer une limite de puissance depuis l'EMS"""
        power_limit = payload.get("power_limit", 0)

        if connector_id in self.connectors:
            old_limit = self.connectors[connector_id]["power_limit"]
            self.connectors[connector_id]["power_limit"] = power_limit

            if abs(old_limit - power_limit) > 0.5:
                logger.info(f"Connector {connector_id}: Power limit {old_limit:.1f}kW → {power_limit:.1f}kW")

    def update_and_send_telemetry(self):
        """
        Mettre à jour l'état et envoyer la télémétrie à l'API
        """
        logger.info(
            f"update_and_send_telemetry called, connectors charging: {sum(1 for c in self.connectors.values() if c['status'] == 'charging')}")

        for connector_id, connector in self.connectors.items():
            if connector["status"] == "charging":
                session_id = connector["session_id"]

                # Calculer la puissance
                power_limit = connector["power_limit"]
                vehicle_max = connector["vehicle_max_power"]
                soc = connector["vehicle_soc"]

                # Courbe de charge réaliste
                if soc < 20:
                    power_factor = 0.95
                elif soc < 80:
                    power_factor = 1.0
                else:
                    power_factor = max(0.2, 1.0 - (soc - 80) / 20 * 0.8)

                target_power = min(power_limit, vehicle_max) * power_factor
                connector["current_power"] = target_power * random.uniform(0.95, 1.0)

                # Calculer le courant
                connector["current"] = (connector["current_power"] * 1000) / connector["voltage"]

                # Mettre à jour l'énergie (1 seconde)
                energy_increment = connector["current_power"] / 3600
                connector["energy_delivered"] += energy_increment

                # Mettre à jour le SOC (1kWh = 1.5% pour batterie 65kWh)
                soc_increment = energy_increment * 1.5
                connector["vehicle_soc"] = min(100, connector["vehicle_soc"] + soc_increment)

                # Envoyer à l'API REST
                try:
                    response = requests.post(
                        f"{self.api_url}/sessions/{session_id}/power-update",
                        json={
                            "consumedPower": connector["current_power"],
                            "vehicleMaxPower": connector["vehicle_max_power"]
                        },
                        timeout=2
                    )

                    if response.status_code == 200:
                        data = response.json()
                        new_limit = data.get("newAllocatedPower")
                        if new_limit and abs(connector["power_limit"] - new_limit) > 0.5:
                            connector["power_limit"] = new_limit
                            logger.debug(f"Power limit updated from API: {new_limit:.1f}kW")

                except requests.exceptions.RequestException as e:
                    logger.error(f"API error: {e}")

                # Arrêter si plein
                if connector["vehicle_soc"] >= 99.5:
                    logger.info(f"Vehicle on connector {connector_id} fully charged, stopping...")
                    self._stop_session(connector_id)

    def _stop_session(self, connector_id: int):
        """Arrêter une session"""
        connector = self.connectors[connector_id]

        if connector["status"] != "charging":
            return

        session_id = connector["session_id"]
        total_energy = connector["energy_delivered"]

        # Appeler l'API REST pour arrêter
        try:
            response = requests.post(
                f"{self.api_url}/sessions/{session_id}/stop",
                json={"consumedEnergy": total_energy},
                timeout=2
            )

            if response.status_code == 200:
                logger.info(f"✓ Session {session_id} stopped")
                logger.info(f"  Duration: {int(time.time() - connector['start_time'])}s")
                logger.info(f"  Energy: {total_energy:.2f}kWh")
                logger.info(f"  Final SOC: {connector['vehicle_soc']:.1f}%")
            else:
                logger.error(f"API error stopping session: {response.status_code}")

        except requests.exceptions.RequestException as e:
            logger.error(f"API error: {e}")

        # Réinitialiser le connecteur
        connector["status"] = "available"
        connector["session_id"] = None
        connector["current_power"] = 0.0
        connector["power_limit"] = 0.0
        connector["energy_delivered"] = 0.0

    def run(self):
        """Boucle principale"""
        logger.info(f"\n{'=' * 60}")
        logger.info(f"Charger {self.charger_id} - Running in realistic mode")
        logger.info(f"Waiting for session start commands from EMS...")
        logger.info(f"{'=' * 60}\n")

        try:
            while self.running:
                self.update_and_send_telemetry()
                time.sleep(2)
        except KeyboardInterrupt:
            logger.info("\nStopping...")
        finally:
            self.disconnect()

    def disconnect(self):
        """Déconnexion"""
        self.running = False
        self.client.loop_stop()
        self.client.disconnect()
        logger.info(f"Charger {self.charger_id} disconnected")


def main():
    parser = argparse.ArgumentParser(description="Realistic Charger Simulator")
    parser.add_argument("--station-id", default="ELECTRA_PARIS_15", help="Station ID")
    parser.add_argument("--charger-id", default="CP001", help="Charger ID")
    parser.add_argument("--connectors", type=int, default=2, help="Number of connectors")
    parser.add_argument("--mqtt-broker", default="localhost", help="MQTT broker host")
    parser.add_argument("--mqtt-port", type=int, default=1883, help="MQTT broker port")
    parser.add_argument("--api-url", default="http://localhost:8000", help="API URL")

    args = parser.parse_args()

    simulator = RealisticChargerSimulator(
        station_id=args.station_id,
        charger_id=args.charger_id,
        num_connectors=args.connectors,
        mqtt_broker=args.mqtt_broker,
        mqtt_port=args.mqtt_port,
        api_url=args.api_url
    )

    simulator.connect()
    simulator.run()


if __name__ == "__main__":
    main()