import requests
import json

try:
    response = requests.get("http://localhost:5000/health/background-tasks", timeout=5)
    if response.status_code == 200:
        data = response.json()
        print("Background tasks health:")
        print(json.dumps(data, indent=2))
    else:
        print(f"Health check failed with status: {response.status_code}")
except Exception as e:
    print(f"Error checking health: {e}")