from app.shared.module_definitions import ModuleDefinition

MODULE = ModuleDefinition(
    name="content",
    description="Canonical content records, metadata, and ingestion lifecycle management.",
    public_contracts=["content-record", "content-version", "ingestion-job"],
    plugin_capabilities=["content_ingestor", "content_post_processor"],
)
