from dataclasses import dataclass

from app.core.config import Settings


@dataclass(slots=True)
class PluginContext:
    settings: Settings
