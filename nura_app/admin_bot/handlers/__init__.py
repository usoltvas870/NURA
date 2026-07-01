from admin_bot.handlers.deploy import router as deploy_router
from admin_bot.handlers.errors import router as errors_router
from admin_bot.handlers.help import router as help_router
from admin_bot.handlers.logs import router as logs_router
from admin_bot.handlers.restart import router as restart_router
from admin_bot.handlers.status import router as status_router

__all__ = [
    "deploy_router",
    "errors_router",
    "help_router",
    "logs_router",
    "restart_router",
    "status_router",
]
