#!/usr/bin/env python3
"""
Test simple de l'API
"""

import requests
import json

API_URL = "http://localhost:8000"

print("Testing API endpoints...")

# Test 1: Root
print("\n1. Testing root endpoint...")
try:
    response = requests.get(f"{API_URL}/")
    print(f"   Status: {response.status_code}")
    if response.status_code == 200:
        print(f"   Response: {json.dumps(response.json(), indent=2)}")
except Exception as e:
    print(f"   Error: {e}")

# Test 2: Health
print("\n2. Testing health endpoint...")
try:
    response = requests.get(f"{API_URL}/health")
    print(f"   Status: {response.status_code}")
    if response.status_code == 200:
        print(f"   Response: {json.dumps(response.json(), indent=2)}")
except Exception as e:
    print(f"   Error: {e}")

# Test 3: Station Status
print("\n3. Testing station status endpoint...")
try:
    response = requests.get(f"{API_URL}/station/status")
    print(f"Status Code: {response.status_code}")
    print(f"Headers: {dict(response.headers)}")
    print(f"\nResponse Body:")
    print(response.text)

    # Si c'est du JSON, l'afficher joliment
    try:
        data = response.json()
        print(f"\nJSON Response:")
        print(json.dumps(data, indent=2))
    except:
        pass

except Exception as e:
    print(f"Error: {e}")
