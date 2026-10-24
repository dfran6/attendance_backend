from fastapi import Depends, Request, status
from fastapi.security import HTTPBearer 
from fastapi.security.http import HTTPAuthorizationCredentials
from src.models.main_model import User, UserStatus
from src.modules.userAuth.service import UserService
from .utils import decode_token
from fastapi.exceptions import HTTPException
from src.db.mains import get_session
from sqlmodel.ext.asyncio.session import AsyncSession
from typing import Any, List
import uuid
from src.core.redis import token_in_blocklist



user_service = UserService()


class TokenBearer(HTTPBearer):
    def __init__(self, auto_error = True):
        super().__init__(auto_error=auto_error)
        
    async def __call__(self, request: Request) -> HTTPAuthorizationCredentials | None:
        creds = await super().__call__(request)
        if creds is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
        token = creds.credentials
        token_data = decode_token(token)
        if not token_data:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")
        if await token_in_blocklist(token_data['jti']):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"error":" token has been revoked", 
                    "resolution":"please get a new token"})

        
        self.verify_token_data(token_data)
        
        return token_data
        
    def token_valid(self, token:str) -> bool :
        
        return decode_token(token) is not None
    
    def verify_token_data(self,token_data):
        raise NotImplementedError("please Override this method in child classes")


class AccessTokenBearer(TokenBearer):
     def verify_token_data(self, token_data:dict) -> None:
        if not token_data or token_data.get("refresh"):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Please provide an access token")
               
            
class RefreshTokenBearer(TokenBearer):
    def verify_token_data(self, token_data:dict) -> None:
            if not token_data or not token_data.get("refresh"):
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Please provide a refresh token")


async def get_current_user(token_details : dict = Depends(AccessTokenBearer()),session:AsyncSession = Depends(get_session)):
    user_data = token_details.get("user", {})
    user_id = user_data.get("user_uid")
    if user_id:
        try:
            user = await session.get(User, uuid.UUID(str(user_id)))
        except (TypeError, ValueError):
            user = None
    else:
        user = await user_service.get_user_by_email(user_data.get("email", ""), session)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User account no longer exists")
    if not user.is_active or user.status == UserStatus.banned:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is inactive or banned")
    
    return user


   
    
class RoleChecker:
    def __init__(self, allowed_roles:List[str]) -> None:
        
        self.allowed_roles = allowed_roles
        
        
    def __call__(self, current_user: User = Depends(get_current_user)) -> Any:
            
        if not current_user.is_active:
            raise HTTPException(
            status_code= status.HTTP_403_FORBIDDEN,
            detail={"message":"Account is inactive ",
                    "resolution":"contact support for more details"
                    })
            
        if current_user.status == UserStatus.banned:
            raise HTTPException(
            status_code= status.HTTP_403_FORBIDDEN,
            detail={"message":"Account is banned ",
                    "resolution":"contact support for more details"
                    })
                    
            
        if current_user.role in self.allowed_roles:
            return True
        
        raise HTTPException(
            status_code= status.HTTP_403_FORBIDDEN,
            detail="you are not permitted to perform this action")
        
