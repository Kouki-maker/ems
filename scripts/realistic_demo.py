#!/usr/bin/env python3
"""
Démo réaliste du flow complet
"""

import subprocess
import time
import requests
import sys

API_URL = "http://localhost:8000"


def start_charger(charger_id: str):
    """Démarrer un simulateur de chargeur"""
    proc = subprocess.Popen([
        "python", "simulators/charger_realistic.py",
        "--station-id", "ELECTRA_PARIS_15",
        "--charger-id", charger_id,
        "--api-url", API_URL
    ])
    print(f"✓ Charger {charger_id} started (PID: {proc.pid})")
    return proc


def create_session(charger_id: str, connector_id: int, vehicle_max_power: float):
    """Créer une session via l'API"""
    response = requests.post(
        f"{API_URL}/sessions/",
        json={
            "chargerId": charger_id,
            "connectorId": connector_id,
            "vehicleMaxPower": vehicle_max_power
        }
    )

    if response.status_code == 200:
        data = response.json()
        print(f"✓ Session created: {data['sessionId']}")
        print(f"  Allocated: {data['allocatedPower']}kW")
        return data['sessionId']
    else:
        print(f"✗ Error: {response.status_code}")
        return None


def show_status():
    """Afficher le statut"""
    response = requests.get(f"{API_URL}/station/status")
    if response.status_code == 200:
        data = response.json()
        print(f"\n{'=' * 70}")
        print(f"Active Sessions: {data['activeSessions']}")
        print(f"Total Consumed: {data['totalConsumed']:.1f}kW")

        for s in data.get('sessions', []):
            print(
                f"  {s['sessionId']}: {s['consumedPower']:.1f}kW / {s['totalEnergy']:.2f}kWh / SOC:{s['vehicleSoc']:.1f}%")


def main():
    print("=" * 70)
    print("REALISTIC DEMO - Complete Flow")
    print("=" * 70)

    # 1. Démarrer les chargeurs (ils attendent des commandes)
    print("\n1. Starting chargers...")
    charger1 = start_charger("CP001")
    charger2 = start_charger("CP002")
    time.sleep(5)

    # 2. Créer des sessions via l'API (l'API commande les chargeurs)
    print("\n2. Creating sessions via API...")
    session1 = create_session("CP001", 1, 150.0)
    time.sleep(2)
    session2 = create_session("CP002", 1, 100.0)
    time.sleep(5)

    # 3. Observer la charge (les chargeurs envoient des updates à l'API)
    print("\n3. Monitoring charging...")
    for i in range(20):
        show_status()
        time.sleep(3)

    # 4. Nettoyer
    print("\n4. Cleaning up...")
    charger1.terminate()
    charger2.terminate()

    print("\n✓ Demo completed!")


if __name__ == "__main__":
    main()
