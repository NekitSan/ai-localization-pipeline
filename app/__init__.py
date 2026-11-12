import json
import os

from dotenv import load_dotenv
from flask import Flask

# Импортируем наши модули
from app.config import load_config
from app.utils.glossary import GlossaryManager
from app.utils.prompt_manager import PromptBuilder


def create_app():
    app = Flask(__name__)
    load_dotenv()

    # 1. Загружаем конфиг
    try:
        cfg = load_config()
    except Exception as e:
        print(f"❌ Ошибка конфигурации: {e}")
        raise

    # 2. Загружаем глоссарии и промпты
    base_dir = os.path.dirname(os.path.abspath(__file__))
    llm_dir = os.path.join(base_dir, "llm")
    
    glossary_mgr = GlossaryManager(llm_dir)
    prompt_builder = PromptBuilder(os.path.join(llm_dir, "prompts"), glossary_mgr)

    # 3. Сохраняем в app.config
    app.config['APP_CONFIG'] = cfg
    app.config['GLOSSARY_MGR'] = glossary_mgr
    app.config['PROMPT_BUILDER'] = prompt_builder

    # 4. Регистрируем Blueprints (Роуты)
    from app.routes import bp
    app.register_blueprint(bp)

    return app