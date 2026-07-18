import asyncio
from .browser import get_browser_worker

_provider = None
_lock = asyncio.Lock()

def set_provider(p):
    global _provider
    _provider = p

def is_busy() -> bool:
    return _lock.locked()

def get_provider_name() -> str:
    return _provider.name if _provider else "unknown"

async def send_message(message: str) -> str:
    """
    Sends a message and returns the response.
    Queues requests until the single browser session is available.
    """
    async with _lock:
        if not _provider:
            raise Exception("Provider not initialized.")
            
        worker = get_browser_worker()
        if not worker:
            raise Exception("Browser worker not initialized.")
            
        # Start a fresh chat
        await _provider.start_new_chat(worker)
        
        # Type the message
        await _provider.type_message(worker, message)
        
        # Click send
        await _provider.click_send(worker)
        
        # Wait for the response to finish streaming
        await _provider.wait_for_response(worker)
        
        # Small buffer
        await asyncio.sleep(0.5)
        
        # Scrape response
        response = await _provider.scrape_response(worker)
        
        if not response:
            raise Exception(f"Could not scrape response from {_provider.name}.")
            
        return response
