import streamlit as st
import requests
import tempfile
import os
from pathlib import Path
import time
import logging
from fastapi import FastAPI, UploadFile, File, HTTPException, Query
from fastapi.responses import FileResponse
import uvicorn
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer
import shutil
import asyncio
import base64

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Constants
BACKEND_URL = "http://localhost:8000"  # Change this to your GPU backend URL

# Frontend (Streamlit)
def streamlit_frontend():
    st.set_page_config(
        page_title="PowerPoint Translation",
        page_icon="📊",
        layout="wide"
    )
    
    st.title("PowerPoint Translation")
    st.write("Upload your PowerPoint presentation and optionally a glossary file to translate it to French.")
    
    # File upload
    pptx_file = st.file_uploader("Upload PowerPoint File", type=['pptx'])
    glossary_file = st.file_uploader("Upload Glossary File (Optional)", type=['jsonl'])
    
    # Model selection
    model_name = st.selectbox(
        "Select Translation Model",
        ["Qwen/Qwen3-8B", "Qwen/Qwen3-14B", "Qwen/Qwen3-72B"],
        index=0
    )
    
    # Layout option
    apply_layout = st.checkbox(
        "Apply Layout Adjustments",
        help="Adjust the layout of the translated presentation to match the original"
    )
    
    if st.button("Translate"):
        if not pptx_file:
            st.error("Please upload a PowerPoint file.")
            return
            
        try:
            # Create progress bar
            progress_bar = st.progress(0)
            status_text = st.empty()
            
            # Save files to temporary directory
            with tempfile.TemporaryDirectory() as temp_dir:
                # Save uploaded files
                pptx_path = os.path.join(temp_dir, pptx_file.name)
                with open(pptx_path, 'wb') as f:
                    f.write(pptx_file.getvalue())
                
                # Prepare files for upload
                files = {
                    'pptx_file': (pptx_file.name, open(pptx_path, 'rb'))
                }
                
                # Add glossary file if provided
                if glossary_file:
                    glossary_path = os.path.join(temp_dir, glossary_file.name)
                    with open(glossary_path, 'wb') as f:
                        f.write(glossary_file.getvalue())
                    files['glossary_file'] = (glossary_file.name, open(glossary_path, 'rb'))
                else:
                    # Create empty glossary file
                    empty_glossary_path = os.path.join(temp_dir, "empty_glossary.jsonl")
                    with open(empty_glossary_path, 'w', encoding='utf-8') as f:
                        f.write('{"en": "", "fr": ""}\n')
                    files['glossary_file'] = ("empty_glossary.jsonl", open(empty_glossary_path, 'rb'))
                
                # Make API request
                status_text.text("Sending files to translation server...")
                response = requests.post(
                    f"{BACKEND_URL}/translate",
                    files=files,
                    params={
                        'model_name': model_name,
                        'apply_layout': apply_layout
                    }
                )
                
                if response.status_code == 200:
                    # Save the translated file
                    output_path = os.path.join(temp_dir, f"translated_{pptx_file.name}")
                    with open(output_path, 'wb') as f:
                        f.write(response.content)
                    
                    # Auto-download the file
                    st.markdown(
                        f'<a href="data:application/vnd.openxmlformats-officedocument.presentationml.presentation;base64,{base64.b64encode(response.content).decode()}" download="translated_{pptx_file.name}">Click here if download does not start automatically</a>',
                        unsafe_allow_html=True
                    )
                    
                    # Add JavaScript for auto-download
                    st.markdown(
                        f"""
                        <script>
                            var link = document.createElement('a');
                            link.href = "data:application/vnd.openxmlformats-officedocument.presentationml.presentation;base64,{base64.b64encode(response.content).decode()}";
                            link.download = "translated_{pptx_file.name}";
                            document.body.appendChild(link);
                            link.click();
                            document.body.removeChild(link);
                        </script>
                        """,
                        unsafe_allow_html=True
                    )
                    
                    st.success("Translation completed successfully! Your file should download automatically.")
                else:
                    st.error(f"Translation failed: {response.text}")
                
        except Exception as e:
            st.error(f"An error occurred: {str(e)}")
            
        finally:
            # Clear progress indicators
            progress_bar.empty()
            status_text.empty()

# Backend (FastAPI)
app = FastAPI(title="PowerPoint Translation API")

