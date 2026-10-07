from __future__ import annotations

from contextlib import asynccontextmanager


class _NoopPool:
    def acquire(self):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def fetchval(self, *args, **kwargs):
        return None

    async def fetch(self, *args, **kwargs):
        return []

    async def execute(self, *args, **kwargs):
        return None


_pool = _NoopPool()


async def init_pool(database_url: str):
    return None


async def close_pool():
    return None


def pool():
    return _pool
