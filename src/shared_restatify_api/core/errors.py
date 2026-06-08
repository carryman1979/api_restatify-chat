from fastapi import HTTPException


def unauthorized_error(detail: str = "Unauthorized") -> HTTPException:
    return HTTPException(status_code=401, detail=detail)
