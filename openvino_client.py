"""
OpenVINO GenAI клиент для инференса на CPU/iGPU.
Совместим по API с ollama_client.py.
"""

import os
import sys
from typing import Optional

from config import OPENVINO_MODEL_DIR, OPENVINO_DEVICE

_generator = None


def _detect_device():
    """Определяет лучшее доступное устройство (GPU > CPU)."""
    try:
        import openvino as ov
        core = ov.Core()
        devices = core.available_devices
        print(f"🖥️  Доступные устройства: {devices}")
        if "GPU" in devices:
            print("✅ iGPU доступен! Используем GPU.")
            return "GPU"
        print("⚠️  iGPU не доступен. Используем CPU.")
        return "CPU"
    except Exception:
        return "CPU"


def _load_model():
    global _generator
    if _generator is not None:
        return _generator

    import openvino_genai as ov_genai
    import openvino as ov

    model_path = OPENVINO_MODEL_DIR
    device = _detect_device()

    print(f"🔄 Загружаю модель на {device}...")

    if not os.path.exists(model_path):
        print(f"📥 Конвертирую модель (первый запуск, ~5 минут)...")
        from optimum.intel import OVModelForCausalLM
        from transformers import AutoTokenizer

        hf_token = os.environ.get("HF_TOKEN")
        model = OVModelForCausalLM.from_pretrained(
            "Qwen/Qwen2.5-7B-Instruct",
            export=True,
            device=device,
            load_in_4bit=True,
            dtype="auto",
            token=hf_token
        )
        model.save_pretrained(model_path)
        tokenizer = AutoTokenizer.from_pretrained(
            "Qwen/Qwen2.5-7B-Instruct",
            token=hf_token
        )
        tokenizer.save_pretrained(model_path)

        tok_path = os.path.join(model_path, "openvino_tokenizer.xml")
        if not os.path.exists(tok_path):
            from openvino_tokenizers import convert_tokenizer
            ov_tokenizer, ov_detokenizer = convert_tokenizer(tokenizer, with_detokenizer=True)
            ov.save_model(ov_tokenizer, tok_path)
            ov.save_model(ov_detokenizer, os.path.join(model_path, "openvino_detokenizer.xml"))

        print(f"✅ Модель сохранена в {model_path}")

    tok_path = os.path.join(model_path, "openvino_tokenizer.xml")
    if not os.path.exists(tok_path):
        print("📥 Конвертирую токенизатор в OpenVINO IR формат...")
        from transformers import AutoTokenizer
        from openvino_tokenizers import convert_tokenizer
        tokenizer = AutoTokenizer.from_pretrained(model_path)
        ov_tokenizer, ov_detokenizer = convert_tokenizer(tokenizer, with_detokenizer=True)
        ov.save_model(ov_tokenizer, tok_path)
        ov.save_model(ov_detokenizer, os.path.join(model_path, "openvino_detokenizer.xml"))
        print("✅ Токенизатор сконвертирован")

    cache_dir = os.path.join(os.path.dirname(model_path), "ov_cache")
    os.makedirs(cache_dir, exist_ok=True)

    core = ov.Core()
    core.set_property({"CACHE_DIR": cache_dir})
    core.set_property(device, {
        "PERFORMANCE_HINT": "LATENCY",
        "NUM_STREAMS": "1"
    })

    _generator = ov_genai.LLMPipeline(model_path, device)
    print(f"✅ Модель загружена на {device}")
    return _generator


def query_openvino(system_prompt: str, user_content: str,
                   temperature: float = 0.0) -> Optional[str]:
    """
    Отправляет запрос к OpenVINO модели и возвращает ответ.
    """
    generator = _load_model()

    from transformers import AutoTokenizer
    tok = AutoTokenizer.from_pretrained(OPENVINO_MODEL_DIR)
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content}
    ]
    prompt = tok.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)

    try:
        import openvino_genai as ov_genai
        gen_config = ov_genai.GenerationConfig()
        gen_config.max_new_tokens = 2048
        gen_config.temperature = temperature

        result = generator.generate(prompt, gen_config)
        return result.text.strip() if hasattr(result, 'text') else str(result).strip()
    except Exception as e:
        print(f" ❌ OpenVINO ошибка: {e}")
        return None
