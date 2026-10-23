import httpx

from api.main import create_app
from app.container import Container
from tests.conftest import say


async def _noop():
    return None


async def test_chat_roundtrip_and_health_with_fake_llm(rig):
    r = rig([say("Hello!"), say("Still here.")])
    app = create_app(Container(agent=r.agent, sessions=r.sessions, close=_noop))

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        assert (await client.get("/health")).json() == {"status": "ok"}

        first = (await client.post("/chat", json={"message": "hi"})).json()
        second = (
            await client.post("/chat", json={"session_id": first["session_id"], "message": "hi"})
        ).json()

    assert first["reply"] == "Hello!"
    assert first["failed"] is False
    assert second["session_id"] == first["session_id"]
    assert len(r.llm.calls[1][1]) == 3  # second call saw the first exchange


async def test_empty_message_is_rejected(rig):
    r = rig([])
    app = create_app(Container(agent=r.agent, sessions=r.sessions, close=_noop))

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/chat", json={"message": ""})

    assert response.status_code == 422


async def test_chat_page_is_served(rig):
    r = rig([])
    app = create_app(Container(agent=r.agent, sessions=r.sessions, close=_noop))

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/")

    assert response.status_code == 200
    assert "<form" in response.text
