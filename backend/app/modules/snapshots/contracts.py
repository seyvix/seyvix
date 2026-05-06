from app.shared.module_definitions import ModuleDefinition

MODULE = ModuleDefinition(
    name="snapshots",
    description="Point-in-time snapshots for content, derived artifacts, and indexing state.",
    public_contracts=["snapshot-settings", "snapshot-job", "snapshot-artifact", "snapshot-worker"],
    plugin_capabilities=["snapshot_backend", "thumbnail_generator", "archive_preservation"],
)
