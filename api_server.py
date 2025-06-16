from fastapi import FastAPI, UploadFile, File, HTTPException, Query
from fastapi.responses import FileResponse
import uvicorn
import os
import shutil
import tempfile
from pathlib import Path
import time
from Backend.translation_pipeline import run_pipeline
import logging
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="PowerPoint Translation API")

# Global model instance
model = None

@app.on_event("startup")
async def startup_event():
    """Initialize the model on startup."""
    global model
    try:
        # Initialize your model here
        # model = load_model()
        device = "cuda" if torch.cuda.is_available() else "cpu"
        model = AutoModelForCausalLM.from_pretrained(
            "Qwen/Qwen3-8B",
            torch_dtype=torch.float16,
            device_map=device
        )
        tokenizer = AutoTokenizer.from_pretrained("Qwen/Qwen3-8B")
    except Exception as e:
        logger.error(f"Failed to initialize model: {e}")
        raise

@app.post("/translate")
async def translate_presentation(
    pptx_file: UploadFile = File(...),
    glossary_file: UploadFile = File(...),
    model_name: str = Query("Qwen/Qwen3-8B", description="Translation model to use"),
    apply_layout: bool = Query(False, description="Whether to apply layout adjustments")
):
    """
    Translate a PowerPoint presentation using the specified model and glossary.
    Optionally apply layout adjustments to match the original presentation.
    """
    try:
        # Create temporary directories
        session_id = str(int(time.time()))
        base_dir = Path(tempfile.gettempdir()) / f"translation_{session_id}"
        dirs = {
            'input': base_dir / 'input',
            'output': base_dir / 'output',
            'layout': base_dir / 'layout',
            'slides': base_dir / 'slides',
            'glossary': base_dir / 'glossary'
        }
        
        for dir_path in dirs.values():
            dir_path.mkdir(parents=True, exist_ok=True)
        
        # Save uploaded files
        pptx_path = dirs['slides'] / pptx_file.filename
        glossary_path = dirs['glossary'] / glossary_file.filename
        
        with open(pptx_path, 'wb') as f:
            shutil.copyfileobj(pptx_file.file, f)
        with open(glossary_path, 'wb') as f:
            shutil.copyfileobj(glossary_file.file, f)
        
        # Run pipeline
        output_pptx = dirs['output'] / f"{Path(pptx_file.filename).stem}_fr.pptx"
        
        run_pipeline(
            input_pptx=str(pptx_path),
            output_pptx=str(output_pptx),
            glossary_file=str(glossary_path),
            model_path=model_name,
            apply_layout=apply_layout
        )
        
        # If layout was applied, return the layout-adjusted file
        if apply_layout:
            output_pptx = output_pptx.replace(".pptx", "_layout.pptx")
        
        # Return the translated file
        return FileResponse(
            path=str(output_pptx),
            filename=f"{Path(pptx_file.filename).stem}_fr.pptx",
            media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation"
        )
        
    except Exception as e:
        logger.error(f"Translation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
        
    # finally:
    #     # Clean up temporary files
    #     try:
    #         shutil.rmtree(base_dir)
    #     except Exception as e:
    #         logger.error(f"Failed to clean up temporary files: {e}")

@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000) 