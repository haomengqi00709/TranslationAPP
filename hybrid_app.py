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

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load secrets from Streamlit
RUNPOD_API_KEY = st.secrets["runpod"]["api_key"]
RUNPOD_ENDPOINT = st.secrets["runpod"]["endpoint"]
BACKEND_URL = RUNPOD_ENDPOINT if RUNPOD_ENDPOINT else "http://localhost:8000"

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
    glossary_file = st.file_uploader("Upload Glossary File (Optional)", type=['jsonl'])
    
    # Model selection
    model_name = st.selectbox(
        "Select Translation Model",
        AVAILABLE_MODELS,
        index=AVAILABLE_MODELS.index(DEFAULT_MODEL)
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
            
        # Check file size
        if pptx_file.size > MAX_FILE_SIZE:
            st.error(f"File size exceeds the maximum limit of {MAX_FILE_SIZE/1024/1024}MB")
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
                progress_bar.progress(20)
                
                try:
                    headers = {}
                    if RUNPOD_API_KEY:
                        headers["Authorization"] = f"Bearer {RUNPOD_API_KEY}"
                    
                    response = requests.post(
                        f"{BACKEND_URL}/translate",
                        files=files,
                        params={
                            'model_name': model_name,
                            'apply_layout': apply_layout
                        },
                        headers=headers
                    )
                    
                    if response.status_code == 200:
                        progress_bar.progress(100)
                        # Save the translated file
                        output_path = os.path.join(temp_dir, f"translated_{pptx_file.name}")
                        with open(output_path, 'wb') as f:
                            f.write(response.content)
                        
                        # Create download link
                        st.markdown(
                            f'<a href="data:application/vnd.openxmlformats-officedocument.presentationml.presentation;base64,{base64.b64encode(response.content).decode()}" download="translated_{pptx_file.name}">Click here to download the translated presentation</a>',
                            unsafe_allow_html=True
                        )
                        
                        st.success("Translation completed successfully!")
                    else:
                        st.error(f"Translation failed: {response.text}")
                        
                except requests.exceptions.ConnectionError:
                    st.error("Could not connect to the translation server. Please check your internet connection and try again.")
                except Exception as e:
                    st.error(f"An error occurred during translation: {str(e)}")
                
        except Exception as e:
            st.error(f"An error occurred: {str(e)}")
            
        finally:
            # Clear progress indicators
            progress_bar.empty()
            status_text.empty()

if __name__ == "__main__":
    streamlit_frontend()