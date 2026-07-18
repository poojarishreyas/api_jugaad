import os
from playwright.async_api import async_playwright

class PlaywrightWorker:
    def __init__(self):
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None

    async def init_browser(self):
        print("[browser] Launching Playwright...")
        self.playwright = await async_playwright().start()
        
        # We use channel="chrome" to use the user's actual system Chrome installation.
        # This matches the previous Puppeteer behavior and offers the best compatibility.
        data_dir = os.path.join(os.getcwd(), "chrome-data")
        self.context = await self.playwright.chromium.launch_persistent_context(
            user_data_dir=data_dir,
            channel="chrome",
            headless=False,
            viewport={"width": 1024, "height": 768},
            args=["--disable-blink-features=AutomationControlled"]
        )
        
        # Hide playwright/webdriver signals
        await self.context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
        """)

        pages = self.context.pages
        if pages:
            self.page = pages[0]
        else:
            self.page = await self.context.new_page()

    async def close(self):
        if self.context:
            await self.context.close()
        if self.playwright:
            await self.playwright.stop()

_worker_instance = None

async def init_browser():
    global _worker_instance
    _worker_instance = PlaywrightWorker()
    await _worker_instance.init_browser()
    return _worker_instance

def get_browser_worker():
    return _worker_instance
