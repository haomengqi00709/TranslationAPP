import threading
from transformers import AutoModelForCausalLM, AutoTokenizer
import logging
import torch

logger = logging.getLogger(__name__)

# Dictionary to cache loaded models and tokenizers
_model_cache = {}
_tokenizer_cache = {}
_lock = threading.Lock()

if torch.cuda.is_available():
    device = "cuda"
elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
    device = "mps"
else:
    device = "cpu"

def get_model_and_tokenizer(model_name="Qwen/Qwen3-8B", device="cpu"):
    """
    Load and cache the model and tokenizer for the given model_name.
    Returns (model, tokenizer).
    Thread-safe and extensible for future model types.
    """
    with _lock:
        if model_name in _model_cache and model_name in _tokenizer_cache:
            logger.info(f"Returning cached model and tokenizer for {model_name}")
            return _model_cache[model_name], _tokenizer_cache[model_name]
        logger.info(f"Loading model and tokenizer for {model_name}")
        tokenizer = AutoTokenizer.from_pretrained(model_name)
        model = AutoModelForCausalLM.from_pretrained(
            model_name,
            torch_dtype=torch.float16,
            device_map=device  # or 'auto'
        )
        logger.info("Moving model to device...")
        model = model.to(device)
        logger.info("Model moved to device.")
        _model_cache[model_name] = model
        _tokenizer_cache[model_name] = tokenizer
        return model, tokenizer

# Example for future extension:
# def get_model_and_tokenizer(model_name="Qwen/Qwen3-8B", backend="hf"):
#     if backend == "vllm":
#         ... # logic for vLLM
#     elif backend == "hf":
#         ... # as above 