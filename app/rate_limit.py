from slowapi import Limiter
from slowapi.util import get_remote_address

from app.config import settings

# In-memory storage is fine for a single instance; point `storage_uri` at Redis when scaling out.
limiter = Limiter(key_func=get_remote_address, enabled=settings.rate_limit_enabled)
