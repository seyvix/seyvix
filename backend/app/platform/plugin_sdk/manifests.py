from pydantic import BaseModel


class PluginManifest(BaseModel):
    name: str
    version: str
    api_version: str
    capabilities: list[str]
