from app.shared.module_definitions import ModuleDefinition

MODULE = ModuleDefinition(
    name="recommendations",
    description="Semantic recommendations for navigating related user content.",
    public_contracts=["note-recommendation"],
    plugin_capabilities=["recommendation_ranker"],
)
