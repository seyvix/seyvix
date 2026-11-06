"""Single place that registers every ORM model on `Base.metadata`.

Used by alembic, the worker and tests so relationships across modules always resolve.
"""

from __future__ import annotations


def import_all_models() -> None:
    from app.core.database import Base
    from app.modules.auth import models as _auth  # noqa: F401
    from app.modules.content import models as _content  # noqa: F401
    from app.modules.snapshots import models as _snapshots  # noqa: F401
    from app.modules.tags import models as _tags  # noqa: F401
    from app.modules.taxonomy import models as _taxonomy  # noqa: F401
    from app.modules.telegram_integration import models as _telegram  # noqa: F401
    from app.modules.vectorization import models as _vectorization  # noqa: F401
    from app.platform import heartbeat as _heartbeat  # noqa: F401
    from app.platform.events import models as _events  # noqa: F401
    from app.platform.jobs import register_notify_triggers

    register_notify_triggers(Base.metadata)
