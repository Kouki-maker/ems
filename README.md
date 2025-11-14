# Electra EMS - Energy Management System

Energy Management System for fast-charging stations.

## 📋 Requirements

- Docker & Docker Compose

## 🚀 Quick Start

### Docker
```bash
# Clone repository
git clone https://github.com/Kouki-maker/ems
cd ems
````

```bash
# Build containers
make docker-dev

# The API is available in http://localhost:8000
# Documentation: http://localhost:8000/docs
```

## Realistic Demo
```bash
# Realistic demonstration
python simulators/charger_realistic.py
```


## 📊 Simulation de Scénarios
```bash
# Simulate charger communication with MQTT
python simulators/charger_simulator.py
```
```bash
# Simulate bess communication with MQTT
python simulators/bess_simulator.py
```
## ❓You can have more commands by running 
```bash
# Help
make help
```
