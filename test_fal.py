# -*- coding: utf-8 -*-
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

import os, traceback
from dotenv import load_dotenv
load_dotenv()

os.environ["FAL_KEY"] = os.getenv("FAL_KEY", "")
print(f"FAL_KEY set: {'YES' if os.environ.get('FAL_KEY') else 'NO - MISSING'}")
print(f"FAL_KEY prefix: {os.environ.get('FAL_KEY','')[:20]}...")

import fal_client

print("\nTesting fal.ai FLUX 1.1 Pro Ultra...")
try:
    result = fal_client.subscribe(
        "fal-ai/flux-pro/v1.1-ultra",
        arguments={
            "prompt": "A silver ring on white marble, jewelry photography, cream background",
            "num_images": 1,
            "output_format": "jpeg",
            "aspect_ratio": "1:1",
            "safety_tolerance": "6",
        },
    )
    print(f"Result keys: {list(result.keys()) if result else 'None'}")
    images = result.get("images", []) if result else []
    if images:
        print(f"SUCCESS — image URL: {images[0]['url'][:80]}...")
    else:
        print(f"EMPTY images. Full response: {result}")
except Exception as e:
    print(f"EXCEPTION: {e}")
    traceback.print_exc()
