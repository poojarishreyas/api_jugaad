import asyncio
import time
from abc import ABC, abstractmethod

from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from ..scraper import scrape_response

class BaseProvider(ABC):
    name: str = "base"
    url: str = ""

    @abstractmethod
    async def verify_auth(self, worker) -> bool:
        pass

    @abstractmethod
    async def start_new_chat(self, worker):
        pass

    @abstractmethod
    async def type_message(self, worker, message: str):
        pass

    @abstractmethod
    async def click_send(self, worker):
        pass

    @abstractmethod
    async def wait_for_response(self, worker):
        pass

    @abstractmethod
    async def scrape_response(self, worker) -> str:
        pass


class WebChatProvider(BaseProvider):
    """Shared Playwright flow used by the supported browser chat providers."""

    SELECTORS: dict[str, str] = {}

    async def verify_auth(self, worker) -> bool:
        if any(marker in worker.page.url for marker in ("login", "signin", "sign-in", "auth", "ServiceLogin")):
            return False
        try:
            await worker.page.wait_for_selector(self.SELECTORS["inputBox"], timeout=15_000)
            return True
        except PlaywrightTimeoutError:
            return False

    async def start_new_chat(self, worker):
        await worker.page.goto(self.url)
        await worker.page.wait_for_selector(self.SELECTORS["inputBox"], timeout=15_000)

    async def type_message(self, worker, message: str):
        await worker.page.locator(self.SELECTORS["inputBox"]).fill(message)

    async def click_send(self, worker):
        button = worker.page.locator(self.SELECTORS["sendButton"])
        if await button.count() and await button.is_enabled():
            await button.click()
        else:
            await worker.page.locator(self.SELECTORS["inputBox"]).press("Enter")

    async def wait_for_response(self, worker):
        page = worker.page
        try:
            await page.wait_for_selector(self.SELECTORS["assistantMessage"], state="attached", timeout=30_000)
        except PlaywrightTimeoutError:
            pass

        try:
            await page.wait_for_selector(self.SELECTORS["stopButton"], state="attached", timeout=2_000)
            await page.wait_for_selector(self.SELECTORS["stopButton"], state="detached", timeout=120_000)
            return
        except PlaywrightTimeoutError:
            pass

        # Some UIs do not expose a reliable stop control. Treat one second of
        # unchanged rendered output as completion, with a bounded wait.
        messages = page.locator(self.SELECTORS["assistantMessage"])
        last_text, last_change = "", time.monotonic()
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            count = await messages.count()
            if count:
                current_text = await messages.nth(count - 1).inner_text()
                if current_text != last_text:
                    last_text, last_change = current_text, time.monotonic()
                elif current_text and time.monotonic() - last_change > 1:
                    return
            await asyncio.sleep(0.2)

    async def scrape_response(self, worker) -> str:
        messages = worker.page.locator(self.SELECTORS["assistantMessage"])
        count = await messages.count()
        return await scrape_response(messages.nth(count - 1)) if count else ""
