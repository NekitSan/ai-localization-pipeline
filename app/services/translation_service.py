import json

import requests

from app.utils import (
    extract_secure_entities,
    filter_glossary,
    validate_translation,
)


def translate_chunk(
    model_name: str,
    ollama_url: str,
    system_prompt: str,
    local_chunk: dict,
    glossary_data: dict,
    payload_options: dict,
    timeout: int,
    keep_alive: int = 0
):
    attempt = 1
    last_error = ""

    # 1. Собираем текст чанка
    chunk_text = " ".join(str(v) for v in local_chunk.values())
    
    # 2. Фильтруем глоссарий (вызов утилиты)
    relevant_glossary = filter_glossary(glossary_data, chunk_text)

    while attempt <= 3:
        try:
            # 3. Извлекаем сущности (только из отфильтрованного глоссария)
            secure_entities = extract_secure_entities(local_chunk, relevant_glossary)

            # 4. Формируем промпт
            current_prompt = system_prompt
            
            if relevant_glossary:
                current_prompt += f"\n\nCRITICAL GLOSSARY (use exactly these terms):\n{json.dumps(relevant_glossary, ensure_ascii=False)}"
                
            if secure_entities:
                entities_str = ", ".join(secure_entities)
                current_prompt += f"\n\nCRITICAL: Transliterate these words: {entities_str}."

            # 5. Payload
            payload = {
                "model": model_name,
                "messages": [
                    {"role": "system", "content": current_prompt},
                    {"role": "user", "content": json.dumps(local_chunk, ensure_ascii=False)}
                ],
                "stream": False,
                "format": "json",
                "options": payload_options,
                "keep_alive": keep_alive
            }

            # ... (дальше отправка и парсинг как было)
            res = requests.post(ollama_url, json=payload, timeout=timeout)
            
            if res.status_code != 200:
                last_error = f"HTTP {res.status_code}"
                attempt += 1
                continue

            ai_text = res.json().get("message", {}).get("content", "").strip()
            
            if not ai_text:
                last_error = "Пустой ответ от модели"
                attempt += 1
                continue

            clean_text = ai_text.strip("\ufeff\xa0\x00 \n\r\t")
            s, e = clean_text.find("{"), clean_text.rfind("}")

            if s == -1 or e == -1:
                last_error = "В ответе нет JSON-скобок"
                attempt += 1
                continue

            try:
                chunk_res = json.loads(clean_text[s:e+1])
            except json.JSONDecodeError as je:
                last_error = f"Ошибка парсинга JSON: {je}"
                attempt += 1
                continue

            is_valid, error_msg = validate_translation(chunk_res, local_chunk)
            
            if is_valid:
                return True, chunk_res, "OK"
            else:
                last_error = error_msg
                print(f"⚠️ [Попытка {attempt}/3] {error_msg}")
                attempt += 1

        except Exception as e:
            last_error = str(e)
            print(f"❌ [Попытка {attempt}/3] Ошибка: {e}")
            attempt += 1

    return False, {}, f"Не удалось перевести чанк после 3 попыток. Последняя ошибка: {last_error}"