from app.shared.module_definitions import ModuleDefinition

MODULE = ModuleDefinition(
    name="snapshots",
    description="Point-in-time snapshots for content, derived artifacts, and indexing state.",
    public_contracts=["snapshot", "snapshot-manifest", "restore-request"],
    plugin_capabilities=["snapshot_backend"],
)
