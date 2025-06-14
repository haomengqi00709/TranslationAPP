import json
import logging
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer
from typing import Dict, Any, List, Tuple
import time
from pathlib import Path
import shutil

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Check for MPS availability
device = "mps" if torch.backends.mps.is_available() else "cpu"
logger.info(f"Using device: {device}")

def load_rag_terms_list(jsonl_path: str) -> List[Tuple[str, str]]:
    """Load RAG terms from a JSONL file as a list of (en, fr) tuples."""
    rag_terms = []
    with open(jsonl_path, 'r', encoding='utf-8') as f:
        for line in f:
            entry = json.loads(line)
            rag_terms.append((entry['en'], entry['fr']))
    return rag_terms

def find_terms_in_text(text: str, rag_terms: List[Tuple[str, str]]) -> List[Tuple[str, str]]:
    """Return a list of (en, fr) pairs found in the text."""
    found = []
    for en, fr in rag_terms:
        if en in text:
            found.append((en, fr))
    return found

def build_focused_rag_context(found_terms: List[Tuple[str, str]]) -> str:
    if not found_terms:
        return ""
    lines = [
        "IMPORTANT: For the following English terms, ALWAYS use the exact French translation provided below:"
    ]
    for en, fr in found_terms:
        lines.append(f"- {en} = {fr}")
    lines.append("If you see these terms (even in parentheses or as acronyms), you MUST use the French version above.")
    return "\n".join(lines)

class LocalTranslator:
    def __init__(self, model_name: str = "Qwen/Qwen3-8B"):
        logger.info(f"Loading model: {model_name}")
        self.tokenizer = AutoTokenizer.from_pretrained(model_name)
        self.model = AutoModelForCausalLM.from_pretrained(
            model_name,
            torch_dtype=torch.float16,
            device_map=device
        )
        logger.info("Model loaded successfully")

    def translate(self, text: str, rag_context: str = None) -> str:
        try:
            if rag_context:
                system_content = (
                    f"{rag_context}\n"
                    "You are a professional translator. Use the provided French translations for the listed English terms. Only output the French translation."
                )
            else:
                system_content = (
                    "You are a professional translator. Only output the French translation."
                )
            messages = [
                {"role": "system", "content": system_content},
                {"role": "user", "content": text}
            ]
            prompt = self.tokenizer.apply_chat_template(
                messages,
                tokenize=False,
                add_generation_prompt=True,
                enable_thinking=False
            )
            inputs = self.tokenizer(prompt, return_tensors="pt").to(self.model.device)
            with torch.no_grad():
                outputs = self.model.generate(
                    **inputs,
                    max_new_tokens=200,
                    temperature=0.8,
                    top_p=0.95,
                    top_k=20,
                    min_p=0,
                    do_sample=True
                )
            translation = self.tokenizer.decode(outputs[0], skip_special_tokens=True)
            translation = translation.split("assistant")[-1].strip()
            translation = translation.replace("<think>", "")
            translation = translation.replace("</think>", "")
            translation = translation.replace("\n\n", " ").strip()
            return translation
        except Exception as e:
            logger.error(f"Translation error: {str(e)}")
            return text

def filter_lines_by_glossary(input_file: str, glossary_file: str, filtered_output_file: str):
    """Extract lines from input_file where the English text contains any glossary term."""
    rag_terms = load_rag_terms_list(glossary_file)
    found_count = 0
    with open(input_file, 'r', encoding='utf-8') as f_in, \
         open(filtered_output_file, 'w', encoding='utf-8') as f_out:
        for i, line in enumerate(f_in, 1):
            # if i > 20:  # Only process first 20 lines
            #     break
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                
                # Handle tables_full.jsonl structure
                if 'data' in data:  # This is a table structure
                    has_rag_terms = False
                    for row in data['data']:
                        for cell in row:
                            for para in cell.get('paragraphs', []):
                                for run in para.get('runs', []):
                                    english_text = run.get('text', '')
                                    found_terms = find_terms_in_text(english_text, rag_terms)
                                    if found_terms:
                                        has_rag_terms = True
                                        break
                    if has_rag_terms:
                        f_out.write(json.dumps(data, ensure_ascii=False) + '\n')
                        found_count += 1
                else:  # Regular text block or chart
                    english_text = data.get('text', '')
                    found_terms = find_terms_in_text(english_text, rag_terms)
                    if found_terms:
                        f_out.write(json.dumps(data, ensure_ascii=False) + '\n')
                        found_count += 1
            except Exception as e:
                logger.error(f"Error processing line {i}: {str(e)}")
                continue
    logger.info(f"Extracted {found_count} lines containing RAG terms to {filtered_output_file}")

