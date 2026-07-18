from .chatgpt import ChatGPTProvider
from .zai import ZaiProvider
from .gemini import GeminiProvider

def get_provider(name: str):
    providers = {
        "chatgpt": ChatGPTProvider,
        "zai": ZaiProvider,
        "gemini": GeminiProvider
    }
    provider_class = providers.get(name.lower())
    if provider_class:
        return provider_class()
    return None
