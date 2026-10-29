from sqlmodel import select
from sqlalchemy.ext.asyncio import AsyncSession
from src.models.main_model import User


class AuthService():
    async def get_user_by_statecode(self, statecode:str, session:AsyncSession):
        statement = select(User).where(User.state_code == statecode)
        result = await session.execute(statement)
        user = result.scalar_one_or_none()
        
        return user
    
    
    async def 