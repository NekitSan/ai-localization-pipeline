import os

from dotenv import load_dotenv

load_dotenv()

from app import create_app

app = create_app()

if __name__ == "__main__":
    is_dev = os.getenv("APP_ENV", "prod").lower() == "dev"
    
    print(f"🌐 Запуск сервера (Режим: {'DEV 🛠️' if is_dev else 'PROD 🚀'})...")
    print("🔗 Ссылка: http://127.0.0.1:8000")
    
    app.run(
        host="127.0.0.1", 
        port=8000, 
        debug=is_dev, 
        use_reloader=is_dev
    )