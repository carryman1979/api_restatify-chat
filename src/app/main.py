from fastapi import FastAPI

from src.app.modules.auth.router import router as auth_router
from src.app.modules.health.router import router as health_router
from src.app.modules.support_chat.router import router as support_router
from src.app.modules.support_chat.websocket_router import router as support_ws_router
from src.shared_restatify_api.config.settings import get_settings


settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.include_router(health_router)
app.include_router(auth_router, prefix="/v1/auth", tags=["auth"])
app.include_router(support_router, prefix="/v1/support", tags=["support-chat"])
app.include_router(support_ws_router, prefix="/v1/support", tags=["support-chat-ws"])
