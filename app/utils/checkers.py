import json
import re


def validate_translation(translated_chunk: dict, original_chunk: dict) -> tuple[bool, str]:
    """
    Проверяет переведенный чанк на валидность.
    Возвращает (True, "OK") если всё хорошо, или (False, "Причина ошибки").
    """
    
    # 1. Проверка совпадения ключей
    if set(translated_chunk.keys()) != set(original_chunk.keys()):
        return False, "Несовпадение ключей (ИИ потеряла или добавила строки)"

    # Регулярка для поиска иероглифов (Китайский, Японский, Корейский)
    cjk_pattern = re.compile(r'[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]')

    for key, trans_text in translated_chunk.items():
        orig_text = original_chunk.get(key, "")
        
        # Если ИИ вернула не строку (например, число или null) - это ошибка
        if not isinstance(trans_text, str):
            return False, f"Значение ключа {key} не является строкой"
            
        # 2. Проверка на китайский/японский/корейский
        # (Проверяем только если в оригинале их не было)
        if cjk_pattern.search(trans_text) and not cjk_pattern.search(orig_text):
            return False, f"Обнаружены иероглифы в переводе (Ключ: {key})"

        # 3. Проверка сохранности переменных (Placeholders)
        # Ищем всё, что похоже на переменные: %s, %d, {name}, {0}, §a
        var_pattern = re.compile(r'(%[sd]|\{\w+\}|§[a-zA-Z0-9])')
        
        orig_vars = var_pattern.findall(orig_text)
        trans_vars = var_pattern.findall(trans_text)
        
        # Если наборы переменных не совпадают — ИИ сломала код
        if sorted(orig_vars) != sorted(trans_vars):
            return False, f"Потеряны или изменены переменные (Ключ: {key}). Ожидалось: {orig_vars}, Получено: {trans_vars}"

    # Если все проверки пройдены
    return True, "OK"

def extract_secure_entities(text_chunk: dict, glossary_data: dict = None) -> list[str]:
    """
    Собирает 100% безопасный список сущностей для транслитерации.
    Не трогает обычные слова с большой буквы, перекладывая их на контекст ИИ.
    """
    entities = set()
    
    # 1. Забираем проверенные имена из глоссария (если он передан)
    if glossary_data:
        for key in glossary_data.keys():
            if key and isinstance(key, str) and key[0].isupper():
                entities.add(key.strip())
                
    # 2. Вытаскиваем только ЖЕСТКИЕ маркеры игрового лора из текста
    for text in text_chunk.values():
        if not isinstance(text, str):
            continue
            
        # Паттерн А: Слова в кавычках (например, Sword of "Frostmourne")
        quoted = re.findall(r'["\'«]([A-Z][a-zA-Z]+)["\'»]', text)
        entities.update(quoted)
        
        # Паттерн Б: Имена перед апострофом (например, Bjorn's Axe)
        apostrophe = re.findall(r'\b([A-Z][a-z]+)\'s\b', text)
        entities.update(apostrophe)
        
        # Паттерн В: CamelCase внутри слова (например, ShadowFiend, StormBreaker)
        # Обычные слова английского языка так никогда не пишутся
        camel_case = re.findall(r'\b[A-Z][a-z]+[A-Z][a-zA-Z]+\b', text)
        entities.update(camel_case)

    return list(entities)

def debug_ollama_response(text: str, chunk_num: int = 0):
    """
    Выводит в консоль сырой ответ от Ollama для отладки.
    """
    print("\n" + "="*60)
    print(f"🔍 [ОТЛАДКА ЧАНК {chunk_num}] Сырой ответ от Ollama:")
    print(f"📏 Длина текста: {len(text)} символов")
    
    if not text:
        print("❌ ОТВЕТ ПУСТОЙ!")
    elif "<think>" in text:
        print("⚠️ ВНИМАНИЕ: В ответе есть теги <think>!")
        
    print(f"📄 Текст:\n{'-'*60}")
    print(text)
    print("-"*60 + "\n")

def debug_ollama_request(system_prompt: str, user_content: dict, chunk_num: int = 0):
    print("\n" + "="*60)
    print(f"📤 [ОТПРАВКА В OLLAMA] Чанк {chunk_num}")
    print(f"📄 SYSTEM PROMPT (последние 200 символов):\n...{system_prompt[-200:]}")
    print(f"📄 USER CONTENT (что переводим):\n{json.dumps(user_content, ensure_ascii=False, indent=2)}")
    print("="*60 + "\n")