import requests
import os

def test_translation_api():
    # API endpoint
    url = "http://localhost:8000/translate"
    
    # File paths
    pptx_path = "slides/PPT-3-Government-in-Canada1 (2).pptx"
    glossary_path = "glossaryfile/glossary.jsonl"
    
    # Check if files exist
    if not os.path.exists(pptx_path):
        print(f"Error: PowerPoint file not found at {pptx_path}")
        return
    if not os.path.exists(glossary_path):
        print(f"Error: Glossary file not found at {glossary_path}")
        return
    
    # Prepare the files
    files = {
        'pptx_file': ('presentation.pptx', open(pptx_path, 'rb')),
        'glossary_file': ('glossary.jsonl', open(glossary_path, 'rb'))
    }
    
    # Parameters
    params = {
        'model_name': 'Qwen/Qwen3-8B',
        'apply_layout': False
    }
    
    try:
        # Make the request
        print("Sending translation request...")
        response = requests.post(url, files=files, params=params)
        
        # Check if request was successful
        if response.status_code == 200:
            # Save the translated file
            output_path = "output/translated_presentation.pptx"
            os.makedirs("output", exist_ok=True)
            with open(output_path, 'wb') as f:
                f.write(response.content)
            print(f"Translation successful! File saved to {output_path}")
        else:
            print(f"Error: {response.status_code}")
            print(response.text)
            
    except Exception as e:
        print(f"Error occurred: {str(e)}")
    finally:
        # Close the files
        files['pptx_file'][1].close()
        files['glossary_file'][1].close()

if __name__ == "__main__":
    test_translation_api() 