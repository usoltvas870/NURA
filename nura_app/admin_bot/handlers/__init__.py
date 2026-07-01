from admin_bot.handlers.chat import router as chat_router
from admin_bot.handlers.deploy import router as deploy_router
from admin_bot.handlers.help import router as help_router
from admin_bot.handlers.restart import router as restart_router
from admin_bot.handlers.status import router as status_router

__all__ = [
    "chat_router",
    "deploy_router",
    "help_router",
    "restart_router",
    "status_router",
]
