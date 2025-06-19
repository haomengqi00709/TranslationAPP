from fastapi import FastAPI, UploadFile, File, HTTPException, Query, BackgroundTasks
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
from Backend.model_loader import get_model_and_tokenizer
import uuid
import random
import json
import psutil

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

print("=== CUDA DEBUG INFO ===")
print("CUDA available:", torch.cuda.is_available())
print("CUDA device count:", torch.cuda.device_count())
if torch.cuda.is_available():
    print("CUDA device name:", torch.cuda.get_device_name(0))
print("=======================")

app = FastAPI(title="PowerPoint Translation API")

# Global model and tokenizer instance
model = None
tokenizer = None

# In-memory job store for demonstration (use Redis or DB for production)
jobs = {}
MAX_CONCURRENT_JOBS = 2  # Limit concurrent translations
job_queue = []  # Queue for waiting jobs

def get_device():
    if torch.cuda.is_available():
        return "cuda"
    elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        return "mps"
    else:
        return "cpu"

@app.on_event("startup")
async def startup_event():
    """Initialize the model and tokenizer on startup."""
    global model, tokenizer
    try:
        device = get_device()
        model, tokenizer = get_model_and_tokenizer("Qwen/Qwen3-8B", device=device)
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

def background_translation(job_id, pptx_path, glossary_path, model_name, apply_layout):
    global model, tokenizer
    try:
        # Set up output path
        output_dir = f"/tmp/{job_id}_output"
        os.makedirs(output_dir, exist_ok=True)
        output_pptx = os.path.join(output_dir, f"{Path(pptx_path).stem}_fr.pptx")
        
        # Initialize job with simple line tracking
        jobs[job_id]['current_line'] = 0
        jobs[job_id]['message'] = 'Starting translation...'
        
        # Start a background thread to simulate progressive line tracking
        import threading
        import time
        
        def simulate_progress():
            """Simple progressive line tracking - increment every 0.5-2 seconds randomly"""
            current_line = 0
            
            while jobs[job_id]['status'] == 'processing':
                # Random delay between 0.5-2 seconds
                delay = random.uniform(0.5, 2.0)
                time.sleep(delay)
                current_line += 1
                jobs[job_id]['current_line'] = current_line
                jobs[job_id]['message'] = f"Processing line {current_line}"
                logger.info(f"Job {job_id}: {jobs[job_id]['message']} (delay: {delay:.1f}s)")
        
        # Start progress simulation thread
        progress_thread = threading.Thread(target=simulate_progress)
        progress_thread.daemon = True
        progress_thread.start()
        
        # Run the real pipeline
        run_pipeline(
            input_pptx=pptx_path,
            output_pptx=output_pptx,
            glossary_file=glossary_path,
            model_path=model_name,
            apply_layout=apply_layout
        )
        
        jobs[job_id]['status'] = 'done'
        jobs[job_id]['message'] = 'Translation complete. Ready to download.'
        jobs[job_id]['output_path'] = output_pptx
        
        # Process queue to start next job
        process_queue()
        
        # Clean up temporary files
        try:
            if os.path.exists(pptx_path):
                os.remove(pptx_path)
            if os.path.exists(glossary_path):
                os.remove(glossary_path)
            logger.info(f"Cleaned up temporary files for job {job_id}")
        except Exception as e:
            logger.warning(f"Failed to clean up temporary files for job {job_id}: {e}")
            
    except Exception as e:
        jobs[job_id]['status'] = 'error'
        jobs[job_id]['message'] = f'Error: {str(e)}'
        
        # Process queue even on error to start next job
        process_queue()
        
        # Clean up temporary files even on error
        try:
            if os.path.exists(pptx_path):
                os.remove(pptx_path)
            if os.path.exists(glossary_path):
                os.remove(glossary_path)
        except Exception as cleanup_error:
            logger.warning(f"Failed to clean up temporary files after error: {cleanup_error}")

