#!/usr/bin/env python3
"""
Simulateur de chargeur EV qui communique via MQTT
"""

import paho.mqtt.client as mqtt
import json
import time
import random
import argparse
from datetime import datetime
from typing import Optional
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class ChargerSimulator:
    """
    Simulateur de chargeur EV avec communication MQTT
    """

    def __init__(self, station_id: str, charger_id: str, num_connectors: int = 2,
                 broker_host: str = "localhost", broker_port: int = 1883):
        self.station_id = station_id
        self.charger_id = charger_id
        self.num_connectors = num_connectors
        self.broker_host = broker_host
        self.broker_port = broker_port

        # État des connecteurs
        self.connectors = {}
        for i in range(1, num_connectors + 1):
            self.connectors[i] = {
                "status": "available",
                "session_id": None,
                "power_limit": 0.0,  # kW
                "vehicle_max_power": 0.0,  # kW
                "current_power": 0.0,  # kW
                "voltage": 400.0,  # V
                "current": 0.0,  # A
                "energy_delivered": 0.0,  # kWh
                "vehicle_soc": 20.0  # %
            }

        # Client MQTT
        self.client = mqtt.Client(client_id=f"charger_{charger_id}")
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self.connected = False

    def connect(self):
        """Connexion au broker MQTT"""
        try:
            self.client.connect(self.broker_host, self.broker_port, 60)
            self.client.loop_start()
            logger.info(f"Charger {self.charger_id} connecting to MQTT broker...")
            time.sleep(2)  # Attendre la connexion
        except Exception as e:
            logger.error(f"Failed to connect: {e}")
            raise

    def _on_connect(self, client, userdata, flags, rc):
        """Callback de connexion"""
        if rc == 0:
            self.connected = True
            logger.info(f"✓ Charger {self.charger_id} connected to MQTT broker")

            # S'abonner aux commandes
            command_topic = f"electra/{self.station_id}/charger/{self.charger_id}/command"
            self.client.subscribe(command_topic, qos=1)
            logger.info(f"  Subscribed to: {command_topic}")

            # S'abonner aux limites de puissance pour chaque connecteur
            for connector_id in self.connectors.keys():
                power_limit_topic = f"electra/{self.station_id}/charger/{self.charger_id}/connector/{connector_id}/power_limit"
                self.client.subscribe(power_limit_topic, qos=1)
                logger.info(f"  Subscribed to: {power_limit_topic}")
        else:
            logger.error(f"Connection failed with code: {rc}")

    def _on_message(self, client, userdata, msg):
        """Callback pour les messages reçus"""
        try:
            payload = json.loads(msg.payload.decode())
            topic = msg.topic

            if "/power_limit" in topic:
                # Extraire le connector_id du topic
                parts = topic.split("/")
                connector_id = int(parts[-2])
                self._handle_power_limit(connector_id, payload)
            elif "/command" in topic:
                self._handle_command(payload)

        except Exception as e:
            logger.error(f"Error handling message: {e}")

    def _handle_power_limit(self, connector_id: int, payload: dict):
        """Gérer une commande de limite de puissance"""
        power_limit = payload.get("power_limit", 0)

        if connector_id in self.connectors:
            old_limit = self.connectors[connector_id]["power_limit"]
            self.connectors[connector_id]["power_limit"] = power_limit

            logger.info(f"Connector {connector_id}: Power limit updated: {old_limit:.1f}kW -> {power_limit:.1f}kW")

            # Ajuster la puissance actuelle si nécessaire
            if self.connectors[connector_id]["current_power"] > power_limit:
                self.connectors[connector_id]["current_power"] = power_limit

    def _handle_command(self, payload: dict):
        """Gérer une commande générique"""
        command = payload.get("command")
        logger.info(f"Received command: {command}")

        # Implémenter les commandes si nécessaire
        if command == "reset":
            logger.info(f"Resetting charger {self.charger_id}")

    def start_session(self, connector_id: int, vehicle_max_power: float = 150.0,
                      user_id: str = "user_123"):
        """
        Démarrer une session de charge sur un connecteur
        """
        if connector_id not in self.connectors:
            logger.error(f"Connector {connector_id} does not exist")
            return None

        connector = self.connectors[connector_id]

        if connector["status"] != "available":
            logger.error(f"Connector {connector_id} is not available")
            return None

        # Générer un ID de session
        session_id = f"session_{self.charger_id}_{connector_id}_{int(time.time())}"

        # Mettre à jour l'état du connecteur
        connector["status"] = "charging"
        connector["session_id"] = session_id
        connector["vehicle_max_power"] = vehicle_max_power
        connector["power_limit"] = vehicle_max_power  # Initialement
        connector["current_power"] = 0.0
        connector["energy_delivered"] = 0.0
        connector["vehicle_soc"] = random.uniform(10, 40)  # SOC initial aléatoire

        # Publier le message de démarrage de session
        topic = f"electra/{self.station_id}/charger/{self.charger_id}/session/start"
        message = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "charger_id": self.charger_id,
            "connector_id": connector_id,
            "session_id": session_id,
            "vehicle_max_power": vehicle_max_power,
            "user_id": user_id
        }

        self.client.publish(topic, json.dumps(message), qos=1)
        logger.info(f"✓ Session started on connector {connector_id}: {session_id}")
        logger.info(f"  Vehicle max power: {vehicle_max_power}kW")
        logger.info(f"  Initial SOC: {connector['vehicle_soc']:.1f}%")

        return session_id

    def stop_session(self, connector_id: int):
        """
        Arrêter une session de charge
        """
        if connector_id not in self.connectors:
            return

        connector = self.connectors[connector_id]

        if connector["status"] != "charging":
            logger.warning(f"No active session on connector {connector_id}")
            return

        session_id = connector["session_id"]
        total_energy = connector["energy_delivered"]

        # Publier le message d'arrêt
        topic = f"electra/{self.station_id}/charger/{self.charger_id}/session/stop"
        message = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "charger_id": self.charger_id,
            "connector_id": connector_id,
            "session_id": session_id,
            "total_energy": total_energy,
            "reason": "user_stop"
        }

        self.client.publish(topic, json.dumps(message), qos=1)
        logger.info(f"✓ Session stopped on connector {connector_id}: {session_id}")
        logger.info(f"  Total energy delivered: {total_energy:.2f}kWh")
        logger.info(f"  Final SOC: {connector['vehicle_soc']:.1f}%")

        # Réinitialiser l'état du connecteur
        connector["status"] = "available"
        connector["session_id"] = None
        connector["current_power"] = 0.0
        connector["power_limit"] = 0.0

    def publish_telemetry(self):
        """
        Publier la télémétrie de tous les connecteurs
        """
        for connector_id, connector in self.connectors.items():
            if connector["status"] == "charging":
                power_limit = connector["power_limit"]
                vehicle_max = connector["vehicle_max_power"]
                soc = connector["vehicle_soc"]

                if soc < 20:
                    power_factor = 0.95
                elif soc < 80:
                    power_factor = 1.0
                else:
                    # Réduction de puissance au-dessus de 80%
                    power_factor = max(0.2, 1.0 - (soc - 80) / 20 * 0.8)

                target_power = min(power_limit, vehicle_max) * power_factor
                connector["current_power"] = target_power * random.uniform(0.95, 1.0)

                # Calculer le courant
                connector["current"] = (connector["current_power"] * 1000) / connector["voltage"]

                # Mettre à jour l'énergie délivrée (en supposant 1 seconde entre chaque publication)
                energy_increment = connector["current_power"] / 3600  # kWh
                connector["energy_delivered"] += energy_increment

                # Mettre à jour le SOC (approximation: 1kWh = 1.5% pour une batterie de 65kWh)
                soc_increment = energy_increment * 1.5
                connector["vehicle_soc"] = min(100, connector["vehicle_soc"] + soc_increment)

                # Publier la télémétrie
                topic = f"electra/{self.station_id}/charger/{self.charger_id}/telemetry"
                message = {
                    "timestamp": datetime.utcnow().isoformat() + "Z",
                    "charger_id": self.charger_id,
                    "connector_id": connector_id,
                    "voltage": connector["voltage"],
                    "current": connector["current"],
                    "power": connector["current_power"] * 1000,  # W
                    "session_id": connector["session_id"],
                    "vehicle_soc": connector["vehicle_soc"],
                    "status": connector["status"],
                    "temperature": random.uniform(25, 45)
                }

                self.client.publish(topic, json.dumps(message), qos=1)

                # Publier la mise à jour de session avec TOUTES les données
                session_topic = f"electra/{self.station_id}/charger/{self.charger_id}/session/update"
                session_message = {
                    "timestamp": datetime.utcnow().isoformat() + "Z",
                    "charger_id": self.charger_id,
                    "connector_id": connector_id,
                    "session_id": connector["session_id"],
                    "consumed_power": connector["current_power"],  # kW
                    "vehicle_max_power": connector["vehicle_max_power"],  # kW
                    "vehicle_soc": connector["vehicle_soc"],  # %
                    "energy_delivered": connector["energy_delivered"]  # kWh - IMPORTANT!
                }

                self.client.publish(session_topic, json.dumps(session_message), qos=1)

                # Log pour debug
                if int(time.time()) % 5 == 0:  # Log toutes les 5 secondes
                    logger.debug(
                        f"Connector {connector_id}: "
                        f"Power={connector['current_power']:.1f}kW, "
                        f"Energy={connector['energy_delivered']:.2f}kWh, "
                        f"SOC={connector['vehicle_soc']:.1f}%"
                    )

                # Arrêter automatiquement si la batterie est pleine
                if connector["vehicle_soc"] >= 99.5:
                    logger.info(f"Vehicle on connector {connector_id} is fully charged")
                    self.stop_session(connector_id)

    def run_interactive(self):
        """Mode interactif"""
        logger.info(f"\n{'=' * 60}")
        logger.info(f"Charger {self.charger_id} - Interactive Mode")
        logger.info(f"{'=' * 60}\n")

        while True:
            print("\nCommands:")
            print("  1. Start session on connector")
            print("  2. Stop session on connector")
            print("  3. Show status")
            print("  4. Exit")

            choice = input("\nChoice: ").strip()

            if choice == "1":
                connector_id = int(input("Connector ID: "))
                vehicle_power = float(input("Vehicle max power (kW) [150]: ") or "150")
                self.start_session(connector_id, vehicle_power)

            elif choice == "2":
                connector_id = int(input("Connector ID: "))
                self.stop_session(connector_id)

            elif choice == "3":
                self._print_status()

            elif choice == "4":
                break

    def _print_status(self):
        """Afficher le statut actuel"""
        print(f"\n{'=' * 60}")
        print(f"Charger {self.charger_id} Status")
        print(f"{'=' * 60}")

        for connector_id, connector in self.connectors.items():
            print(f"\nConnector {connector_id}:")
            print(f"  Status: {connector['status']}")
            print(f"  Session ID: {connector['session_id']}")
            print(f"  Power Limit: {connector['power_limit']:.1f}kW")
            print(f"  Current Power: {connector['current_power']:.1f}kW")
            print(f"  Energy Delivered: {connector['energy_delivered']:.2f}kWh")
            print(f"  Vehicle SOC: {connector['vehicle_soc']:.1f}%")

    def run_simulation(self, duration: int = 300):
        """
        Exécuter une simulation automatique

        Args:
            duration: Durée de la simulation en secondes
        """
        logger.info(f"\n{'=' * 60}")
        logger.info(f"Starting automatic simulation for {duration} seconds")
        logger.info(f"{'=' * 60}\n")

        start_time = time.time()

        # Démarrer une session sur le premier connecteur
        self.start_session(1, vehicle_max_power=150.0)
        time.sleep(5)

        # Optionnellement démarrer une autre session
        if self.num_connectors > 1:
            self.start_session(2, vehicle_max_power=100.0)

        try:
            while time.time() - start_time < duration:
                # Publier la télémétrie
                self.publish_telemetry()

                # Afficher le statut périodiquement
                if int(time.time() - start_time) % 10 == 0:
                    self._print_status()

                time.sleep(1)  # Publier toutes les secondes

        except KeyboardInterrupt:
            logger.info("\nSimulation interrupted by user")

        finally:
            # Arrêter toutes les sessions
            for connector_id in self.connectors.keys():
                if self.connectors[connector_id]["status"] == "charging":
                    self.stop_session(connector_id)

            logger.info("\nSimulation completed")

    def disconnect(self):
        """Déconnexion du broker MQTT"""
        self.client.loop_stop()
        self.client.disconnect()
        logger.info(f"Charger {self.charger_id} disconnected")


def main():
    parser = argparse.ArgumentParser(description="Charger Simulator for Electra EMS")
    parser.add_argument("--station-id", default="ELECTRA_PARIS_15", help="Station ID")
    parser.add_argument("--charger-id", default="CP001", help="Charger ID")
    parser.add_argument("--connectors", type=int, default=2, help="Number of connectors")
    parser.add_argument("--broker", default="localhost", help="MQTT broker host")
    parser.add_argument("--port", type=int, default=1883, help="MQTT broker port")
    parser.add_argument("--mode", choices=["interactive", "auto"], default="interactive",
                        help="Simulation mode")
    parser.add_argument("--duration", type=int, default=300,
                        help="Duration of auto simulation in seconds")

    args = parser.parse_args()

    # Créer le simulateur
    simulator = ChargerSimulator(
        station_id=args.station_id,
        charger_id=args.charger_id,
        num_connectors=args.connectors,
        broker_host=args.broker,
        broker_port=args.port
    )

    # Connexion
    simulator.connect()

    try:
        if args.mode == "interactive":
            simulator.run_interactive()
        else:
            simulator.run_simulation(args.duration)
    finally:
        simulator.disconnect()


if __name__ == "__main__":
    main()
