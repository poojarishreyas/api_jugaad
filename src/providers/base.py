from abc import ABC, abstractmethod

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
