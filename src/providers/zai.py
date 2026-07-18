from .base import WebChatProvider

SELECTORS = {
    "inputBox": '#chat-input',
    "sendButton": '#send-message-button',
    "stopButton": 'button[aria-label="Stop"], button.stop-btn',
    "assistantMessage": '.markdown-prose',
}

class ZaiProvider(WebChatProvider):
    name = "zai"
    url = "https://chat.z.ai/"
    
    SELECTORS = SELECTORS
