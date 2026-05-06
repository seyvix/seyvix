from typing import Protocol

from app.platform.plugin_sdk.context import PluginContext
from app.platform.plugin_sdk.manifests import PluginManifest
from app.platform.plugin_sdk.registry import PluginRegistry


class Plugin(Protocol):
    manifest: PluginManifest

    def register(self, registry: PluginRegistry) -> None: ...

    async def startup(self, ctx: PluginContext) -> None: ...

    async def shutdown(self, ctx: PluginContext) -> None: ...
