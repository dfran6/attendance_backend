from redis import asyncio as aioredis
from src.core.config import Config

JTI_EXPIRY = 2 * 24 * 60 * 60

token_blocklist = aioredis.from_url(Config.REDIS_URL)
otp_store = aioredis.from_url(Config.REDIS_URL) 
redis_client = aioredis.from_url(Config.REDIS_URL) 

async def add_jti_to_blocklist(jti:str) -> None:
    await token_blocklist.set(
        name= jti,
        value='',
        ex=JTI_EXPIRY
        
    )

async def token_in_blocklist(jti: str) -> bool:
    jti= await token_blocklist.get(jti) 
    
    return jti is not None



async def store_otp(email: str, otp: str, expiry: int = 300):
    """Store OTP in Redis with 5-minute expiry"""
    key = f"otp:{email}"
    await otp_store.set(key, otp, ex=expiry)

async def verify_otp(email: str, otp: str) -> bool:
    """Verify OTP and return True if valid"""
    key = f"otp:{email}"
    stored_otp = await otp_store.get(key)
    # Redis returns bytes, decode to string for comparison
    if stored_otp:
        stored_otp = stored_otp.decode('utf-8') if isinstance(stored_otp, bytes) else stored_otp
    if stored_otp and stored_otp == otp:
        await otp_store.delete(key)  # Delete after use
        return True
    return False

async def get_otp(email: str) -> str | None:
    """Retrieve OTP from Redis"""
    key = f"otp:{email}"
    return await otp_store.get(key)

async def store_verification_token(email: str, token: str, expiry: int = 600):
    """Store verification token in Redis with 10-minute expiry"""
    key = f"verify_token:{email}"
    await otp_store.set(key, token, ex=expiry)

async def verify_token(email: str, token: str) -> bool:
    """Verify token and delete if valid"""
    key = f"verify_token:{email}"
    stored_token = await otp_store.get(key)
    # Redis returns bytes, decode to string for comparison
    if stored_token:
        stored_token = stored_token.decode('utf-8') if isinstance(stored_token, bytes) else stored_token
    if stored_token and stored_token == token:
        await otp_store.delete(key)  # Delete after use
        return True
    return False

async def get_email_from_verification_token(token: str) -> str | None:
    """Get email associated with verification token (for debugging)"""
    # Iterate through keys to find matching token
    pattern = "verify_token:*"
    keys = await otp_store.keys(pattern)
    for key in keys:
        stored_token = await otp_store.get(key)
        if stored_token == token:
            return key.replace("verify_token:", "")
    return None
