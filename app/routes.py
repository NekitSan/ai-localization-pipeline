import hashlib
import json
import os

from flask import (
    Blueprint,
    Response,
    current_app,
    jsonify,
    request,
    send_from_directory,
    stream_with_context,
)

# Импорты сервисов
from app.services import parse_and_mask, translate_chunk

bp = Blueprint('main', __name__)

@bp.route('/')
def index():
    return send_from_directory(current_app.template_folder, 'index.html')

@bp.route('/api/compare', methods=['POST'])
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

@bp.route('/api/glossaries', methods=['GET'])
def get_glossaries():
    mgr = current_app.config['GLOSSARY_MGR']
    files = mgr.get_available_files()
    return jsonify({"success": True, **files})

@bp.route('/api/translate-stream', methods=['POST'])
def translate_stream():
    req_data = request.get_json()
    file_format = req_data.get('format', 'json')
    raw_content = req_data.get('data', '').strip()
    selected_game = req_data.get('game')

    if not raw_content:
        return jsonify({"success": False, "error": "Пустой текст"}), 400

    # Получаем конфиги из app.config
    cfg = current_app.config['APP_CONFIG']
    glossary_mgr = current_app.config['GLOSSARY_MGR']
    prompt_builder = current_app.config['PROMPT_BUILDER']
    
    # Пути
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    temps_dir = os.path.join(base_dir, "app", "llm", "temps")
    os.makedirs(temps_dir, exist_ok=True)

    source_hash = hashlib.md5(raw_content.encode('utf-8')).hexdigest()
    cache_file = os.path.join(temps_dir, f"progress_{source_hash}.json")

    for f in [os.path.join(temps_dir, ".key_bridge_cache.json"), os.path.join(temps_dir, ".xml_template_cache")]:
        if os.path.exists(f): os.remove(f)

    def generate():
        yield f"data: {json.dumps({'type': 'log', 'text': '🚀 Запуск конвейера...'})}\n\n"
        
        # Парсинг
        try:
            ai_friendly_dict, key_bridge, is_nested_json = parse_and_mask(raw_content, file_format, temps_dir)
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'text': f'Ошибка парсинга: {e}'})}\n\n"
            return

        if file_format == "json" and is_nested_json:
            key_bridge["__META_NESTED__"] = "true"

        with open(os.path.join(temps_dir, ".key_bridge_cache.json"), "w", encoding="utf-8") as f:
            json.dump(key_bridge, f, ensure_ascii=False)

        yield f"data: {json.dumps({'type': 'log', 'text': '📖 Структура изолирована'})}\n\n"

        # Промпт и глоссарий
        system_prompt = prompt_builder.build(game_name=selected_game)
        glossary_data = glossary_mgr.load_layers(selected_game)
        
        if glossary_data:
            yield f"data: {json.dumps({'type': 'log', 'text': '🎯 Глоссарий подключен'})}\n\n"
        
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
                chunk_num = (already_count // 12) + 1  # 12 - это CHUNK_SIZE
                start_idx = already_count
                end_idx = min(start_idx + 12, total_strings)

                global_chunk = dict(items[start_idx:end_idx])
                local_chunk = {f"text_{i}": v for i, v in enumerate(global_chunk.values())}
                local_to_global = {f"text_{i}": k for i, k in enumerate(global_chunk.keys())}

                yield f"data: {json.dumps({'type': 'log', 'text': f'🧠 Чанк {chunk_num} отправлен в Ollama ({len(local_chunk)} строк)...'})}\n\n"

                # ВЫЗОВ СЕРВИСА ПЕРЕВОДА
                success, chunk_res, error_msg = translate_chunk(
                    model_name=cfg.models[0],
                    ollama_url=cfg.ollama_api_url,
                    system_prompt=system_prompt,
                    local_chunk=local_chunk,
                    glossary_data=glossary_data,
                    payload_options=cfg.options,
                    timeout=300,
                    keep_alive=cfg.keep_alive
                )

                if not success:
                    yield f"data: {json.dumps({'type': 'error', 'text': f'Чанк {chunk_num} не прошел валидацию: {error_msg}'})}\n\n"
                    return

                for l_k, text_val in chunk_res.items():
                    translated_ai_dict[local_to_global[l_k]] = text_val

                with open(cache_file, "w", encoding="utf-8") as f:
                    json.dump({"hash": source_hash, "translated_data": translated_ai_dict}, f, ensure_ascii=False)

                percent = int((len(translated_ai_dict) / total_strings) * 100)
                yield f"data: {json.dumps({'type': 'progress', 'current': len(translated_ai_dict), 'total': total_strings, 'percent': percent})}\n\n"
                yield f"data: {json.dumps({'type': 'log', 'text': f'✅ Чанк {chunk_num} успешно валидирован и сохранен.'})}\n\n"

        except GeneratorExit:
            print(f"🛑 [Остановка] Сохранено: {len(translated_ai_dict)}")
            raise

        # --- СБОРКА РЕЗУЛЬТАТА ---
        with open(os.path.join(temps_dir, ".key_bridge_cache.json"), "r", encoding="utf-8") as f: 
            key_bridge = json.load(f)
        
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
            else: 
                out_data = final_map
            final_text = json.dumps(out_data, ensure_ascii=False, indent=2)
        elif file_format == "xml":
            with open(os.path.join(temps_dir, ".xml_template_cache"), "r", encoding="utf-8") as f: 
                result_xml = f.read()
            for k, v in final_map.items(): 
                result_xml = result_xml.replace(f"__TOKEN_{k}__", v)
            final_text = result_xml
        else:
            sorted_lines = [final_map.get(f"text_line_{i}", "") for i in range(len(final_map))]
            final_text = "\n".join(sorted_lines)

        for f in [os.path.join(temps_dir, ".key_bridge_cache.json"), os.path.join(temps_dir, ".xml_template_cache")]:
            if os.path.exists(f): os.remove(f)
        if os.path.exists(cache_file): os.remove(cache_file)

        yield f"data: {json.dumps({'type': 'log', 'text': '🎉 Генерация успешно завершена!'})}\n\n"
        yield f"data: {json.dumps({'type': 'done', 'result': final_text})}\n\n"

    return Response(stream_with_context(generate()), content_type='text/event-stream')