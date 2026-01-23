import requests
from requests.auth import HTTPBasicAuth
import sys

BASE_URL = "http://localhost:8000"
USER = "admin"
PASS = "admin" # Default from .env.example

def test_api_auth():
    print("Testing API Authentication...")
    
    # 1. Test without auth
    print("- Testing without auth (should be 401)...")
    try:
        r = requests.get(f"{BASE_URL}/api/scripts")
        if r.status_code == 401:
            print("  [PASS] Got 401 Unauthorized")
        else:
            print(f"  [FAIL] Got {r.status_code} instead of 401")
    except Exception as e:
        print(f"  [ERROR] {e}")

    # 2. Test with auth
    print("- Testing with auth (should be 200)...")
    try:
        r = requests.get(f"{BASE_URL}/api/scripts", auth=HTTPBasicAuth(USER, PASS))
        if r.status_code == 200:
            print("  [PASS] Got 200 OK")
        else:
            print(f"  [FAIL] Got {r.status_code} instead of 200. Check if server is running and credentials are correct.")
    except Exception as e:
        print(f"  [ERROR] {e}")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        BASE_URL = sys.argv[1]
    test_api_auth()
