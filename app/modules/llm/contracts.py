from app.shared.module_definitions import ModuleDefinition

MODULE = ModuleDefinition(
    name="llm",
    description="LLM provider abstraction, prompt execution, and model policy enforcement.",
    public_contracts=["completion-request", "tool-call", "provider-policy"],
    plugin_capabilities=["llm_provider", "tool_runtime"],
)
