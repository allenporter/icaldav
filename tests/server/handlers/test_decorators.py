"""Unit tests for server handler decorators."""

from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from icaldav.server.handlers.decorators import path_args


async def test_path_args_decorator() -> None:
    """Test path_args unpacks request match_info as keyword arguments."""

    @path_args
    async def sample_handler(
        self, request: web.Request, collection_id: str
    ) -> web.Response:
        return web.Response(text=f"coll:{collection_id}")

    class DummyHandler:
        pass

    handler_inst = DummyHandler()
    request = make_mocked_request(
        "GET", "/work", match_info={"collection_id": "test_work"}
    )

    resp = await sample_handler(handler_inst, request)
    assert resp.text == "coll:test_work"
