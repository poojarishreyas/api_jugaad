import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    PROVIDER = os.getenv("PROVIDER", "chatgpt")
    PORT = int(os.getenv("PORT", "3000"))
    API_KEY = os.getenv("API_KEY", "")
    CAPTURE_RAW_REQUESTS = os.getenv("CAPTURE_RAW_REQUESTS", "false").lower() in {"1", "true", "yes", "on"}
    RAW_REQUEST_PATH = os.getenv("RAW_REQUEST_PATH", "raw_request.json")
    CAPTURE_DIRECTORY = os.getenv("CAPTURE_DIRECTORY", "captures")

config = Config()