@app.on_event("startup")
async def startup_event():
    """Initialize the translation pipeline on startup."""
    try:
        # Check if we can import the pipeline
        from translation_pipeline import run_pipeline
        logger.info("Translation pipeline imported successfully")
    except Exception as e:
        logger.error(f"Failed to import pipeline: {e}")
        raise

@app.post("/translate")
async def translate_presentation(
    pptx_file: UploadFile = File(...),
    glossary_file: UploadFile = File(None),
    model_name: str = Query("Qwen/Qwen3-8B", description="Translation model to use"),
    apply_layout: bool = Query(False, description="Whether to apply layout adjustments")
):
    """
    Translate a PowerPoint presentation using the specified model and glossary.
    Optionally apply layout adjustments to match the original presentation.
    If no glossary file is provided, an empty glossary will be used.
    """
    base_dir = None
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
            logger.info(f"Created directory: {dir_path}")
        
        # Save uploaded files
        pptx_path = dirs['slides'] / pptx_file.filename
        with open(pptx_path, 'wb') as f:
            shutil.copyfileobj(pptx_file.file, f)
        
        # Handle glossary file
        glossary_path = dirs['glossary'] / "glossary.jsonl"
        if glossary_file and glossary_file.filename:
            with open(glossary_path, 'wb') as f:
                shutil.copyfileobj(glossary_file.file, f)
            logger.info(f"Using provided glossary file: {glossary_file.filename}")
        else:
            # Create empty glossary file
            with open(glossary_path, 'w', encoding='utf-8') as f:
                f.write('{"en": "", "fr": ""}\n')
            logger.info("No glossary file provided, using empty glossary")
        
        logger.info(f"Saved input files: {pptx_path}, {glossary_path}")
        
        # Run pipeline
        output_pptx = dirs['output'] / f"{Path(pptx_file.filename).stem}_fr.pptx"
        logger.info(f"Will save output to: {output_pptx}")
        
        try:
            from translation_pipeline import run_pipeline
            run_pipeline(
                input_pptx=str(pptx_path),
                output_pptx=str(output_pptx),
                glossary_file=str(glossary_path),
                model_path=model_name,
                apply_layout=apply_layout
            )
            
            # Verify the output file exists and is not empty
            if not output_pptx.exists():
                raise FileNotFoundError(f"Pipeline did not create output file: {output_pptx}")
            if output_pptx.stat().st_size == 0:
                raise ValueError(f"Output file is empty: {output_pptx}")
            
            logger.info(f"Translation completed successfully. Output file: {output_pptx}")
            
            # If layout was applied, check for layout-adjusted file
            if apply_layout:
                layout_pptx = output_pptx.with_name(f"{output_pptx.stem}_layout.pptx")
                if layout_pptx.exists():
                    output_pptx = layout_pptx
                    logger.info(f"Using layout-adjusted file: {output_pptx}")
            
            # Create a copy of the file in a new location that won't be cleaned up
            final_output = base_dir / "final_output.pptx"
            shutil.copy2(output_pptx, final_output)
            logger.info(f"Created final output copy at: {final_output}")
            
            # Ensure the file exists and is not empty before sending
            if not final_output.exists():
                raise FileNotFoundError(f"Final output file not found: {final_output}")
            if final_output.stat().st_size == 0:
                raise ValueError(f"Final output file is empty: {final_output}")
            
            # Create a response that will handle the file serving
            response = FileResponse(
                path=str(final_output),
                filename=f"{Path(pptx_file.filename).stem}_fr.pptx",
                media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation"
            )
            
            # Add cleanup callback to response
            async def cleanup():
                try:
                    # Wait a bit to ensure file is served
                    await asyncio.sleep(5)
                    if base_dir and base_dir.exists():
                        shutil.rmtree(base_dir)
                        logger.info(f"Cleaned up temporary directory: {base_dir}")
                except Exception as e:
                    logger.error(f"Failed to clean up temporary files: {e}")
            
            # Set the cleanup as a background task
            response.background = cleanup
            return response
            
        except Exception as e:
            logger.error(f"Pipeline execution failed: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail=f"Translation pipeline failed: {str(e)}"
            )
        
    except Exception as e:
        logger.error(f"Translation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy"}

def main():
    """Main function to run either the frontend or backend."""
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "--backend":
        # Run FastAPI backend
        uvicorn.run(app, host="0.0.0.0", port=8000)
    else:
        # Run Streamlit frontend
        streamlit_frontend()

if __name__ == "__main__":
    main() 