@app.post("/start-translation")
async def start_translation(
    background_tasks: BackgroundTasks,
    pptx_file: UploadFile = File(...),
    glossary_file: UploadFile = File(None),  # Make optional
    model_name: str = Query("Qwen/Qwen3-8B"),
    apply_layout: bool = Query(False),
    custom_glossary: str = Query("[]")  # JSON string of user terms
):
    # Clean up old jobs first
    cleanup_old_jobs()
    
    # Check system resources
    can_process, message = check_system_resources()
    if not can_process and "memory" in message.lower():
        # Only reject if it's a memory issue, otherwise queue
        raise HTTPException(status_code=503, detail=f"System busy: {message}")
    
    job_id = str(uuid.uuid4())
    
    # Save PowerPoint file
    pptx_path = f"/tmp/{job_id}_{pptx_file.filename}"
    with open(pptx_path, "wb") as f:
        f.write(await pptx_file.read())
    
    # Handle glossary - either uploaded file or custom terms, or both
    glossary_path = None
    
    # Parse user custom glossary
    user_terms = []
    try:
        user_terms = json.loads(custom_glossary)
    except json.JSONDecodeError:
        user_terms = []
    
    if glossary_file and user_terms:
        # Both uploaded file and custom terms - merge them
        logger.info(f"User provided both glossary file and {len(user_terms)} custom terms - merging")
        
        # Read uploaded glossary file
        uploaded_terms = []
        try:
            uploaded_content = await glossary_file.read()
            for line in uploaded_content.decode('utf-8').split('\n'):
                if line.strip():
                    uploaded_terms.append(json.loads(line))
        except Exception as e:
            logger.warning(f"Failed to parse uploaded glossary file: {e}")
            uploaded_terms = []
        
        # Merge uploaded terms with custom terms
        all_terms = uploaded_terms + user_terms
        logger.info(f"Merged {len(uploaded_terms)} uploaded terms with {len(user_terms)} custom terms = {len(all_terms)} total")
        
        # Create merged glossary file
        glossary_path = f"/tmp/{job_id}_merged_glossary.jsonl"
        with open(glossary_path, 'w', encoding='utf-8') as f:
            for term in all_terms:
                f.write(json.dumps(term, ensure_ascii=False) + '\n')
                
    elif glossary_file:
        # Only uploaded glossary file
        glossary_path = f"/tmp/{job_id}_{glossary_file.filename}"
        with open(glossary_path, "wb") as f:
            f.write(await glossary_file.read())
            
    elif user_terms:
        # Only custom terms
        glossary_path = f"/tmp/{job_id}_custom_glossary.jsonl"
        with open(glossary_path, 'w', encoding='utf-8') as f:
            for term in user_terms:
                f.write(json.dumps(term, ensure_ascii=False) + '\n')
                
    else:
        # No glossary provided - create empty glossary file
        glossary_path = f"/tmp/{job_id}_empty_glossary.jsonl"
        with open(glossary_path, 'w', encoding='utf-8') as f:
            # Create a completely empty file to avoid RAG processing
            pass  # Empty file - no content
    
    # Check if we can start processing immediately
    active_jobs = sum(1 for job in jobs.values() if job.get('status') == 'processing')
    
    if active_jobs < MAX_CONCURRENT_JOBS:
        # Can start immediately
        jobs[job_id] = {
            "status": "processing",
            "message": "Starting translation...",
            "output_path": None,
            "created_time": time.time()
        }
        
        # Start background task immediately
        background_tasks.add_task(
            background_translation, 
            job_id, pptx_path, glossary_path, model_name, apply_layout
        )
        
        logger.info(f"Started job {job_id} immediately")
        
    else:
        # Add to queue
        queue_position = len(job_queue) + 1
        jobs[job_id] = {
            "status": "queued",
            "message": f"Queued: Position {queue_position} of {queue_position}",
            "output_path": None,
            "created_time": time.time(),
            "queue_position": queue_position
        }
        
        # Add to queue
        job_queue.append({
            'job_id': job_id,
            'pptx_path': pptx_path,
            'glossary_path': glossary_path,
            'model_name': model_name,
            'apply_layout': apply_layout
        })
        
        logger.info(f"Queued job {job_id} at position {queue_position}")
    
    return {"job_id": job_id, "status": jobs[job_id]["status"], "message": jobs[job_id]["message"]}

@app.get("/job-status")
async def job_status(job_id: str):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    response = {
        "job_id": job_id, 
        "status": job["status"], 
        "message": job["message"]
    }
    
    # Add line tracking info if available
    if "current_line" in job:
        response["current_line"] = job["current_line"]
    
    # Add queue information if queued
    if job["status"] == "queued" and "queue_position" in job:
        response["queue_position"] = job["queue_position"]
        response["queue_length"] = len(job_queue)
    
    return response

@app.get("/download")
async def download(job_id: str):
    job = jobs.get(job_id)
    if not job or job["status"] != "done":
        raise HTTPException(status_code=404, detail="File not ready")
    return FileResponse(job["output_path"], filename="translated.pptx")

def cleanup_old_jobs():
    """Clean up jobs older than 1 hour to prevent memory buildup."""
    current_time = time.time()
    jobs_to_remove = []
    
    for job_id, job_data in jobs.items():
        if 'created_time' not in job_data:
            job_data['created_time'] = current_time
        elif current_time - job_data['created_time'] > 3600:  # 1 hour
            jobs_to_remove.append(job_id)
    
    for job_id in jobs_to_remove:
        del jobs[job_id]
        logger.info(f"Cleaned up old job: {job_id}")
    
    return len(jobs_to_remove)

def check_system_resources():
    """Check if system has enough resources for new job."""
    # Check memory usage
    memory_percent = psutil.virtual_memory().percent
    if memory_percent > 85:
        return False, f"System memory usage too high: {memory_percent}%"
    
    # Don't check concurrent jobs since we queue them now
    return True, "OK"

def process_queue():
    """Process queued jobs when slots become available."""
    global job_queue
    
    # Check if we can start any queued jobs
    active_jobs = sum(1 for job in jobs.values() if job.get('status') == 'processing')
    available_slots = MAX_CONCURRENT_JOBS - active_jobs
    
    # Start queued jobs if slots are available
    while job_queue and available_slots > 0:
        queued_job = job_queue.pop(0)  # Get first job in queue
        job_id = queued_job['job_id']
        
        # Update job status to processing
        if job_id in jobs:
            jobs[job_id]['status'] = 'processing'
            jobs[job_id]['message'] = 'Starting translation...'
            jobs[job_id]['queue_position'] = None  # Remove queue position
            
            # Start the background task
            import threading
            thread = threading.Thread(
                target=background_translation,
                args=(
                    job_id, 
                    queued_job['pptx_path'], 
                    queued_job['glossary_path'], 
                    queued_job['model_name'], 
                    queued_job['apply_layout']
                )
            )
            thread.daemon = True
            thread.start()
            
            logger.info(f"Started queued job {job_id}")
            available_slots -= 1
    
    # Update queue positions for remaining jobs
    for i, queued_job in enumerate(job_queue):
        job_id = queued_job['job_id']
        if job_id in jobs:
            jobs[job_id]['queue_position'] = i + 1
            jobs[job_id]['message'] = f'Queued: Position {i + 1} of {len(job_queue)}'

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000) 