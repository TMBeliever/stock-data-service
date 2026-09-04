import datetime
from typing import Optional, Dict, Any
import bcrypt
import jwt
from common_server.config import settings

def get_password_hash(password: str) -> str:
    """使用 Bcrypt 进行加盐哈希加密"""
    pwd_bytes = password.encode("utf-8")
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(pwd_bytes, salt).decode("utf-8")

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """比对明文密码与 Bcrypt 密文"""
    try:
        return bcrypt.checkpw(
            plain_password.encode("utf-8"),
            hashed_password.encode("utf-8")
        )
    except Exception:
        return False

def create_access_token(data: Dict[str, Any], expires_delta: Optional[datetime.timedelta] = None) -> str:
    """签发标准 JWT Access Token"""
    to_encode = data.copy()
    now = datetime.datetime.now(datetime.timezone.utc)
    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + datetime.timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode.update({"exp": expire, "iat": now})
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt

def decode_access_token(token: str) -> Optional[Dict[str, Any]]:
    """校验并解析 JWT Token，过期或被篡改时返回 None"""
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        return payload
    except jwt.PyJWTError:
        return None
