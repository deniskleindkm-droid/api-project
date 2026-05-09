import time
from fastapi import HTTPException, Request

# Store request timestamps per IP
request_counts = {}

MAX_REQUESTS = 10
WINDOW_SECONDS = 60

def rate_limit(request: Request):
    ip = request.client.host
    now = time.time()
    
    if ip not in request_counts:
        request_counts[ip] = []
    
    # Remove timestamps older than the window
    request_counts[ip] = [t for t in request_counts[ip] if now - t < WINDOW_SECONDS]
    
    if len(request_counts[ip]) >= MAX_REQUESTS:
        raise HTTPException(status_code=429, detail="Too many requests. Slow down!")
    
    request_counts[ip].append(now)