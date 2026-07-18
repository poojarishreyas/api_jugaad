import time
import asyncio
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from .base import BaseProvider
from ..scraper import scrape_markdown

SELECTORS = {
    "inputBox": '#prompt-textarea',
    "sendButton": 'button[data-testid="send-button"]',
    "stopButton": 'button[aria-label="Stop generating"]',
    "assistantMessage": 'div[data-message-author-role="assistant"]',
}

class ChatGPTProvider(BaseProvider):
    name = "chatgpt"
    url = "https://chatgpt.com/"
    
    async def verify_auth(self, worker) -> bool:
        page = worker.page
        url = page.url
        if "login" in url or "auth" in url:
            return False
            
        try:
            await page.wait_for_selector(SELECTORS['inputBox'], timeout=15000)
            return True
        except PlaywrightTimeoutError:
            return False

    async def start_new_chat(self, worker):
        page = worker.page
        await page.goto(self.url)
        await page.wait_for_selector(SELECTORS['inputBox'], timeout=15000)

    async def type_message(self, worker, message: str):
        page = worker.page
        await page.locator(SELECTORS['inputBox']).fill(message)

    async def click_send(self, worker):
        page = worker.page
        btn = page.locator(SELECTORS['sendButton'])
        if await btn.count() > 0 and await btn.is_enabled():
            await btn.click()
        else:
            await page.locator(SELECTORS['inputBox']).press("Enter")

    async def wait_for_response(self, worker):
        page = worker.page
        print("[chatgpt] Waiting for assistant message to appear...")
        try:
            await page.wait_for_selector(SELECTORS['assistantMessage'], state="attached", timeout=30000)
        except PlaywrightTimeoutError:
            pass
            
        print("[chatgpt] Waiting for streaming to finish...")
        
        try:
            await page.wait_for_selector(SELECTORS['stopButton'], state="attached", timeout=2000)
            print("[chatgpt] Stop button detected. Waiting for it to disappear...")
            await page.wait_for_selector(SELECTORS['stopButton'], state="detached", timeout=120000)
            print("[chatgpt] Stop button disappeared.")
            return
        except PlaywrightTimeoutError:
            pass
            
        print("[chatgpt] Falling back to DOM stabilization...")
        
        last_text = ""
        last_time = time.time()
        
        locators = page.locator(SELECTORS['assistantMessage'])
        start = time.time()
        while time.time() - start < 120:
            count = await locators.count()
            if count == 0:
                await asyncio.sleep(0.2)
                continue
                
            current_text = await locators.nth(count - 1).inner_text()
            if current_text != last_text:
                last_text = current_text
                last_time = time.time()
            elif time.time() - last_time > 1.0:
                if current_text:
                    print("[chatgpt] DOM stabilized.")
                    return
            await asyncio.sleep(0.2)

    async def scrape_response(self, worker) -> str:
        page = worker.page
        locators = page.locator(SELECTORS['assistantMessage'])
        count = await locators.count()
        if count == 0:
            return ""
        return await scrape_markdown(locators.nth(count - 1))
