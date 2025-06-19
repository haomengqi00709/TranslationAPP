import logging
import os
import time
from pathlib import Path
from Backend.extract_all import ContentExtractor
from Backend.translate_all import translate_all_content
from Backend.rag_process import process_content_with_rag
from Backend.update_pptx import update_pptx
from Backend.layout_manager import process_text_layout, process_table_layout, process_chart_layout, apply_layout_adjustments
from pptx import Presentation
import json
import re



# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def preserve_special_chars(input_dir: str, output_dir: str):
    """
    Preserve special characters (spaces, quotes, punctuation, etc.) at the start and end of translations.
    Also ensure the first non-special character's capitalization matches the original.
    """
    logger.info("Preserving special characters in translations")
    
    # Helper to extract leading/trailing special chars
    def get_leading_trailing_specials(text):
        leading = re.match(r'^[^\w\d]+', text)
        trailing = re.search(r'[^\w\d]+$', text)
        return (leading.group(0) if leading else '', trailing.group(0) if trailing else '')

    # Helper to match capitalization of first non-special char
    def match_first_capitalization(original, translated):
        # Remove leading specials
        lead_orig = re.match(r'^[^\w\d]+', original)
        lead_tran = re.match(r'^[^\w\d]+', translated)
        orig_body = original[len(lead_orig.group(0)):] if lead_orig else original
        tran_body = translated[len(lead_tran.group(0)):] if lead_tran else translated
        if not orig_body or not tran_body:
            return translated  # Nothing to do
        orig_first = orig_body[0]
        tran_first = tran_body[0]
        # If original is upper and translation is not, capitalize
        if orig_first.isupper() and not tran_first.isupper():
            tran_body = tran_body[0].upper() + tran_body[1:]
        # If original is lower and translation is not, lowercase
        elif orig_first.islower() and not tran_first.islower():
            tran_body = tran_body[0].lower() + tran_body[1:]
        # Recombine
        prefix = lead_tran.group(0) if lead_tran else ''
        return prefix + tran_body

    # Helper to preserve spaces, quotes, and colons at start and end
    def preserve_formatting(original, translated):
        """Ensure French translation has same leading/trailing spaces, quotes, and colons as English."""
        result = translated
        
        # Preserve leading space
        if original.startswith(' ') and not result.startswith(' '):
            result = ' ' + result
        
        # Preserve trailing space  
        if original.endswith(' ') and not result.endswith(' '):
            result = result + ' '
        
        # Preserve leading quote
        if original.startswith('"') and not result.startswith('"'):
            result = '"' + result
        
        # Preserve trailing quote
        if original.endswith('"') and not result.endswith('"'):
            result = result + '"'
        
        # Preserve leading colon
        if original.startswith(':') and not result.startswith(':'):
            result = ':' + result
        
        # Preserve trailing colon
        if original.endswith(':') and not result.endswith(':'):
            result = result + ':'
        
        return result

    # Process each JSONL file
    for filename in ["merged_text_blocks.jsonl", "merged_tables_with_translations.jsonl", "merged_chart_titles.jsonl"]:
        input_path = f"{input_dir}/{filename}"
        output_path = f"{output_dir}/{filename}"
        
        logger.info(f"Processing file: {input_path}")
        
        if not Path(input_path).exists():
            logger.error(f"Input file not found: {input_path}")
            continue
            
        processed_items = []
        modified_count = 0
        
        try:
            with open(input_path, 'r', encoding='utf-8') as f:
                for line_num, line in enumerate(f, 1):
                    try:
                        item = json.loads(line)
                        
                        # Handle different file structures
                        if 'data' in item:  # This is a table structure
                            for row in item['data']:
                                for cell in row:
                                    for para in cell.get('paragraphs', []):
                                        for run in para.get('runs', []):
                                            if 'text' in run and 'french_text' in run:
                                                original = run['text']
                                                translated = run['french_text']
                                                if not translated:
                                                    continue
                                                original_translation = translated
                                                # Use the improved special character handling
                                                translated = preserve_formatting(original, translated)
                                                # Match capitalization
                                                translated = match_first_capitalization(original, translated)
                                                if translated != original_translation:
                                                    run['french_text'] = translated
                                                    modified_count += 1
                        else:  # Regular text block or chart
                            if 'text' in item and 'french_text' in item:
                                original = item['text']
                                translated = item['french_text']
                                if not translated:
                                    continue
                                original_translation = translated
                                # Use the improved special character handling
                                translated = preserve_formatting(original, translated)
                                translated = match_first_capitalization(original, translated)
                                if translated != original_translation:
                                    item['french_text'] = translated
                                    modified_count += 1
                        processed_items.append(item)
                    except json.JSONDecodeError as e:
                        logger.error(f"Error decoding JSON at line {line_num}: {e}")
                        continue
            # Write processed items back to file
            with open(output_path, 'w', encoding='utf-8') as f:
                for item in processed_items:
                    f.write(json.dumps(item, ensure_ascii=False) + '\n')
            logger.info(f"✅ Processed {filename}: {modified_count} translations modified")
        except Exception as e:
            logger.error(f"Error processing {filename}: {str(e)}")
            continue

