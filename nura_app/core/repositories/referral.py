import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from core.models import ReferralReward


class ReferralRepository:
    def __init__(self, session_factory: async_sessionmaker):
        self._session_factory = session_factory

    async def create_reward(
        self,
        referrer_id: uuid.UUID,
        referred_id: uuid.UUID,
        event: str,
    ) -> ReferralReward | None:
        async with self._session_factory() as session:
            try:
                reward = ReferralReward(
                    referrer_id=referrer_id,
                    referred_id=referred_id,
                    event=event,
                )
                session.add(reward)
                await session.commit()
                return reward
            except Exception:
                await session.rollback()
                return None

    async def get_referrer_stats(self, referrer_id: uuid.UUID) -> dict:
        async with self._session_factory() as session:
            result = await session.execute(
                select(ReferralReward).where(
                    ReferralReward.referrer_id == referrer_id
                )
            )
            rewards = result.scalars().all()
            return {
                "total": len(rewards),
                "registrations": sum(1 for r in rewards if r.event == "registration"),
                "purchases": sum(1 for r in rewards if r.event == "matrix_purchase"),
            }
