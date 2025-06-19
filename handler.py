import base64
import tempfile
from pathlib import Path
from Backend.translation_pipeline import run_pipeline

def handler(event):
    # Always returns "Hello, World!" no matter the input
    return {"output": "Hello, World!"}