from app.shared.module_definitions import ModuleDefinition

MODULE = ModuleDefinition(
    name="auth",
    description="Identity, API keys, roles, and access policy bindings.",
    public_contracts=["current-user", "service-auth", "tenant-boundary"],
    plugin_capabilities=["auth_provider", "policy_provider"],
)
