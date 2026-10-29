from fastapi import APIRouter

from src.modules.auth.schema import LoginSchema

auth_router =  APIRouter()



@auth_router.post("/login")
async def login(login_data:LoginSchema):
    
    
    return 