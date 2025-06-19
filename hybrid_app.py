import streamlit as st
import requests
import tempfile
import os
from pathlib import Path
import time
import logging
import shutil
import base64
from dotenv import load_dotenv
import json

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load secrets from Streamlit
RUNPOD_API_KEY = st.secrets["runpod"]["api_key"]
RUNPOD_ENDPOINT = st.secrets["runpod"]["endpoint"]
BACKEND_URL = RUNPOD_ENDPOINT if RUNPOD_ENDPOINT else "https://sbcub0e3qx9ryu-8000.proxy.runpod.net"

# App configuration
APP_TITLE = st.secrets["app"]["title"]
APP_DESCRIPTION = st.secrets["app"]["description"]

# Model configuration
DEFAULT_MODEL = st.secrets["models"]["default_model"]
AVAILABLE_MODELS = st.secrets["models"]["available_models"]

# Upload configuration
MAX_FILE_SIZE = st.secrets["upload"]["max_file_size"] * 1024 * 1024  # Convert to bytes
ALLOWED_EXTENSIONS = st.secrets["upload"]["allowed_extensions"]

def streamlit_frontend():
    st.set_page_config(
        page_title=APP_TITLE,
        page_icon="📊",
        layout="wide"
    )
    
    st.title(APP_TITLE)
    st.write(APP_DESCRIPTION)
    
    # File upload
    pptx_file = st.file_uploader("Upload PowerPoint File", type=['pptx'])
    
    # Glossary section - vertical layout
    glossary_file = st.file_uploader(
        "Upload Glossary File (Optional)", 
        type=['jsonl'],
        help="Used for special needs when there are specific term translations you want to ensure are used consistently. Upload a JSONL file with English-French term pairs."
    )
    
    # Custom terms section right below
    st.write("**Or add custom terms:**")
    col1, col2 = st.columns(2)
    
    with col1:
        english_term = st.text_input("English Term", key="eng_term", placeholder="e.g., Technical Term")
    with col2:
        french_term = st.text_input("French Translation", key="fr_term", placeholder="e.g., Terme technique")
    
    # Add button
    if st.button("➕ Add Term", type="secondary"):
        if english_term and french_term:
            # Add to session state
            if 'custom_glossary' not in st.session_state:
                st.session_state.custom_glossary = []
            st.session_state.custom_glossary.append({
                'en': english_term.strip(),
                'fr': french_term.strip()
            })
            st.success(f"✅ Added: {english_term} → {french_term}")
            # Clear the input fields
            st.rerun()
        elif not english_term or not french_term:
            st.error("Please enter both English and French terms")
    
    # Display current custom glossary in a nice format
    if 'custom_glossary' in st.session_state and st.session_state.custom_glossary:
        st.write("**📋 Your Custom Terms:**")
        
        # Display terms in a more organized way with delete buttons
        for i, term in enumerate(st.session_state.custom_glossary):
            col_term1, col_term2 = st.columns([1, 1])
            with col_term1:
                st.write(f"{i+1}. **{term['en']}** → *{term['fr']}*")
            with col_term2:
                if st.button("×", key=f"delete_{i}", help=f"Delete: {term['en']} → {term['fr']}"):
                    st.session_state.custom_glossary.pop(i)
                    st.rerun()
        
        # Action buttons for custom glossary
        col_clear1, col_clear2, col_download = st.columns([1, 2, 1])
        with col_clear1:
            if st.button("Clear All", type="secondary"):
                st.session_state.custom_glossary = []
                st.rerun()
        
        with col_download:
            # Create JSONL content for download
            jsonl_content = ""
            for term in st.session_state.custom_glossary:
                jsonl_content += json.dumps(term, ensure_ascii=False) + '\n'
            
            # Create download button
            st.download_button(
                label="Download JSONL for future use",
                data=jsonl_content,
                file_name="custom_glossary.jsonl",
                mime="application/json",
                type="secondary"
            )
        
        st.write("---")
    
    # Model selection - hidden for security
    model_name = DEFAULT_MODEL  # Always use default model, don't show selection to users
    
    # Layout option
    apply_layout = st.checkbox(
        "Apply Layout Adjustments (testing, not recommended yet)",
        help="Adjust the layout of the translated presentation to match the original"
    )
    
    status_text = st.empty()
    
    if st.button("Translate"):
        if not pptx_file:
            st.error("Please upload a PowerPoint file.")
            return
        
        if pptx_file.size > MAX_FILE_SIZE:
            st.error(f"File size exceeds the maximum limit of {MAX_FILE_SIZE/1024/1024}MB")
            return
        
        try:
            progress_bar = st.progress(0)
            status_text.info("Processing English")
            with tempfile.TemporaryDirectory() as temp_dir:
                pptx_path = os.path.join(temp_dir, pptx_file.name)
                with open(pptx_path, 'wb') as f:
                    f.write(pptx_file.getvalue())
                
                # Prepare files for upload
                files = {'pptx_file': (pptx_file.name, open(pptx_path, 'rb'))}
                
                # Add glossary file if provided
                if glossary_file:
                    glossary_path = os.path.join(temp_dir, glossary_file.name)
                    with open(glossary_path, 'wb') as f:
                        f.write(glossary_file.getvalue())
                    files['glossary_file'] = (glossary_file.name, open(glossary_path, 'rb'))
                
                # Prepare custom glossary data
                custom_glossary_data = st.session_state.get('custom_glossary', [])
                custom_glossary_json = json.dumps(custom_glossary_data)

                # Show status about glossary sources
                if glossary_file and custom_glossary_data:
                    st.info(f"📋 Using uploaded glossary file ({glossary_file.name}) with {len(custom_glossary_data)} custom terms")
                elif glossary_file:
                    st.info(f"📋 Using uploaded glossary file: {glossary_file.name}")
                elif custom_glossary_data:
                    st.info(f"📋 Using {len(custom_glossary_data)} custom terms")
                else:
                    st.info("📋 No glossary provided - using standard translation")

                # Start translation job
                status_text.text("Starting translation job...")
                progress_value = 20  # Start after job submission
                progress_bar.progress(progress_value)
                headers = {}
                if RUNPOD_API_KEY:
                    headers["Authorization"] = f"Bearer {RUNPOD_API_KEY}"
                
                # Prepare parameters
                params = {
                    'model_name': model_name,
                    'apply_layout': apply_layout,
                    'custom_glossary': custom_glossary_json
                }
                
                response = requests.post(
                    f"{BACKEND_URL}/start-translation",
                    files=files,
                    params=params,
                    headers=headers
                )
                if response.status_code != 200:
                    st.error(f"Failed to start translation: {response.text}")
                    return
                job_info = response.json()
                job_id = job_info["job_id"]
                status_text.text(job_info.get("message", "Processing..."))
                progress_bar.progress(progress_value)

                # Poll for job status
                while True:
                    time.sleep(5)
                    status_response = requests.get(f"{BACKEND_URL}/job-status", params={"job_id": job_id}, headers=headers)
                    if status_response.status_code != 200:
                        st.error(f"Failed to get job status: {status_response.text}")
                        return
                    status_json = status_response.json()
                    
                    # Display progressive line information if available
                    current_line = status_json.get("current_line")
                    
                    if current_line:
                        # Show simple line progress
                        status_text.text(f"Processing line {current_line}")
                        # Simple progress bar increment
                        progress_value = min(20 + (current_line * 2), 90)  # Scale line number to progress
                        progress_bar.progress(progress_value)
                    elif status_json["status"] == "queued":
                        # Show queue information
                        queue_position = status_json.get("queue_position", 0)
                        queue_length = status_json.get("queue_length", 0)
                        status_text.text(f"⏳ Queued: Position {queue_position} of {queue_length}")
                        # Show minimal progress for queued jobs
                        progress_value = 10
                        progress_bar.progress(progress_value)
                    else:
                        # Fallback to message if line info not available
                        status_text.text(status_json.get("message", "Processing..."))
                        progress_value = min(progress_value + 10, 90)
                        progress_bar.progress(progress_value)
                    
                    if status_json["status"] == "done":
                        progress_value = 90
                        progress_bar.progress(progress_value)
                        break

                # Download the result
                download_response = requests.get(f"{BACKEND_URL}/download", params={"job_id": job_id}, headers=headers)
                if download_response.status_code == 200:
                    progress_bar.progress(100)
                    output_path = os.path.join(temp_dir, f"translated_{pptx_file.name}")
                    with open(output_path, 'wb') as f:
                        f.write(download_response.content)
                    st.markdown(
                        f'<a href="data:application/vnd.openxmlformats-officedocument.presentationml.presentation;base64,{base64.b64encode(download_response.content).decode()}" download="translated_{pptx_file.name}">Click here to download the translated presentation</a>',
                        unsafe_allow_html=True
                    )
                    st.success("Translation completed successfully!")
                else:
                    st.error(f"Failed to download translated file: {download_response.text}")

        except Exception as e:
            st.error(f"An error occurred: {str(e)}")
        finally:
            progress_bar.empty()
            status_text.empty()

if __name__ == "__main__":
    streamlit_frontend()