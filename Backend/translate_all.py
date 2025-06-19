import json
import logging
import torch
from typing import Dict, Any, List
import time
from pathlib import Path
from Backend.model_loader import get_model_and_tokenizer

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Device selection: CUDA > MPS > CPU
if torch.cuda.is_available():
    device = "cuda"
elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
    device = "mps"
else:
    device = "cpu"
logger.info(f"Using device: {device}")

class LocalTranslator:
    def __init__(self, model, tokenizer):
        """Initialize the translator with a shared LLM model and tokenizer."""
        self.model = model
        self.tokenizer = tokenizer
        logger.info("Model and tokenizer assigned to LocalTranslator")

    def translate(self, text: str) -> str:
        """Translate English text to French using the shared model."""
        try:
            # Create messages for chat template
            messages = [
                {"role": "system", "content": "You are a professional translator. Translate the following text to French. Only output the French translation. If there's only blank text, return an empty string."},
                {"role": "user", "content": text}
            ]
            
            # Apply chat template with thinking disabled
            prompt = self.tokenizer.apply_chat_template(
                messages,
                tokenize=False,
                add_generation_prompt=True,
                enable_thinking=False
            )
            
            # Tokenize
            inputs = self.tokenizer(prompt, return_tensors="pt").to(self.model.device)
            
            # Generate with optimized parameters
            with torch.no_grad():
                outputs = self.model.generate(
                    **inputs,
                    max_new_tokens=100,
                    temperature=0.8,
                    top_p=0.95,
                    top_k=20,
                    min_p=0,
                    do_sample=True
                )
            
            # Decode and clean output
            translation = self.tokenizer.decode(outputs[0], skip_special_tokens=True)
            # Extract only the French translation and clean up think tags
            translation = translation.split("assistant")[-1].strip()
            
            # More thorough cleaning of think tags
            translation = translation.replace("<think>", "")
            translation = translation.replace("</think>", "")
            translation = translation.replace("\n\n", " ").strip()
            
            return translation
        except Exception as e:
            logger.error(f"Translation error: {str(e)}")
            return text  # Return original text if translation fails

def process_jsonl_line(line: str, translator: LocalTranslator) -> Dict[str, Any]:
    """Process a single JSONL line and handle translations."""
    try:
        data = json.loads(line)
        
        # Handle tables_full.jsonl structure
        if 'data' in data:  # This is a table structure
            for row in data['data']:
                for cell in row:
                    for para in cell.get('paragraphs', []):
                        for run in para.get('runs', []):
                            if isinstance(run.get('french_text'), str) and run['french_text'].startswith('[FR]'):
                                english_text = run['text']
                                french_text = translator.translate(english_text)
                                run['french_text'] = french_text
        else:  # Regular text block or chart
            if isinstance(data.get('french_text'), str) and data['french_text'].startswith('[FR]'):
                english_text = data['text']
                french_text = translator.translate(english_text)
                data['french_text'] = french_text
        
        return data
    except json.JSONDecodeError:
        logger.error(f"Error decoding JSON line: {line}")
        return None

def process_file(input_file: str, output_file: str, translator: LocalTranslator) -> int:
    """Process a single JSONL file and write to output file."""
    processed_count = 0
    
    with open(input_file, 'r', encoding='utf-8') as f_in, \
         open(output_file, 'w', encoding='utf-8') as f_out:
        
        for i, line in enumerate(f_in, 1):
            # if i > 20:  # Only process first 5 lines
            #     break
                
            line = line.strip()
            if not line:
                continue
                
            logger.info(f"Processing line {i} from {input_file}")
            processed_data = process_jsonl_line(line, translator)
            if processed_data:
                f_out.write(json.dumps(processed_data, ensure_ascii=False) + '\n')
                processed_count += 1
                logger.info(f"Completed line {i} from {input_file}")
    
    return processed_count

def translate_all_content(input_dir: str = "input", output_dir: str = "output", model_name: str = "Qwen/Qwen3-8B"):
    """Process all JSONL files in the input directory and save translations to output directory."""
    # Create output directory if it doesn't exist
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    
    print("[TIMER] Starting model/tokenizer loading...")
    t0 = time.time()
    model, tokenizer = get_model_and_tokenizer(model_name)
    print(f"[TIMER] Model/tokenizer loaded in {time.time() - t0:.2f} seconds.")

    print("[TIMER] Moving model to device...")
    t1 = time.time()
    model = model.to(device)
    print(f"[TIMER] Model moved to device in {time.time() - t1:.2f} seconds.")

    print("[TIMER] Initializing LocalTranslator...")
    t2 = time.time()
    translator = LocalTranslator(model, tokenizer)
    print(f"[TIMER] LocalTranslator initialized in {time.time() - t2:.2f} seconds.")
    
    # Define input/output file pairs
    file_pairs = [
        ("text_blocks.jsonl", "translated_text_blocks.jsonl"),
        ("tables_full.jsonl", "translated_tables_full.jsonl"),
        ("chart_titles.jsonl", "translated_chart_titles.jsonl")
    ]
    
    total_processed = 0
    start_time = time.time()
    print("[TIMER] Starting translation loop...")
    
    # Process each file pair
    for input_file, output_file in file_pairs:
        input_path = f"{input_dir}/{input_file}"
        output_path = f"{output_dir}/{output_file}"
        
        if not Path(input_path).exists():
            logger.warning(f"Input file not found: {input_path}")
            continue
            
        logger.info(f"Processing {input_file}...")
        processed = process_file(input_path, output_path, translator)
        total_processed += processed
        logger.info(f"Completed {input_file}: {processed} items translated")
    
    end_time = time.time()
    print(f"[TIMER] Translation loop finished in {end_time - start_time:.2f} seconds.")
    logger.info(f"Translation complete!")
    logger.info(f"Total items translated: {total_processed}")
    logger.info(f"Time taken: {end_time - start_time:.2f} seconds")

def main():
    """Main function to run the translation process."""
    start_time = time.time()
    translate_all_content()
    end_time = time.time()
    logger.info(f"Translation complete!")
    logger.info(f"Time taken: {end_time - start_time:.2f} seconds")

if __name__ == "__main__":
    main() 