def translate_filtered_lines(filtered_input_file: str, glossary_file: str, output_file: str, model_name: str = "Qwen/Qwen3-8B"):
    """Translate only the filtered lines using focused RAG context."""
    rag_terms = load_rag_terms_list(glossary_file)
    translator = LocalTranslator(model_name)
    with open(filtered_input_file, 'r', encoding='utf-8') as f_in, \
         open(output_file, 'w', encoding='utf-8') as f_out:
        for i, line in enumerate(f_in, 1):
            # if i > 20:  # Only process first 20 lines
            #     break
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                
                # Handle tables_full.jsonl structure
                if 'data' in data:  # This is a table structure
                    for row in data['data']:
                        for cell in row:
                            for para in cell.get('paragraphs', []):
                                for run in para.get('runs', []):
                                    english_text = run.get('text', '')
                                    found_terms = find_terms_in_text(english_text, rag_terms)
                                    if found_terms:
                                        rag_context = build_focused_rag_context(found_terms)
                                        if isinstance(run.get('french_text'), str):
                                            run['french_text'] = translator.translate(english_text, rag_context=rag_context)
                else:  # Regular text block or chart
                    english_text = data.get('text', '')
                    found_terms = find_terms_in_text(english_text, rag_terms)
                    if found_terms:
                        rag_context = build_focused_rag_context(found_terms)
                        if isinstance(data.get('french_text'), str):
                            data['french_text'] = translator.translate(english_text, rag_context=rag_context)
                
                f_out.write(json.dumps(data, ensure_ascii=False) + '\n')
                logger.info(f"Translated line {i}")
            except Exception as e:
                logger.error(f"Error processing line {i}: {str(e)}")
                continue
    logger.info(f"Translation complete. Output written to {output_file}")

def merge_focused_rag_translations(master_file: str, focused_rag_file: str, output_file: str):
    """Merge translations from focused RAG file into the master file."""
    # Load translations from focused RAG file
    translations = {}
    with open(focused_rag_file, 'r', encoding='utf-8') as f:
        for i, line in enumerate(f, 1):
            # if i > 20:  # Only process first 20 lines
            #     break
            try:
                data = json.loads(line)
                
                # Handle different content types
                if 'data' in data:  # Tables
                    for row in data['data']:
                        for cell in row:
                            for para in cell.get('paragraphs', []):
                                for run in para.get('runs', []):
                                    if 'run_idx' in run and 'french_text' in run:
                                        translations[run['run_idx']] = run['french_text']
                else:  # Text blocks and charts
                    if 'french_text' in data:
                        key = (
                            data.get('slide_index'),
                            data.get('shape_index'),
                            data.get('paragraph_index', 0),
                            data.get('run_index', 0)
                        )
                        translations[key] = data['french_text']
            except Exception as e:
                logger.error(f"Error processing line {i} from RAG file: {str(e)}")
                continue
    
    logger.info(f"Loaded {len(translations)} translations from focused RAG file")
    
    # Process master file and update translations
    with open(master_file, 'r', encoding='utf-8') as f_in, \
         open(output_file, 'w', encoding='utf-8') as f_out:
        
        for i, line in enumerate(f_in, 1):
            # if i > 20:  # Only process first 20 lines
            #     break
            try:
                data = json.loads(line)
                updated = False
                
                # Handle different content types
                if 'data' in data:  # Tables
                    for row in data['data']:
                        for cell in row:
                            for para in cell.get('paragraphs', []):
                                for run in para.get('runs', []):
                                    run_idx = run.get('run_idx')
                                    if run_idx in translations:
                                        run['french_text'] = translations[run_idx]
                                        updated = True
                else:  # Text blocks and charts
                    key = (
                        data.get('slide_index'),
                        data.get('shape_index'),
                        data.get('paragraph_index', 0),
                        data.get('run_index', 0)
                    )
                    if key in translations:
                        data['french_text'] = translations[key]
                        updated = True
                
                f_out.write(json.dumps(data, ensure_ascii=False) + '\n')
                if updated:
                    logger.info(f"Updated translations in item {i}")
                else:
                    logger.info(f"No updates needed for item {i}")
                
            except Exception as e:
                logger.error(f"Error processing line {i} from master file: {str(e)}")
                continue
    
    logger.info(f"Merge complete. Output written to {output_file}")

