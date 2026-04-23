from collections import defaultdict
from collections.abc import Callable


class PluginRegistry:
    def __init__(self) -> None:
        self._handlers: dict[str, list[Callable[..., object]]] = defaultdict(list)

    def register(self, capability: str, handler: Callable[..., object]) -> None:
        self._handlers[capability].append(handler)

    def get_handlers(self, capability: str) -> list[Callable[..., object]]:
        return list(self._handlers[capability])