def run_pipeline(
    input_pptx: str,
    output_pptx: str,
    glossary_file: str,
    model_path: str = "Qwen/Qwen3-8B",
    apply_layout: bool = False
):
    """
    Run the complete translation pipeline.
    
    Args:
        input_pptx (str): Path to input English PowerPoint file
        output_pptx (str): Path to output French PowerPoint file
        glossary_file (str): Path to glossary file for RAG terms
        model_path (str): Path to translation model
        apply_layout (bool): Whether to apply layout adjustments
    """
    start_time = time.time()
    logger.info("Starting translation pipeline")
    
    # Create necessary directories
    os.makedirs("input", exist_ok=True)
    os.makedirs("output", exist_ok=True)
    os.makedirs("layout", exist_ok=True)
    
    try:
        # Step 1: Extract content from PowerPoint
        logger.info("Step 1: Extracting content from PowerPoint")
            
        extractor = ContentExtractor()
        extractor.extract_text_blocks(
            pptx_path=input_pptx,
            output_jsonl="input/text_blocks.jsonl"
        )
        extractor.extract_tables(
            pptx_path=input_pptx,
            full_output_jsonl="input/tables_full.jsonl",
            runs_output_jsonl="input/tables_runs.jsonl"
        )
        extractor.extract_chart_titles(
            pptx_path=input_pptx,
            output_jsonl="input/chart_titles.jsonl"
        )
        
        # Step 2: Translate content
        logger.info("Step 2: Translating content")
            
        translate_all_content(
            input_dir="input",
            output_dir="output",
            model_name=model_path
        )
        
        # Step 3: Process with RAG
        logger.info("Step 3: Processing with RAG")
            
        process_content_with_rag(
            input_dir="input",
            output_dir="output",
            glossary_file=glossary_file,
            model_name=model_path
        )
        
        # Step 3.5: Preserve special characters in translations
        logger.info("Step 3.5: Preserving special characters in translations")
            
        preserve_special_chars(
            input_dir="output",
            output_dir="output"
        )
        
        # Step 4: Update PowerPoint with translations
        logger.info("Step 4: Updating PowerPoint with translations")
            
        update_pptx(
            input_pptx=input_pptx,
            output_pptx=output_pptx,
            text_jsonl="output/merged_text_blocks.jsonl",
            tables_jsonl="output/merged_tables_with_translations.jsonl",
            charts_jsonl="output/merged_chart_titles.jsonl"
        )
        
        # Step 5: Apply layout adjustments (optional)
        if apply_layout:
            logger.info("Step 5: Applying layout adjustments")
                
            # Process English presentation
            eng_prs = Presentation(input_pptx)
            eng_text_results = process_text_layout(eng_prs, "en")
            eng_table_results = process_table_layout(eng_prs, "en")
            eng_chart_details = process_chart_layout(eng_prs)
            
            # Process French presentation
            fr_prs = Presentation(output_pptx)
            fr_text_results = process_text_layout(fr_prs, "fr", eng_text_results)
            fr_table_results = process_table_layout(fr_prs, "fr", eng_table_results)
            fr_chart_details = process_chart_layout(fr_prs)
            
            # Save layout results
            with open("layout/text_layout.jsonl", "w", encoding="utf-8") as f:
                for key in eng_text_results:
                    if key in fr_text_results:
                        f.write(json.dumps(eng_text_results[key], ensure_ascii=False) + "\n")
                        f.write(json.dumps(fr_text_results[key], ensure_ascii=False) + "\n")
            
            with open("layout/table_layout.jsonl", "w", encoding="utf-8") as f:
                for eng_table, fr_table in zip(eng_table_results, fr_table_results):
                    f.write(json.dumps(eng_table, ensure_ascii=False) + "\n")
                    f.write(json.dumps(fr_table, ensure_ascii=False) + "\n")
            
            with open("layout/chart_layout.json", "w", encoding="utf-8") as f:
                json.dump({
                    "english": eng_chart_details,
                    "french": fr_chart_details
                }, f, indent=2, ensure_ascii=False)
            
            # Apply adjustments to French presentation
            apply_layout_adjustments(fr_prs, fr_text_results, fr_table_results)
            
            # Save adjusted French presentation
            layout_output_pptx = output_pptx.replace(".pptx", "_layout.pptx")
            fr_prs.save(layout_output_pptx)
            logger.info(f"✅ Layout adjustments saved to {layout_output_pptx}")
        
        logger.info(f"Pipeline completed successfully in {time.time() - start_time:.2f} seconds")
        
    except Exception as e:
        logger.error(f"Pipeline failed: {str(e)}")
        raise

def main():
    # Define file paths
    input_pptx = "slides/PPT-3-Government-in-Canada1 (1).pptx"
    output_pptx = "Output_ppt/PPT-3-Government-in-Canada1 (1)_fr_new.pptx"
    glossary_file = "glossaryfile/glossary1.jsonl"
    model_path = "Qwen/Qwen3-8B"
    
    # Run pipeline
    run_pipeline(
        input_pptx=input_pptx,
        output_pptx=output_pptx,
        glossary_file=glossary_file,
        model_path=model_path,
        apply_layout=True  # Set to False to skip layout adjustments
    )

if __name__ == "__main__":
    main() 