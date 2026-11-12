import hashlib
import json
import os

import requests
from dotenv import load_dotenv
from flask import (
    Flask,
    Response,
    jsonify,
    request,
    send_from_directory,
    stream_with_context,
)

from app.utils import (
    GlossaryManager,
    debug_ollama_request,
    debug_ollama_response,
    extract_secure_entities,
    validate_translation,
)
from app.utils.prompt_manager import PromptBuilder  # <-- Импортируем твой билдер

load_dotenv()

app = Flask(__name__, static_folder='.')

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LLM_DIR = os.path.join(BASE_DIR, "llm")
TEMPS_DIR = os.path.join(LLM_DIR, "temps")
GLOSSARY_MGR = GlossaryManager(LLM_DIR)
PROMPT_BUILDER = PromptBuilder(os.path.join(LLM_DIR, "prompts"), GLOSSARY_MGR) 

CONFIG_PATH = os.path.join(LLM_DIR, "config.json")
if os.path.exists(CONFIG_PATH):
    with open(CONFIG_PATH, "r", encoding="utf-8") as f: config = json.load(f)
else: config = {}

STATUSES_PATH = os.path.join(LLM_DIR, "statuses.json")
if os.path.exists(STATUSES_PATH):
    with open(STATUSES_PATH, "r", encoding="utf-8-sig") as f: statuses = json.load(f)
else: statuses = {"START": "🚀", "MASK": "📖", "GLOSSARY": "🎯", "CHUNK_START": "🧠", "RETRY": "⚠️", "CHUNK_SUCCESS": "✅", "SUCCESS": "🎉", "ERROR": "❌"}

OLLAMA_API_URL = os.getenv("OLLAMA_API_URL", "http://localhost:11434/api/chat")
MODELS_RAW = os.getenv("MODELS", "deepseek-r1:14b")
MODEL_NAME = MODELS_RAW.split(",")[0].strip() if MODELS_RAW else "deepseek-r1:14b"

CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "12"))
TIMEOUT_SECONDS = int(os.getenv("TIMEOUT_SECONDS", "300"))

PAYLOAD_OPTIONS = {
    "temperature": config.get("temperature", 0.1),
    "num_predict": config.get("num_predict", 1024),
    "num_ctx": config.get("num_ctx", 2048)
}

@app.route('/')
def index():
    return send_from_directory('.', 'index.html')

@app.route('/api/compare', methods=['POST'])
def compare_translations():
    req_data = request.get_json()
    source_raw = req_data.get('source', '')
    target_raw = req_data.get('target', '')

    try:
        source = json.loads(source_raw) if source_raw else {}
        target = json.loads(target_raw) if target_raw else {}
        if not isinstance(source, dict) or not isinstance(target, dict):
            return jsonify({"success": False, "error": "JSON должен быть объектом"}), 400
    except json.JSONDecodeError:
        return jsonify({"success": False, "error": "Невалидный JSON"}), 400

    missing_keys = {k: v for k, v in source.items() if k not in target}
    extra_keys = {k: v for k, v in target.items() if k not in source}

    return jsonify({
        "success": True, "missing": missing_keys, "extra": extra_keys,
        "missing_count": len(missing_keys), "extra_count": len(extra_keys),
        "total_source": len(source)
    })

@app.route('/api/glossaries', methods=['GET'])
def get_glossaries():
    files = GLOSSARY_MGR.get_available_files()
    return jsonify({"success": True, **files})

