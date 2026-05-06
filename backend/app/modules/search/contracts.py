from app.shared.module_definitions import ModuleDefinition

MODULE = ModuleDefinition(
    name="search",
    description="Search orchestration, ranking, and retrieval APIs across content stores.",
    public_contracts=["search-query", "search-result", "ranking-profile"],
    plugin_capabilities=["search_backend", "reranker"],
)
