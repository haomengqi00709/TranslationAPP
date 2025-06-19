import requests
from pathlib import Path

# Replace with your actual file paths
pptx_path = "/Users/jasonhao/Desktop/LLM experiments/translatedocs/forst/translatorAPP/slides/PPT-3-Government-in-Canada1 (2).pptx"
glossary_path = "/Users/jasonhao/Desktop/LLM experiments/translatedocs/forst/glossaryfile/glossary1.jsonl"

url = "https://sbcub0e3qx9ryu-8000.proxy.runpod.net/translate"

with open(pptx_path, "rb") as pptx_file, open(glossary_path, "rb") as glossary_file:
    files = {
        "pptx_file": (pptx_path, pptx_file, "application/vnd.openxmlformats-officedocument.presentationml.presentation"),
        "glossary_file": (glossary_path, glossary_file, "text/plain"),
    }
    data = {
        "model_name": "Qwen/Qwen3-8B",  # or another model if you want
        "apply_layout": "false",         # or "true" if you want layout adjustment
    }
    response = requests.post(url, files=files, data=data)
    if response.status_code == 200:
        # Save the translated pptx
        with open("translated_output.pptx", "wb") as out_file:
            out_file.write(response.content)
        print("Translation successful! Saved as translated_output.pptx")
    else:
        print("Error:", response.status_code, response.text)