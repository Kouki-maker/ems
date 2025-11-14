#!/usr/bin/env python3
"""
Script pour exécuter des scénarios de test avec MQTT
"""

import asyncio
import time
import subprocess
import signal
import sys
import argparse
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class ScenarioRunner:
    def __init__(self, station_id: str = "ELECTRA_PARIS_15",
                 mqtt_broker: str = "localhost", mqtt_port: int = 1883):
        self.station_id = station_id
        self.mqtt_broker = mqtt_broker
        self.mqtt_port = mqtt_port
        self.processes = []

    def start_charger(self, charger_id: str, duration: int = 300):
        """Démarrer un simulateur de chargeur"""
        cmd = [
            "python", "simulators/charger_simulator.py",
            "--station-id", self.station_id,
            "--charger-id", charger_id,
            "--broker", self.mqtt_broker,
            "--port", str(self.mqtt_port),
            "--mode", "auto",
            "--duration", str(duration)
        ]

        process = subprocess.Popen(cmd)
        self.processes.append(process)
        logger.info(f"Started charger simulator: {charger_id}")
        return process

    def start_bess(self, duration: int = 300, initial_soc: float = 100.0):
        """Démarrer un simulateur BESS"""
        cmd = [
            "python", "simulators/bess_simulator.py",
            "--station-id", self.station_id,
            "--broker", self.mqtt_broker,
            "--port", str(self.mqtt_port),
            "--mode", "auto",
            "--duration", str(duration),
            "--initial-soc", str(initial_soc)
        ]

        process = subprocess.Popen(cmd)
        self.processes.append(process)
        logger.info("Started BESS simulator")
        return process

    def stop_all(self):
        """Arrêter tous les processus"""
        logger.info("Stopping all simulators...")
        for process in self.processes:
            try:
                process.terminate()
                process.wait(timeout=5)
            except:
                process.kill()
        self.processes = []

    def run_scenario_1(self):
        """
        Scenario 1: Static Load Management
        2 véhicules sur le même chargeur
        """
        logger.info("=" * 60)
        logger.info("SCENARIO 1: Static Load Management")
        logger.info("=" * 60)

        # Démarrer un seul chargeur
        self.start_charger("CP001", duration=120)

        try:
            logger.info("Scenario running... (120 seconds)")
            time.sleep(120)
        except KeyboardInterrupt:
            logger.info("Scenario interrupted")
        finally:
            self.stop_all()

    def run_scenario_2(self):
        """
        Scenario 2: Dynamic Power Re-allocation
        Multiple chargeurs avec arrivées progressives
        """
        logger.info("=" * 60)
        logger.info("SCENARIO 2: Dynamic Power Re-allocation")
        logger.info("=" * 60)

        # Démarrer 2 chargeurs
        self.start_charger("CP001", duration=180)
        time.sleep(5)
        self.start_charger("CP002", duration=175)

        try:
            logger.info("Scenario running... (180 seconds)")
            time.sleep(180)
        except KeyboardInterrupt:
            logger.info("Scenario interrupted")
        finally:
            self.stop_all()

    def run_scenario_3(self):
        """
        Scenario 3: BESS Boost Integration
        Multiple chargeurs + BESS
        """
        logger.info("=" * 60)
        logger.info("SCENARIO 3: BESS Boost Integration")
        logger.info("=" * 60)

        # Démarrer BESS
        self.start_bess(duration=200, initial_soc=80.0)
        time.sleep(2)

        # Démarrer 2 chargeurs
        self.start_charger("CP001", duration=195)
        time.sleep(5)
        self.start_charger("CP002", duration=190)

        try:
            logger.info("Scenario running... (200 seconds)")
            time.sleep(200)
        except KeyboardInterrupt:
            logger.info("Scenario interrupted")
        finally:
            self.stop_all()


def main():
    parser = argparse.ArgumentParser(description="Run MQTT test scenarios")
    parser.add_argument("scenario", type=int, choices=[1, 2, 3],
                        help="Scenario number to run")
    parser.add_argument("--station-id", default="ELECTRA_PARIS_15",
                        help="Station ID")
    parser.add_argument("--broker", default="localhost",
                        help="MQTT broker host")
    parser.add_argument("--port", type=int, default=1883,
                        help="MQTT broker port")

    args = parser.parse_args()

    runner = ScenarioRunner(
        station_id=args.station_id,
        mqtt_broker=args.broker,
        mqtt_port=args.port
    )

    # Handler pour Ctrl+C
    def signal_handler(sig, frame):
        logger.info("\nReceived interrupt signal")
        runner.stop_all()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)

    # Exécuter le scénario
    if args.scenario == 1:
        runner.run_scenario_1()
    elif args.scenario == 2:
        runner.run_scenario_2()
    elif args.scenario == 3:
        runner.run_scenario_3()


if __name__ == "__main__":
    main()
