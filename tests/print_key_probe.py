# tests/print_key_probe.py
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
k = os.getenv("ANTHROPIC_API_KEY")

print("is None:", k is None)
if k is not None:
    print("repr :", repr(k))
    print("len  :", len(k))
    print("head :", k[:10])
    print("tail :", k[-10:])
    print("last5 code points:", [hex(ord(c)) for c in k[-5:]])
