#!/bin/bash

echo "=========================================="
echo "  Electra EMS - Running Test Scenarios"
echo "=========================================="
echo ""

# Couleurs pour l'output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Créer le dossier de résultats
mkdir -p test_results

echo -e "${BLUE}Running Scenario 1: Static Load Management${NC}"
echo "----------------------------------------"
python -m pytest app/tests/test_scenarios.py::test_scenario_1_static_load -v -s
SCENARIO1=$?

echo ""
echo -e "${BLUE}Running Scenario 2: Dynamic Power Re-allocation${NC}"
echo "----------------------------------------"
python -m pytest app/tests/test_scenarios.py::test_scenario_2_dynamic_reallocation -v -s
SCENARIO2=$?

echo ""
echo -e "${BLUE}Running Scenario 3: BESS Boost Integration${NC}"
echo "----------------------------------------"
python -m pytest app/tests/test_scenarios.py::test_scenario_3_bess_boost -v -s
SCENARIO3=$?

echo ""
echo "=========================================="
echo "  Test Results Summary"
echo "=========================================="

if [ $SCENARIO1 -eq 0 ]; then
    echo -e "${GREEN}✓ Scenario 1: PASSED${NC}"
else
    echo -e "${RED}✗ Scenario 1: FAILED${NC}"
fi

if [ $SCENARIO2 -eq 0 ]; then
    echo -e "${GREEN}✓ Scenario 2: PASSED${NC}"
else
    echo -e "${RED}✗ Scenario 2: FAILED${NC}"
fi

if [ $SCENARIO3 -eq 0 ]; then
    echo -e "${GREEN}✓ Scenario 3: PASSED${NC}"
else
    echo -e "${RED}✗ Scenario 3: FAILED${NC}"
fi

echo ""

# Exit avec erreur si au moins un test a échoué
if [ $SCENARIO1 -ne 0 ] || [ $SCENARIO2 -ne 0 ] || [ $SCENARIO3 -ne 0 ]; then
    exit 1
fi

exit 0
