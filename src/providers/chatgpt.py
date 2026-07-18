from .base import WebChatProvider

SELECTORS = {
    "inputBox": '#prompt-textarea',
    "sendButton": 'button[data-testid="send-button"]',
    "stopButton": 'button[aria-label="Stop generating"]',
    "assistantMessage": 'div[data-message-author-role="assistant"]',
}

class ChatGPTProvider(WebChatProvider):
    name = "chatgpt"
    url = "https://chatgpt.com/"
    
    SELECTORS = SELECTORS
