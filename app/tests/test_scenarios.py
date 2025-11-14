import pytest
import json
from pathlib import Path
from app.models.station import StationConfig
from app.services.session_service import SessionService
import time


def load_scenario(scenario_file: str):
    """Charger un fichier de scénario"""
    path = Path("scenarios") / scenario_file
    with open(path, 'r') as f:
        return json.load(f)


def test_scenario_1_static_load():
    """
    Scenario 1: Static Load Management on a single charger
    2 vehicles on same charger, 150kW each → each gets 100kW
    """
    scenario = load_scenario("scenario_1_static.json")

    # Créer le service avec la config du scénario
    config = StationConfig(**scenario['stationConfig'])
    service = SessionService(config)

    # Démarrer les 2 sessions
    session1_allocated = service.create_session(
        session_id="S1",
        charger_id="CP001",
        connector_id=1,
        vehicle_max_power=150
    )

    session2_allocated = service.create_session(
        session_id="S2",
        charger_id="CP001",
        connector_id=2,
        vehicle_max_power=150
    )

    # Vérifications
    print(f"\n=== Scenario 1 Results ===")
    print(f"Session 1 allocated: {session1_allocated}kW")
    print(f"Session 2 allocated: {session2_allocated}kW")

    # Chaque session devrait recevoir ~100kW (200kW / 2)
    assert abs(session1_allocated - 100) < 1, f"Expected ~100kW, got {session1_allocated}kW"
    assert abs(session2_allocated - 100) < 1, f"Expected ~100kW, got {session2_allocated}kW"

    # Vérifier la conformité grid
    status = service.get_station_status()
    assert status['totalAllocated'] <= config.gridCapacity, "Grid capacity exceeded!"

    print(f"✓ Total allocated: {status['totalAllocated']}kW (grid: {config.gridCapacity}kW)")
    print("✓ Scenario 1 PASSED")


def test_scenario_2_dynamic_reallocation():
    """
    Scenario 2: Dynamic Power Re-allocation
    Test power reallocation as vehicles arrive and leave
    """
    scenario = load_scenario("scenario_2_dynamic.json")

    config = StationConfig(**scenario['stationConfig'])
    service = SessionService(config)

    print(f"\n=== Scenario 2: Dynamic Re-allocation ===")

    # T0: 2 vehicles start charging
    s1_power = service.create_session("S1", "CP001", 1, 150)
    s2_power = service.create_session("S2", "CP001", 2, 150)

    status = service.get_station_status()
    print(f"\nT0: 2 vehicles")
    print(f"  S1: {s1_power}kW, S2: {s2_power}kW")
    print(f"  Total: {status['totalAllocated']}kW")

    # Chaque véhicule devrait recevoir ~150kW (pas de limitation)
    assert s1_power >= 145, f"Expected ~150kW, got {s1_power}kW"
    assert s2_power >= 145, f"Expected ~150kW, got {s2_power}kW"

    # T1: 3rd vehicle arrives
    s3_power = service.create_session("S3", "CP002", 1, 150)

    status = service.get_station_status()
    print(f"\nT1: 3rd vehicle arrives")
    print(f"  Total allocated: {status['totalAllocated']}kW")
    print(f"  Active sessions: {status['activeSessions']}")

    # T2: 4th vehicle arrives - grid becomes constrained
    s4_power = service.create_session("S4", "CP002", 2, 150)

    status = service.get_station_status()
    allocations = service.load_manager.get_current_allocations()

    print(f"\nT2: 4th vehicle arrives (GRID CONSTRAINED)")
    print(f"  Total allocated: {status['totalAllocated']}kW")
    print(f"  Grid capacity: {config.gridCapacity}kW")
    print(f"  Allocations:")
    for alloc in allocations:
        print(f"    {alloc.sessionId}: {alloc.allocatedPower}kW")

    # Vérifier que la grid n'est pas dépassée
    assert status['totalAllocated'] <= config.gridCapacity + 1, "Grid capacity exceeded!"

    # Chaque véhicule devrait recevoir ~99kW ((400-3)/4)
    avg_power = status['totalAllocated'] / 4
    assert 95 <= avg_power <= 105, f"Expected ~99kW per vehicle, got {avg_power}kW"

    # T3: 1st vehicle finishes
    service.stop_session("S1", consumed_energy=12.5)

    status = service.get_station_status()
    allocations = service.load_manager.get_current_allocations()

    print(f"\nT3: 1st vehicle left (POWER REALLOCATION)")
    print(f"  Active sessions: {status['activeSessions']}")
    print(f"  Total allocated: {status['totalAllocated']}kW")
    print(f"  New allocations:")
    for alloc in allocations:
        print(f"    {alloc.sessionId}: {alloc.allocatedPower}kW")

    # Vérifier que les sessions restantes ont reçu plus de puissance
    assert status['activeSessions'] == 3
    avg_power_after = status['totalAllocated'] / 3
    assert avg_power_after > avg_power, "Power should increase after vehicle leaves"

    print(f"  Average power increased from {avg_power:.1f}kW to {avg_power_after:.1f}kW")
    print("✓ Scenario 2 PASSED")