@app.route('/api/translate-stream', methods=['POST'])
def translate_stream():
    req_data = request.get_json()
    file_format = req_data.get('format', 'json')
    raw_content = req_data.get('data', '').strip()
    selected_game = req_data.get('game')

    if not raw_content:
        return jsonify({"success": False, "error": "Пустой текст"}), 400

    os.makedirs(TEMPS_DIR, exist_ok=True)
    source_hash = hashlib.md5(raw_content.encode('utf-8')).hexdigest()
    cache_file = os.path.join(TEMPS_DIR, f"progress_{source_hash}.json")

    for f in [os.path.join(TEMPS_DIR, ".key_bridge_cache.json"), os.path.join(TEMPS_DIR, ".xml_template_cache")]:
        if os.path.exists(f): os.remove(f)

    def generate():
        yield f"data: {json.dumps({'type': 'log', 'text': statuses.get('START', '🚀')})}\n\n"
        
        # --- ПАРСИНГ ---
        original_map = {}
        if file_format == "json":
            try:
                raw_data = json.loads(raw_content)
                def flatten_json(y):
                    out = {}
                    def flatten(x, name=""):
                        if type(x) is dict:
                            for a in x: flatten(x[a], name + a + ".")
                        elif type(x) is list:
                            for i, a in enumerate(x): flatten(a, name + str(i) + ".")
                        else: out[name[:-1]] = str(x)
                    flatten(y)
                    return out
                if any(isinstance(v, dict) for v in raw_data.values()):
                    original_map = flatten_json(raw_data)
                    original_map["__META_NESTED__"] = "true"
                else:
                    original_map = {str(k): str(v) for k, v in raw_data.items() if v}
            except Exception:
                yield f"data: {json.dumps({'type': 'error', 'text': 'Ошибка синтаксиса JSON'})}\n\n"
                return
        elif file_format == "xml":
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(raw_content, "lxml-xml")
            for i, element in enumerate(soup.find_all(string=True)):
                text = element.strip()
                if text and not text.startswith("<?xml"):
                    original_map[f"xml_tag_{i}"] = text
                    element.replace_with(f"__TOKEN_xml_tag_{i}__")
            with open(os.path.join(TEMPS_DIR, ".xml_template_cache"), "w", encoding="utf-8") as f:
                f.write(str(soup))
        else:
            lines = raw_content.split("\n")
            for i, line in enumerate(lines):
                original_map[f"text_line_{i}"] = line

        ai_friendly_dict = {}
        key_bridge = {}
        is_nested_json = original_map.pop("__META_NESTED__", None) == "true"

        for idx, (orig_key, orig_text) in enumerate(original_map.items()):
            ai_key = f"text_{idx}"
            ai_friendly_dict[ai_key] = orig_text
            key_bridge[ai_key] = orig_key

        if file_format == "json" and is_nested_json: key_bridge["__META_NESTED__"] = "true"

        with open(os.path.join(TEMPS_DIR, ".key_bridge_cache.json"), "w", encoding="utf-8") as f:
            json.dump(key_bridge, f, ensure_ascii=False)

        yield f"data: {json.dumps({'type': 'log', 'text': statuses.get('MASK', '📖')})}\n\n"

        system_prompt = PROMPT_BUILDER.build(game_name=selected_game)
        glossary_data = GLOSSARY_MGR.load_layers(selected_game) # Для сущностей
        
        if glossary_data:
            yield f"data: {json.dumps({'type': 'log', 'text': f'🎯 Глоссарий подключен'})}\n\n"

        items = list(ai_friendly_dict.items())
        total_strings = len(items)
        if total_strings == 0:
            yield f"data: {json.dumps({'type': 'error', 'text': 'Нет строк для перевода'})}\n\n"
            return

        translated_ai_dict = {}
        if os.path.exists(cache_file):
            try:
                with open(cache_file, "r", encoding="utf-8") as f:
                    saved_data = json.load(f)
                    if saved_data.get("hash") == source_hash:
                        translated_ai_dict = saved_data.get("translated_data", {})
                        yield f"data: {json.dumps({'type': 'log', 'text': f'♻️ Прогресс: {len(translated_ai_dict)} строк'})}\n\n"
            except Exception as e:
                print(f"⚠️ [Кэш] Ошибка: {e}")

        # --- ЦИКЛ ПЕРЕВОДА ---
        try:
            while len(translated_ai_dict) < total_strings:
                already_count = len(translated_ai_dict)
                chunk_num = (already_count // CHUNK_SIZE) + 1
                start_idx = already_count
                end_idx = min(start_idx + CHUNK_SIZE, total_strings)

                global_chunk = dict(items[start_idx:end_idx])
                local_chunk = {f"text_{i}": v for i, v in enumerate(global_chunk.values())}
                local_to_global = {f"text_{i}": k for i, k in enumerate(global_chunk.keys())}

                yield f"data: {json.dumps({'type': 'log', 'text': statuses.get('CHUNK_START', '').format(chunk=chunk_num, count=len(local_chunk))})}\n\n"

                attempt = 1
                success = False
                chunk_res = {}

                while attempt <= 3 and not success:
                    try:
                        # 1. Извлекаем сущности
                        secure_entities = extract_secure_entities(local_chunk, glossary_data)
                        
                        # 2. Формируем user_content (только текст для перевода)
                        user_content = local_chunk

                        # 3. Формируем финальный промпт (добавляем сущности текстом)
                        current_prompt = system_prompt
                        if secure_entities:
                            entities_str = ", ".join(secure_entities)
                            current_prompt += f"\n\nCRITICAL: The following words MUST be transliterated (written by sound in Cyrillic), NOT translated: {entities_str}."

                        # 4. Payload
                        payload = {
                            "model": MODEL_NAME, 
                            "messages": [
                                {"role": "system", "content": current_prompt}, # <-- ТУТ
                                {"role": "user", "content": json.dumps(user_content, ensure_ascii=False)}
                            ], 
                            "stream": False,
                            "format": "json",
                            "options": PAYLOAD_OPTIONS,
                            "keep_alive": 0 
                        }

                        debug_ollama_request(system_prompt, user_content, chunk_num)

                        res = requests.post(OLLAMA_API_URL, json=payload, timeout=TIMEOUT_SECONDS)
                        if res.status_code != 200: attempt += 1; continue
                        
                        ai_text = res.json().get("message", {}).get("content", "").strip()
                        clean_text = ai_text.strip("\ufeff\xa0\x00 \n\r\t")
                        s, e = clean_text.find("{"), clean_text.rfind("}")
                        chunk_res = json.loads(clean_text[s:e+1] if s != -1 else clean_text)

                        raw_message = res.json().get("message", {})
                        ai_text = raw_message.get("content", "").strip()

                        # DEBUG
                        debug_ollama_response(ai_text, chunk_num)

                        # 4. ВАЛИДАЦИЯ
                        is_valid, error_msg = validate_translation(chunk_res, local_chunk)

                        if is_valid:
                            success = True
                        else:
                            yield f"data: {json.dumps({'type': 'log', 'text': f'⚠️ {error_msg}'})}\n\n"
                            attempt += 1
                            
                    except Exception as e:
                        print(f"❌ [Чанк {chunk_num}] {e}")
                        attempt += 1

                if not success:
                    yield f"data: {json.dumps({'type': 'error', 'text': f'Чанк {chunk_num} не прошел валидацию'})}\n\n"
                    return

                for l_k, text_val in chunk_res.items():
                    translated_ai_dict[local_to_global[l_k]] = text_val

                with open(cache_file, "w", encoding="utf-8") as f:
                    json.dump({"hash": source_hash, "translated_data": translated_ai_dict}, f, ensure_ascii=False)

                percent = int((len(translated_ai_dict) / total_strings) * 100)
                yield f"data: {json.dumps({'type': 'progress', 'current': len(translated_ai_dict), 'total': total_strings, 'percent': percent})}\n\n"
                yield f"data: {json.dumps({'type': 'log', 'text': statuses.get('CHUNK_SUCCESS', '').format(chunk=chunk_num)})}\n\n"

        except GeneratorExit:
            print(f"🛑 [Остановка] Сохранено: {len(translated_ai_dict)}")
            raise

        # --- СБОРКА РЕЗУЛЬТАТА ---
        with open(os.path.join(TEMPS_DIR, ".key_bridge_cache.json"), "r", encoding="utf-8") as f: key_bridge = json.load(f)
        is_nested_json = key_bridge.pop("__META_NESTED__", None) == "true"
        final_map = {key_bridge[k]: v for k, v in translated_ai_dict.items()}
        
        if file_format == "json":
            if is_nested_json:
                def unflatten(flat):
                    res = {}
                    for k, v in flat.items():
                        parts = k.split(".")
                        d = res
                        for p in parts[:-1]:
                            if p not in d: d[p] = {}
                            d = d[p]
                        d[parts[-1]] = v
                    return res
                out_data = unflatten(final_map)
            else: out_data = final_map
            final_text = json.dumps(out_data, ensure_ascii=False, indent=2)
        elif file_format == "xml":
            with open(os.path.join(TEMPS_DIR, ".xml_template_cache"), "r", encoding="utf-8") as f: result_xml = f.read()
            for k, v in final_map.items(): result_xml = result_xml.replace(f"__TOKEN_{k}__", v)
            final_text = result_xml
        else:
            sorted_lines = [final_map.get(f"text_line_{i}", "") for i in range(len(final_map))]
            final_text = "\n".join(sorted_lines)

        for f in [os.path.join(TEMPS_DIR, ".key_bridge_cache.json"), os.path.join(TEMPS_DIR, ".xml_template_cache")]:
            if os.path.exists(f): os.remove(f)
        if os.path.exists(cache_file): os.remove(cache_file)

        yield f"data: {json.dumps({'type': 'log', 'text': statuses.get('SUCCESS', '🎉')})}\n\n"
        yield f"data: {json.dumps({'type': 'done', 'result': final_text})}\n\n"

    return Response(stream_with_context(generate()), content_type='text/event-stream')

if __name__ == "__main__":
    print("🌐 Запуск локального сервера...")
    app.run(host="127.0.0.1", port=8000, debug=True)