import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    PROVIDER = os.getenv("PROVIDER", "chatgpt")
    PORT = int(os.getenv("PORT", "3000"))
    API_KEY = os.getenv("API_KEY", "")

config = Config()
