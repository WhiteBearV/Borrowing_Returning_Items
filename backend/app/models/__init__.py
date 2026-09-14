# imported so Alembic can detect all models via `import app.models`
from app.models import (  # noqa: F401
    audit_log,
    auth_token,
    borrow_item,
    borrow_request,
    bundle,
    change_request,
    eligible_student,
    equipment,
    equipment_category,
    equipment_part,
    notification,
    setting,
    user,
)