def test_scenario_3_bess_boost():
    """
    Scenario 3: Battery Boost Integration
    Test BESS providing boost power when grid is constrained
    """
    scenario = load_scenario("scenario_3_bess.json")

    config = StationConfig(**scenario['stationConfig'])
    service = SessionService(config)

    print(f"\n=== Scenario 3: BESS Boost ===")
    print(f"Grid capacity: {config.gridCapacity}kW")
    print(f"BESS capacity: {config.battery.initialCapacity}kWh")
    print(f"BESS power: {config.battery.power}kW")

    # T0: 2 vehicles start
    s1_power = service.create_session("S1", "CP001", 1, 150)
    s2_power = service.create_session("S2", "CP001", 2, 150)

    status = service.get_station_status()
    print(f"\nT0: 2 vehicles")
    print(f"  Total allocated: {status['totalAllocated']}kW")
    print(f"  BESS SOC: {status['bessSOC']:.1f}%")
    print(f"  BESS Power: {status['bessPower']}kW")

    # T1: 3rd vehicle
    s3_power = service.create_session("S3", "CP002", 1, 150)

    # T2: 4th vehicle - demand exceeds grid, BESS should boost
    s4_power = service.create_session("S4", "CP002", 2, 150)

    # Simuler quelques updates pour activer le BESS
    for i in range(5):
        service.update_power("S1", 150, 150)
        service.update_power("S2", 150, 150)
        service.update_power("S3", 150, 150)
        service.update_power("S4", 150, 150)

    status = service.get_station_status()
    allocations = service.load_manager.get_current_allocations()

    print(f"\nT2: 4 vehicles (BESS BOOST ACTIVATED)")
    print(f"  Grid capacity: {config.gridCapacity}kW")
    print(f"  Total demand: 600kW (4 × 150kW)")
    print(f"  Total allocated: {status['totalAllocated']}kW")
    print(f"  Grid power: {status['gridPower']:.1f}kW")
    print(f"  BESS power: {status['bessPower']:.1f}kW (discharge)")
    print(f"  BESS SOC: {status['bessSOC']:.1f}%")
    print(f"  Allocations:")
    for alloc in allocations:
        print(f"    {alloc.sessionId}: {alloc.allocatedPower}kW")

    # Vérifications
    assert status['bessPower'] > 0, "BESS should be discharging (boost mode)"
    assert status['totalAllocated'] > config.gridCapacity, "Total power should exceed grid with BESS"

    # Chaque véhicule devrait recevoir plus de 130kW grâce au boost
    avg_power = status['totalAllocated'] / 4
    assert avg_power > 130, f"With BESS boost, expected >130kW per vehicle, got {avg_power}kW"

    # T3: 1 vehicle leaves
    service.stop_session("S1", consumed_energy=25)

    # Simuler quelques updates
    for i in range(5):
        service.update_power("S2", 120, 150)
        service.update_power("S3", 120, 150)
        service.update_power("S4", 120, 150)

    status = service.get_station_status()

    print(f"\nT3: 1st vehicle left")
    print(f"  Active sessions: {status['activeSessions']}")
    print(f"  Total allocated: {status['totalAllocated']}kW")
    print(f"  BESS power: {status['bessPower']:.1f}kW")
    print(f"  BESS SOC: {status['bessSOC']:.1f}%")

    # Avec 3 véhicules, le grid devrait suffire, BESS peut charger
    if status['bessPower'] < 0:
        print(f"  BESS is now CHARGING (spare grid power available)")

    print("✓ Scenario 3 PASSED")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