def process_content_with_rag(
    input_dir: str = "input",
    output_dir: str = "output",
    glossary_file: str = "glossaryfile/glossary.jsonl",
    model_name: str = "Qwen/Qwen3-8B"
):
    """Process all content types with RAG."""
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    
    # Process each content type
    content_types = [
        ("output/translated_text_blocks.jsonl", "text_blocks_with_rag_terms.jsonl", "translated_text_blocks_with_rag.jsonl", "merged_text_blocks.jsonl"),
        ("output/translated_tables_full.jsonl", "tables_with_rag_terms.jsonl", "translated_tables_with_rag.jsonl", "merged_tables_with_translations.jsonl"),
        ("output/translated_chart_titles.jsonl", "charts_with_rag_terms.jsonl", "translated_charts_with_rag.jsonl", "merged_chart_titles.jsonl")
    ]
    
    start_time = time.time()
    has_items_to_process = False
    
    # First pass: Filter lines and check if we have any items to process
    for input_file, filtered_file, translated_file, merged_file in content_types:
        input_path = input_file  # No need to join with input_dir since we're using full paths
        if not Path(input_path).exists():
            logger.warning(f"Input file not found: {input_path}")
            continue
            
        logger.info(f"Processing {input_file}...")
        
        # Step 1: Filter lines with RAG terms
        filter_lines_by_glossary(
            input_file=input_path,
            glossary_file=glossary_file,
            filtered_output_file=f"{output_dir}/{filtered_file}"
        )
        
        # Check if the filtered file has any content
        filtered_path = f"{output_dir}/{filtered_file}"
        if Path(filtered_path).exists() and Path(filtered_path).stat().st_size > 0:
            has_items_to_process = True
            logger.info(f"Found items to process in {filtered_file}")
    
    if not has_items_to_process:
        logger.info("No items found requiring RAG processing. Skipping model loading.")
        # Copy original files to merged files
        for input_file, filtered_file, translated_file, merged_file in content_types:
            input_path = input_file
            if Path(input_path).exists():
                shutil.copy2(input_path, f"{output_dir}/{merged_file}")
                logger.info(f"Copied {input_file} to {merged_file}")
        return
    
    # Second pass: Process items if we found any
    logger.info("Found items requiring RAG processing. Loading model...")
    translator = LocalTranslator(model_name)
    
    for input_file, filtered_file, translated_file, merged_file in content_types:
        input_path = input_file
        filtered_path = f"{output_dir}/{filtered_file}"
        
        if not Path(input_path).exists() or not Path(filtered_path).exists():
            continue
            
        if Path(filtered_path).stat().st_size == 0:
            logger.info(f"No items to process in {filtered_file}, copying original file")
            shutil.copy2(input_path, f"{output_dir}/{merged_file}")
            continue
            
        logger.info(f"Processing items in {filtered_file}...")
        
        # Step 2: Translate filtered lines
        translate_filtered_lines(
            filtered_input_file=filtered_path,
            glossary_file=glossary_file,
            output_file=f"{output_dir}/{translated_file}",
            model_name=model_name
        )
        
        # Step 3: Merge translations back
        merge_focused_rag_translations(
            master_file=input_path,
            focused_rag_file=f"{output_dir}/{translated_file}",
            output_file=f"{output_dir}/{merged_file}"
        )
    
    end_time = time.time()
    logger.info(f"RAG processing complete!")
    logger.info(f"Time taken: {end_time - start_time:.2f} seconds")

def main():
    """Main function to run the RAG process."""
    process_content_with_rag(
        input_dir="input",
        output_dir="output",
        glossary_file="/Users/jasonhao/Desktop/LLM experiments/translatedocs/forst/glossoryfile/glossory.jsonl",
        model_name="Qwen/Qwen3-8B"
    )

if __name__ == "__main__":
    main() 