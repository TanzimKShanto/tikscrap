#!/usr/bin/env python3
import requests
import sys
from dotenv import load_dotenv
import os


def test_token(token: str, page_id: str):
    """Test Facebook system user token by fetching /me"""
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    # Test Graph API /me endpoint
    url = (
        f"https://graph.facebook.com/v24.0/{page_id}?fields=instagram_business_account"
    )
    print(f"Testing: GET {url}")
    print(f"Token: {token[:20]}...")

    try:
        resp = requests.get(url, headers=headers, timeout=30)
        print(f"Status: {resp.status_code}")
        print(f"Response: {resp.text}")
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    load_dotenv()
    token = sys.argv[1] if len(sys.argv) > 1 else os.getenv("SYSTEM_USER_TOKEN")
    page_id = sys.argv[2] if len(sys.argv) > 2 else os.getenv("PAGE_ID")
    if not token:
        token = input("Enter token: ").strip()
    if not page_id:
        page_id = input("Enter page_id: ").strip()
    test_token(token, page_id)
