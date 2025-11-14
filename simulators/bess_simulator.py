#!/usr/bin/env python3
"""
Simulateur de BESS (Battery Energy Storage System) qui communique via MQTT
"""

import paho.mqtt.client as mqtt
import json
import time
import random
import argparse
from datetime import datetime
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class BESSSimulator:
    """
    Simulateur de système de stockage par batterie
    """

    def __init__(self, station_id: str, capacity: float = 200.0,
                 max_power: float = 100.0, initial_soc: float = 100.0,
                 broker_host: str = "localhost", broker_port: int = 1883):
        self.station_id = station_id
        self.capacity = capacity  # kWh
        self.max_power = max_power  # kW
        self.min_soc = 10.0  # %
        self.max_soc = 100.0  # %

        # État actuel
        self.soc = initial_soc  # %
        self.voltage = 800.0  # V
        self.current = 0.0  # A
        self.power = 0.0  # kW (+ = discharge, - = charge)
        self.temperature = 25.0  # °C
        self.status = "idle"  # idle, charging, discharging, faulted

        # Commande reçue
        self.commanded_power = 0.0
        self.commanded_mode = "idle"

        # MQTT
        self.broker_host = broker_host
        self.broker_port = broker_port
        self.client = mqtt.Client(client_id=f"bess_{station_id}")
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self.connected = False

    def connect(self):
        """Connexion au broker MQTT"""
        try:
            self.client.connect(self.broker_host, self.broker_port, 60)
            self.client.loop_start()
            logger.info(f"BESS connecting to MQTT broker...")
            time.sleep(2)
        except Exception as e:
            logger.error(f"Failed to connect: {e}")
            raise

    def _on_connect(self, client, userdata, flags, rc):
        """Callback de connexion"""
        if rc == 0:
            self.connected = True
            logger.info(f"✓ BESS connected to MQTT broker")

            # S'abonner aux commandes
            command_topic = f"electra/{self.station_id}/bess/command"
            self.client.subscribe(command_topic, qos=1)
            logger.info(f"  Subscribed to: {command_topic}")
        else:
            logger.error(f"Connection failed with code: {rc}")

    def _on_message(self, client, userdata, msg):
        """Callback pour les messages reçus"""
        try:
            payload = json.loads(msg.payload.decode())
            self._handle_command(payload)
        except Exception as e:
            logger.error(f"Error handling message: {e}")

    def _handle_command(self, payload: dict):
        """Gérer une commande reçue"""
        command = payload.get("command", "idle")
        power = payload.get("power", 0.0)

        logger.info(f"Received command: {command} @ {power}kW")

        self.commanded_mode = command
        self.commanded_power = power

    def update_state(self, dt: float = 1.0):
        """
        Mettre à jour l'état de la batterie

        Args:
            dt: Intervalle de temps en secondes
        """
        # Déterminer la puissance réelle basée sur la commande
        if self.commanded_mode == "discharge":
            # Vérifier si on peut décharger
            if self.soc > self.min_soc:
                # Limiter par la puissance max et le SOC
                available_energy = ((self.soc - self.min_soc) / 100) * self.capacity
                max_discharge = min(self.max_power, available_energy * 3600 / dt)  # kW
                self.power = min(self.commanded_power, max_discharge)
                self.status = "discharging"
            else:
                self.power = 0.0
                self.status = "idle"
                logger.warning("Cannot discharge: SOC too low")

        elif self.commanded_mode == "charge":
            # Vérifier si on peut charger
            if self.soc < self.max_soc:
                # Limiter par la puissance max et le SOC
                available_capacity = ((self.max_soc - self.soc) / 100) * self.capacity
                max_charge = min(self.max_power, available_capacity * 3600 / dt)  # kW
                self.power = -min(self.commanded_power, max_charge)  # Négatif pour charge
                self.status = "charging"
            else:
                self.power = 0.0
                self.status = "idle"
                logger.warning("Cannot charge: SOC full")

        else:  # idle
            self.power = 0.0
            self.status = "idle"

        # Mettre à jour le SOC
        if self.power != 0:
            # Énergie transférée en kWh
            energy_kwh = (abs(self.power) * dt) / 3600

            # Changement de SOC
            soc_change = (energy_kwh / self.capacity) * 100

            if self.power > 0:  # Décharge
                self.soc = max(self.min_soc, self.soc - soc_change)
            else:  # Charge
                self.soc = min(self.max_soc, self.soc + soc_change)

        # Calculer le courant
        if self.power != 0:
            self.current = (abs(self.power) * 1000) / self.voltage
            if self.power < 0:  # Charge
                self.current = -self.current
        else:
            self.current = 0.0

        # Simuler la température (augmente avec la puissance)
        target_temp = 25 + abs(self.power) * 0.2
        self.temperature += (target_temp - self.temperature) * 0.1
        self.temperature = min(60, max(20, self.temperature))

    def publish_status(self):
        """Publier le statut de la batterie"""
        available_capacity = ((self.soc - self.min_soc) / 100) * self.capacity

        topic = f"electra/{self.station_id}/bess/status"
        message = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "soc": self.soc,
            "voltage": self.voltage,
            "current": self.current,
            "power": self.power,
            "temperature": self.temperature,
            "status": self.status,
            "available_capacity": available_capacity
        }

        self.client.publish(topic, json.dumps(message), qos=1)

        # Publier aussi la télémétrie détaillée
        telemetry_topic = f"electra/{self.station_id}/bess/telemetry"
        telemetry_message = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "soc": self.soc,
            "voltage": self.voltage,
            "current": self.current,
            "power": self.power,
            "temperature": self.temperature,
            "status": self.status,
            "capacity": self.capacity,
            "max_power": self.max_power,
            "min_soc": self.min_soc,
            "max_soc": self.max_soc
        }

        self.client.publish(telemetry_topic, json.dumps(telemetry_message), qos=1)

    def _print_status(self):
        """Afficher le statut"""
        print(f"\n{'=' * 60}")
        print(f"BESS Status - {self.station_id}")
        print(f"{'=' * 60}")
        print(f"SOC: {self.soc:.1f}%")
        print(f"Status: {self.status}")
        print(
            f"Power: {self.power:.1f}kW ({'discharge' if self.power > 0 else 'charge' if self.power < 0 else 'idle'})")
        print(f"Current: {self.current:.1f}A")
        print(f"Voltage: {self.voltage:.1f}V")
        print(f"Temperature: {self.temperature:.1f}°C")
        print(f"Available Energy: {((self.soc - self.min_soc) / 100) * self.capacity:.1f}kWh")
        print(f"{'=' * 60}")

    def run_simulation(self, duration: int = 300):
        """
        Exécuter une simulation automatique

        Args:
            duration: Durée en secondes
        """
        logger.info(f"\n{'=' * 60}")
        logger.info(f"Starting BESS simulation for {duration} seconds")
        logger.info(f"Initial SOC: {self.soc:.1f}%")
        logger.info(f"{'=' * 60}\n")

        start_time = time.time()
        last_print = start_time

        try:
            while time.time() - start_time < duration:
                # Mettre à jour l'état
                self.update_state(dt=1.0)

                # Publier le statut
                self.publish_status()

                # Afficher périodiquement
                if time.time() - last_print >= 10:
                    self._print_status()
                    last_print = time.time()

                time.sleep(1)

        except KeyboardInterrupt:
            logger.info("\nSimulation interrupted by user")

        finally:
            self._print_status()
            logger.info("\nSimulation completed")

    def run_interactive(self):
        """Mode interactif"""
        logger.info(f"\n{'=' * 60}")
        logger.info(f"BESS - Interactive Mode")
        logger.info(f"{'=' * 60}\n")

        while True:
            print("\nCommands:")
            print("  1. Set discharge power")
            print("  2. Set charge power")
            print("  3. Set idle")
            print("  4. Show status")
            print("  5. Exit")

            choice = input("\nChoice: ").strip()

            if choice == "1":
                power = float(input(f"Discharge power (0-{self.max_power}kW): "))
                self.commanded_mode = "discharge"
                self.commanded_power = min(power, self.max_power)

            elif choice == "2":
                power = float(input(f"Charge power (0-{self.max_power}kW): "))
                self.commanded_mode = "charge"
                self.commanded_power = min(power, self.max_power)

            elif choice == "3":
                self.commanded_mode = "idle"
                self.commanded_power = 0

            elif choice == "4":
                self._print_status()

            elif choice == "5":
                break

            # Mettre à jour et publier
            self.update_state()
            self.publish_status()

    def disconnect(self):
        """Déconnexion"""
        self.client.loop_stop()
        self.client.disconnect()
        logger.info("BESS disconnected")


def main():
    parser = argparse.ArgumentParser(description="BESS Simulator for Electra EMS")
    parser.add_argument("--station-id", default="ELECTRA_PARIS_15", help="Station ID")
    parser.add_argument("--capacity", type=float, default=200.0, help="Battery capacity in kWh")
    parser.add_argument("--max-power", type=float, default=100.0, help="Max power in kW")
    parser.add_argument("--initial-soc", type=float, default=100.0, help="Initial SOC in %")
    parser.add_argument("--broker", default="localhost", help="MQTT broker host")
    parser.add_argument("--port", type=int, default=1883, help="MQTT broker port")
    parser.add_argument("--mode", choices=["interactive", "auto"], default="interactive",
                        help="Simulation mode")
    parser.add_argument("--duration", type=int, default=300,
                        help="Duration of auto simulation in seconds")

    args = parser.parse_args()

    # Créer le simulateur
    simulator = BESSSimulator(
        station_id=args.station_id,
        capacity=args.capacity,
        max_power=args.max_power,
        initial_soc=args.initial_soc,
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
