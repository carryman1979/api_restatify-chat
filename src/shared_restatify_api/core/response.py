from typing import Any


def ok(data: Any) -> dict[str, Any]:
    return {"success": True, "data": data}
