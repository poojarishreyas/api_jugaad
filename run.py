import sys
import uvicorn

from src.config import config
from src.providers import get_provider
from src import chat
from src.app import app

def prompt_for_provider():
    print()
    print("╔══════════════════════════════════════╗")
    print("║       🤖 API Jugaad — Select AI      ║")
    print("╠══════════════════════════════════════╣")
    print("║  1. chatgpt      ← default           ║")
    print("║  2. zai                              ║")
    print("║  3. gemini                           ║")
    print("╚══════════════════════════════════════╝")
    print()
    
    choice = input("Choose provider [1-3] (Enter for chatgpt): ").strip()
    if choice == "2":
        return "zai"
    elif choice == "3":
        return "gemini"
    else:
        return "chatgpt"

def main():
    print("==============================================")
    print("Welcome to API Jugaad (Python + Playwright)")
    print("==============================================\n")
    
    # Prompt the user for the provider
    provider_name = prompt_for_provider()
    
    provider = get_provider(provider_name)
    if not provider:
        print(f"Error: Unknown provider '{provider_name}'")
        sys.exit(1)
        
    chat.set_provider(provider)
    print(f"[*] Selected Provider: {provider.name}")
    print(f"[*] Server Port: {config.PORT}")
    
    # Playwright browser init + auth check happens in FastAPI lifespan (src/app.py).
    # Just start uvicorn — it will trigger the lifespan startup automatically.
    uvicorn.run(app, host="0.0.0.0", port=config.PORT, log_level="info")

if __name__ == "__main__":
    main()
