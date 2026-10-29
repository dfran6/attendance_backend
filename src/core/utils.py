from decimal import Decimal

from passlib.context import CryptContext
from datetime import datetime, timedelta
import logging
import jwt
from src.core.config import Config
import uuid
from itsdangerous import URLSafeTimedSerializer
import random
import string


password_context = CryptContext(
    schemes=['pbkdf2_sha256'],
    default='pbkdf2_sha256',
    pbkdf2_sha256__default_rounds=30000
)



ACCESS_TOKEN_EXPIRY = 2 * 60 * 60  # 2 hours

def generate_password_hash(password:str) -> str:
    hash = password_context.hash(password)
    return hash


def verify_password(password:str, hash:str) -> bool:
    return password_context.verify(password,hash)

def create_access_token(user_data:dict, expiry:timedelta = None, refresh:bool=False):
    payload ={}
    
    payload['user'] = user_data
    payload['exp'] = datetime.now() + ( expiry if expiry is not None else timedelta(seconds=ACCESS_TOKEN_EXPIRY))
    payload['jti'] = str(uuid.uuid4())
    
    payload['refresh'] = refresh
    
    token = jwt.encode(
        payload=payload,
        key= Config.JWT_SECRET,
        algorithm= Config.JWT_ALGORITHM
    )
    
    return token


def decode_token(token:str) -> dict:
    try:
        configured_algorithms = Config.JWT_ALGORITHM
        algorithms = configured_algorithms if isinstance(configured_algorithms, (list, tuple)) else [configured_algorithms]
        token_data = jwt.decode(
            jwt=token,
            key= Config.JWT_SECRET,
            algorithms=algorithms,
        )
        return token_data
    
    except jwt.ExpiredSignatureError:
        # Specific handling for expired tokens
        logging.warning("Token has expired. User needs to re-login.")
        return None

    except jwt.InvalidTokenError:
        # Specific handling for tampered or malformed tokens
        logging.error("Invalid token provided. Potential security issue.")
        return None

    except Exception as e:
        # A "catch-all" for any other unexpected errors (database, etc.)
        logging.error(f"Unexpected error during decoding: {str(e)}")
        return None
        
serilizer = URLSafeTimedSerializer(
        secret_key=Config.JWT_SECRET,
        salt = "email-verification"
    )

def create_url_safe_token(data:dict):
    
    token = serilizer.dumps(data)
    
    
    return token

def decode_url_safe_token(token:str):
    try:
        token_data = serilizer.loads(token)
        
        return token_data
    
    except Exception as e:
        logging.error(str(e))

        
def generate_otp(length: int = 6) -> str:
    """Generate a random 6-digit OTP code"""
    return ''.join(random.choices(string.digits, k=length))


