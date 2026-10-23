import httpx

from api.main import create_app
from app.container import Container
from core.interfaces import LLMResponse
from tests.conftest import call, say, use


async def _noop():
    return None


async def test_chat_roundtrip_and_health_with_fake_llm(rig, analytics):
    r = rig([say("Hello!"), say("Still here.")])
    app = create_app(
        Container(agent=r.agent, sessions=r.sessions, analytics=analytics, close=_noop)
    )

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


async def test_empty_message_is_rejected(rig, analytics):
    r = rig([])
    app = create_app(
        Container(agent=r.agent, sessions=r.sessions, analytics=analytics, close=_noop)
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/chat", json={"message": ""})

    assert response.status_code == 422


async def test_chat_page_is_served(rig, analytics):
    r = rig([])
    app = create_app(
        Container(agent=r.agent, sessions=r.sessions, analytics=analytics, close=_noop)
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/")

    assert response.status_code == 200
    assert "<form" in response.text


async def test_ranking_endpoint_works_without_a_model(rig, analytics):
    r = rig([])  # the fake model has no script: any model call would fail
    app = create_app(
        Container(agent=r.agent, sessions=r.sessions, analytics=analytics, close=_noop)
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/ranking", params={"region": "New England", "top_n": 3})

    body = response.json()
    assert response.status_code == 200
    assert [x["rank"] for x in body["ranking"]] == [1, 2, 3]
    assert body["as_of"] == "Apr 2026"
    assert body["caveats"]
    assert r.llm.calls == []


async def test_ranking_endpoint_reports_bad_input_clearly(rig, analytics):
    r = rig([])
    app = create_app(
        Container(agent=r.agent, sessions=r.sessions, analytics=analytics, close=_noop)
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        unknown = await client.get("/ranking", params={"region": "Narnia"})
        too_big = await client.get("/ranking", params={"top_n": 500})

    assert unknown.status_code == 400
    assert unknown.json()["detail"]["code"] == "unknown_region"
    assert too_big.status_code == 422


async def test_chat_without_an_api_key_is_a_clear_503_and_ranking_still_works(analytics):
    app = create_app(Container(agent=None, sessions=None, analytics=analytics, close=_noop))

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        chat = await client.post("/chat", json={"message": "hi"})
        ranking = await client.get("/ranking", params={"region": "New England", "top_n": 2})

    assert chat.status_code == 503
    assert chat.json()["detail"] == "Set ANTHROPIC_API_KEY to chat; GET /ranking works without it."
    assert ranking.status_code == 200


async def test_a_blank_api_key_builds_a_container_without_an_agent():
    from app.container import build_container
    from app.settings import Settings

    settings = Settings(anthropic_api_key="  ", data_backend="memory", _env_file=None)
    container = await build_container(settings)

    assert container.agent is None
    assert (await container.analytics.rank("New England", None, 1, None))["ranking"]


async def _client(r, analytics):
    app = create_app(
        Container(agent=r.agent, sessions=r.sessions, analytics=analytics, close=_noop)
    )
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def test_session_messages_return_only_the_visible_turns(rig, analytics):
    r = rig([use(call("add", a=2, b=3)), say("The sum is 5."), say("Still 5.")])
    async with await _client(r, analytics) as client:
        first = (await client.post("/chat", json={"message": "2+3?"})).json()
        sid = first["session_id"]
        await client.post("/chat", json={"session_id": sid, "message": "again?"})
        history = await client.get(f"/sessions/{sid}/messages")

    assert history.status_code == 200
    assert history.json() == [
        {"role": "user", "content": "2+3?"},
        {"role": "assistant", "content": "The sum is 5."},
        {"role": "user", "content": "again?"},
        {"role": "assistant", "content": "Still 5."},
    ]
    # the stored session still holds the hidden tool messages
    stored = await r.sessions.get_or_create(sid)
    assert any(m.tool_calls for m in stored.messages) and any(
        m.tool_results for m in stored.messages
    )


async def test_text_that_comes_with_a_tool_request_stays_hidden(rig, analytics):
    r = rig(
        [LLMResponse(text="Let me check.", tool_calls=[call("add", a=1, b=1)]), say("It is 2.")]
    )
    async with await _client(r, analytics) as client:
        sid = (await client.post("/chat", json={"message": "1+1?"})).json()["session_id"]
        history = (await client.get(f"/sessions/{sid}/messages")).json()

    assert [m["content"] for m in history] == ["1+1?", "It is 2."]


async def test_an_unknown_session_id_is_an_empty_list(rig, analytics):
    async with await _client(rig([]), analytics) as client:
        response = await client.get("/sessions/does-not-exist/messages")

    assert response.status_code == 200
    assert response.json() == []


async def test_an_overlong_session_id_is_rejected(rig, analytics):
    async with await _client(rig([]), analytics) as client:
        response = await client.get(f"/sessions/{'x' * 65}/messages")

    assert response.status_code == 422


async def test_the_page_keeps_the_session_id_in_session_storage_not_local_storage(rig, analytics):
    async with await _client(rig([]), analytics) as client:
        page = (await client.get("/")).text

    assert "sessionStorage" in page
    assert "localStorage" not in page
    assert "/sessions/" in page  # restores the history on load
