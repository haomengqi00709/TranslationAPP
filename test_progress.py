#!/usr/bin/env python3
"""
Test script to verify progressive line tracking functionality
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from Backend.translate_all import process_file, LocalTranslator
from Backend.model_loader import get_model_and_tokenizer
import tempfile
import json

def test_progress_callback(current_line=None, total_lines=None, message=None):
    """Test progress callback function"""
    print(f"PROGRESS: Line {current_line}/{total_lines} - {message}")

def create_test_file():
    """Create a test JSONL file with sample data"""
    test_data = [
        {"text": "Hello world", "french_text": "[FR]"},
        {"text": "Welcome to our presentation", "french_text": "[FR]"},
        {"text": "Today we will discuss important topics", "french_text": "[FR]"},
        {"text": "Key points include", "french_text": "[FR]"},
        {"text": "Thank you for your attention", "french_text": "[FR]"}
    ]
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False) as f:
        for item in test_data:
            f.write(json.dumps(item, ensure_ascii=False) + '\n')
        return f.name

def main():
    print("Testing progressive line tracking...")
    
    # Create test file
    test_file = create_test_file()
    output_file = test_file.replace('.jsonl', '_translated.jsonl')
    
    try:
        # Load model (this might take a while)
        print("Loading model...")
        model, tokenizer = get_model_and_tokenizer("Qwen/Qwen3-8B")
        translator = LocalTranslator(model, tokenizer)
        
        # Test process_file with progress callback
        print("Processing file with progress tracking...")
        processed_count = process_file(test_file, output_file, translator, test_progress_callback)
        
        print(f"✅ Test completed! Processed {processed_count} lines")
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
    finally:
        # Clean up
        if os.path.exists(test_file):
            os.unlink(test_file)
        if os.path.exists(output_file):
            os.unlink(output_file)

if __name__ == "__main__":
    main() 