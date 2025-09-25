# server/protocol.py
import json

def encode(msg: dict) -> str:
    """Convert a Python dict to a JSON string."""
    return json.dumps(msg)

def decode(text: str) -> dict:
    """Convert a JSON string back to a Python dict."""
    return json.loads(text)
