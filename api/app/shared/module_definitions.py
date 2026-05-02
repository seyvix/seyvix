from pydantic import BaseModel


class ModuleDefinition(BaseModel):
    name: str
    description: str
    public_contracts: list[str]
    plugin_capabilities: list[str]
