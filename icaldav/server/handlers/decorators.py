"""Server handler decorators for aiohttp request processing."""

from functools import wraps
from typing import Any, Callable, Coroutine
from aiohttp import web


def path_args(
    func: Callable[..., Coroutine[Any, Any, web.Response]],
) -> Callable[..., Coroutine[Any, Any, web.Response]]:
    """Decorator unpacking request.match_info directly into handler keyword arguments."""

    @wraps(func)
    async def wrapper(self: Any, request: web.Request) -> web.Response:
        return await func(self, request, **request.match_info)

    return wrapper
