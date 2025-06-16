import logging
import os
import time
from pathlib import Path
from .extract_all import ContentExtractor
from .translate_all import translate_all_content
from .rag_process import process_content_with_rag
from .update_pptx import update_pptx
from .layout_manager import process_text_layout, process_table_layout, process_chart_layout, apply_layout_adjustments
from pptx import Presentation
import json

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def run_pipeline(
    input_pptx: str,
    output_pptx: str,
    glossary_file: str,
    model_path: str = "Qwen/Qwen3-8B",
    apply_layout: bool = False,
    progress_callback=None
):
    """
    Run the complete translation pipeline.
    
    Args:
        input_pptx (str): Path to input English PowerPoint file
        output_pptx (str): Path to output French PowerPoint file
        glossary_file (str): Path to glossary file for RAG terms
        model_path (str): Path to translation model
        apply_layout (bool): Whether to apply layout adjustments
        progress_callback (callable): Optional callback function for progress updates
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
        if progress_callback:
            progress_callback(1)
            
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
        if progress_callback:
            progress_callback(2)
            
        translate_all_content(
            input_dir="input",
            output_dir="output",
            model_name=model_path
        )
        
        # Step 3: Process with RAG
        logger.info("Step 3: Processing with RAG")
        if progress_callback:
            progress_callback(3)
            
        process_content_with_rag(
            input_dir="input",
            output_dir="output",
            glossary_file=glossary_file,
            model_name=model_path
        )
        
        # Step 4: Update PowerPoint with translations
        logger.info("Step 4: Updating PowerPoint with translations")
        if progress_callback:
            progress_callback(4)
            
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
            if progress_callback:
                progress_callback(5)
                
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
    input_pptx = "translatorAPP/slides/PPT-3-Government-in-Canada1 (2).pptx"
    output_pptx = "translatorAPP/Output_ppt/PPT-3-Government-in-Canada1 (1)_fr_new.pptx"
    glossary_file = "translatorAPP/glossaryfile/glossary.jsonl"
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