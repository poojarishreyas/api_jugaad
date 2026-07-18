from .base import WebChatProvider

SELECTORS = {
    "inputBox": 'rich-textarea p',
    "sendButton": 'button[aria-label="Send message"]',
    "stopButton": 'button[aria-label="Stop generating"]',
    "assistantMessage": 'message-content',
}

class GeminiProvider(WebChatProvider):
    name = "gemini"
    url = "https://gemini.google.com/app"
    
    SELECTORS = SELECTORS
