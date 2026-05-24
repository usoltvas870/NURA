from sqladmin import Admin, ModelView
from sqladmin.authentication import AuthenticationBackend
from starlette.requests import Request

from core.config import settings
from core.database_sync import sync_engine
from core.models import User, Report, Payment


class AdminAuth(AuthenticationBackend):
    async def login(self, request: Request) -> bool:
        form = await request.form()
        username = form.get("username")
        password = form.get("password")
        if (
            username == settings.admin_username
            and password == settings.admin_password
        ):
            request.session.update({"token": "authenticated"})
            return True
        return False

    async def logout(self, request: Request) -> bool:
        request.session.clear()
        return True

    async def authenticate(self, request: Request) -> bool:
        return request.session.get("token") == "authenticated"


auth_backend = AdminAuth(secret_key=settings.secret_key)


class UserAdmin(ModelView, model=User):
    column_list = [
        User.id,
        User.telegram_id,
        User.username,
        User.first_name,
        User.birth_date,
        User.main_archetype,
        User.main_archetype_number,
        User.subscription_status,
        User.subscription_until,
        User.created_at,
    ]
    column_searchable_list = [User.telegram_id, User.username, User.first_name]
    column_sortable_list = [
        User.created_at,
        User.subscription_status,
        User.telegram_id,
    ]
    column_default_sort = [(User.created_at, True)]
    form_excluded_columns = [User.id]
    form_rules = [
        "telegram_id",
        "username",
        "first_name",
        "birth_date",
        "main_archetype",
        "main_archetype_number",
        "subscription_status",
        "subscription_until",
    ]
    name = "Пользователь"
    name_plural = "Пользователи"
    icon = "fa-solid fa-user"


class ReportAdmin(ModelView, model=Report):
    column_list = [
        Report.id,
        Report.user_id,
        Report.report_type,
        Report.token,
        Report.created_at,
    ]
    column_searchable_list = [Report.token]
    column_sortable_list = [Report.created_at]
    column_default_sort = [(Report.created_at, True)]
    form_excluded_columns = [Report.id]
    name = "Отчёт"
    name_plural = "Отчёты"
    icon = "fa-solid fa-file"


class PaymentAdmin(ModelView, model=Payment):
    column_list = [
        Payment.id,
        Payment.user_id,
        Payment.amount,
        Payment.status,
        Payment.yookassa_id,
        Payment.created_at,
    ]
    column_searchable_list = [Payment.yookassa_id]
    column_sortable_list = [Payment.created_at, Payment.status, Payment.amount]
    column_default_sort = [(Payment.created_at, True)]
    form_excluded_columns = [Payment.id]
    name = "Платёж"
    name_plural = "Платежи"
    icon = "fa-solid fa-credit-card"


def setup_admin(app):
    admin = Admin(
        app,
        engine=sync_engine,
        authentication_backend=auth_backend,
        title="NURA Admin",
        base_url="/admin",
    )

    admin.add_view(UserAdmin)
    admin.add_view(ReportAdmin)
    admin.add_view(PaymentAdmin)

    return admin
