from app.modules.auth.contracts import MODULE as AUTH_MODULE
from app.modules.content.contracts import MODULE as CONTENT_MODULE
from app.modules.llm.contracts import MODULE as LLM_MODULE
from app.modules.search.contracts import MODULE as SEARCH_MODULE
from app.modules.snapshots.contracts import MODULE as SNAPSHOTS_MODULE
from app.modules.tags.contracts import MODULE as TAGS_MODULE
from app.modules.taxonomy.contracts import MODULE as TAXONOMY_MODULE
from app.modules.vectorization.contracts import MODULE as VECTORIZATION_MODULE
from app.shared.module_definitions import ModuleDefinition

ALL_MODULES: tuple[ModuleDefinition, ...] = (
    AUTH_MODULE,
    CONTENT_MODULE,
    SNAPSHOTS_MODULE,
    TAXONOMY_MODULE,
    TAGS_MODULE,
    SEARCH_MODULE,
    VECTORIZATION_MODULE,
    LLM_MODULE,
)


def list_modules() -> tuple[ModuleDefinition, ...]:
    return ALL_MODULES
