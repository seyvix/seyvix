from app.shared.module_definitions import ModuleDefinition

MODULE = ModuleDefinition(
    name="vectorization",
    description="Chunking, embedding generation, and vector index synchronization pipelines.",
    public_contracts=["chunker", "embedding-job", "vector-index"],
    plugin_capabilities=["embedding_provider", "chunking_strategy"],
)
