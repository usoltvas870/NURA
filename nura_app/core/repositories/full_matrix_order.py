"""Repository marker for the dedicated full Matrix financial aggregate.

The transaction-sensitive methods intentionally live in the application service,
where Order, PaymentAttempt, PaymentEvent and Report must be locked together.
"""

from core.models import Order
from core.repositories.base import SQLAlchemyRepository


class FullMatrixOrderRepository(SQLAlchemyRepository[Order]):
    def __init__(self, session_factory):
        super().__init__(session_factory, Order)
