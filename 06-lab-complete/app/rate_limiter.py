"""
Rate limiting (tiêu chí 7).

Sliding window 60 giây cho mỗi API key, lưu trong Redis sorted set để mọi
worker / instance dùng chung và vẫn còn sau khi restart agent.
Vượt giới hạn → HTTP 429 kèm header Retry-After.
"""
import hashlib
import math
import time
import uuid

import redis
from fastapi import HTTPException

from app.config import settings
from app.redis_client import r

WINDOW_SECONDS = 60


def _bucket(key: str) -> str:
    # Không lưu API key thô trong Redis
    return "ratelimit:" + hashlib.sha256(key.encode()).hexdigest()[:16]


def check_rate_limit(key: str) -> None:
    limit = settings.rate_limit_per_minute
    bucket = _bucket(key)
    now = time.time()
    member = f"{now}-{uuid.uuid4().hex[:8]}"
    try:
        # MULTI/EXEC: dọn request cũ, ghi request này, đếm — một khối nguyên tử,
        # nên nhiều worker gọi cùng lúc cũng không vượt giới hạn.
        pipe = r.pipeline(transaction=True)
        pipe.zremrangebyscore(bucket, 0, now - WINDOW_SECONDS)
        pipe.zadd(bucket, {member: now})
        pipe.zcard(bucket)
        pipe.expire(bucket, WINDOW_SECONDS + 1)
        _, _, count, _ = pipe.execute()

        if count > limit:
            r.zrem(bucket, member)  # request bị chặn không chiếm chỗ trong cửa sổ
            oldest = r.zrange(bucket, 0, 0, withscores=True)
            retry_after = WINDOW_SECONDS
            if oldest:
                retry_after = max(1, math.ceil(oldest[0][1] + WINDOW_SECONDS - now))
            raise HTTPException(
                status_code=429,
                detail=f"Rate limit exceeded: {limit} requests per minute",
                headers={"Retry-After": str(retry_after)},
            )
    except redis.RedisError:
        raise HTTPException(status_code=503, detail="Rate limiter unavailable")
