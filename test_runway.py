# -*- coding: utf-8 -*-
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

import os, time, requests, traceback
from dotenv import load_dotenv
load_dotenv()

KEY = os.getenv("RUNWAY_API_KEY", "")
print(f"RUNWAY_API_KEY set: {'YES' if KEY else 'NO - MISSING'}")
print(f"Key prefix: {KEY[:30]}...")

BASE    = "https://api.dev.runwayml.com/v1"
VERSION = "2024-11-06"
HEADERS = {
    "Authorization": f"Bearer {KEY}",
    "X-Runway-Version": VERSION,
    "Content-Type": "application/json",
}

# Use a stable public image URL for testing
TEST_IMAGE = "https://images.unsplash.com/photo-1515562141207-7a88fb7ce338?w=768&q=80"  # jewelry on unsplash

print(f"\nStep 1 — Creating Runway task...")
try:
    r = requests.post(
        f"{BASE}/image_to_video",
        headers=HEADERS,
        json={
            "model":       "gen3a_turbo",
            "promptImage": TEST_IMAGE,
            "promptText":  "Slow elegant light drift, jewelry, 5 seconds",
            "duration":    5,
            "ratio":       "768:1280",
        },
        timeout=30,
    )
    print(f"Status: {r.status_code}")
    print(f"Response: {r.text[:500]}")

    if r.status_code != 200:
        print("FAILED at task creation")
    else:
        task_id = r.json().get("id", "")
        print(f"Task ID: {task_id}")

        print(f"\nStep 2 — Polling task status...")
        for i in range(6):
            time.sleep(10)
            poll = requests.get(f"{BASE}/tasks/{task_id}", headers=HEADERS, timeout=30)
            data = poll.json()
            status = data.get("status", "")
            print(f"  Poll {i+1}: status={status}")
            if status == "SUCCEEDED":
                print(f"  Output: {data.get('output', [])}")
                break
            if status in ("FAILED", "CANCELLED"):
                print(f"  Full response: {data}")
                break

except Exception as e:
    print(f"EXCEPTION: {e}")
    traceback.print_exc()
