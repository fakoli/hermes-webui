"""Regression coverage for moving and cloning WebUI sessions across profiles."""

import json
import pathlib
import urllib.error
import urllib.request

from tests._pytest_port import BASE, TEST_DEFAULT_MODEL


REPO_ROOT = pathlib.Path(__file__).parent.parent.resolve()


def _post(path, body=None):
    request = urllib.request.Request(
        BASE + path,
        data=json.dumps(body or {}).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.loads(response.read()), response.status
    except urllib.error.HTTPError as error:
        return json.loads(error.read()), error.code


def _get(path):
    with urllib.request.urlopen(BASE + path, timeout=10) as response:
        return json.loads(response.read()), response.status


def _create_persisted_session(title):
    payload, status = _post("/api/session/new", {})
    assert status == 200
    session_id = payload["session"]["session_id"]
    payload, status = _post(
        "/api/session/rename",
        {"session_id": session_id, "title": title},
    )
    assert status == 200
    from api.models import Session

    session = Session.load(session_id)
    assert session is not None
    session.messages = [
        {"role": "user", "content": "preserve this turn", "timestamp": 1.0},
        {"role": "assistant", "content": "preserved reply", "timestamp": 2.0},
    ]
    session.context_messages = list(session.messages)
    session.project_id = "source-project"
    session.gateway_routing = {"strategy": "fallback", "models": ["source-model"]}
    session.gateway_routing_history = [{"model": "source-model"}]
    session.save()
    return session_id


def _create_destination_profile(name, model, provider="openai"):
    payload, status = _post(
        "/api/profile/create",
        {"name": name},
    )
    assert status == 200, payload
    # The network-blocked test catalog intentionally contains only a minimal
    # fallback set, so seed the destination's config directly after exercising
    # the real profile-creation API.
    profile_path = pathlib.Path(payload["profile"]["path"])
    (profile_path / "config.yaml").write_text(
        json.dumps({"model": {"default": model, "provider": provider}}),
        encoding="utf-8",
    )


def _cleanup_session_file(session_id):
    from api.models import SESSION_DIR

    path = SESSION_DIR / f"{session_id}.json"
    path.unlink(missing_ok=True)
    path.with_suffix(".json.bak").unlink(missing_ok=True)


def test_move_session_adopts_destination_profile_routing():
    profile = "transfer-move-target"
    model = TEST_DEFAULT_MODEL
    session_id = None
    _create_destination_profile(profile, model)
    try:
        session_id = _create_persisted_session("Move me")
        from api.models import Session

        crashed = Session.load(session_id)
        assert crashed is not None
        crashed.active_stream_id = "dead-provider-stream"
        crashed.save(touch_updated_at=False)
        payload, status = _post(
            "/api/session/profile-transfer",
            {
                "session_id": session_id,
                "destination_profile": profile,
                "mode": "move",
            },
        )

        assert status == 200, payload
        assert payload["mode"] == "move"
        assert payload["session"]["session_id"] == session_id
        assert payload["session"]["profile"] == profile
        assert payload["session"]["model"] == model
        assert payload["session"]["model_provider"] == "openai"
        assert payload["session"]["project_id"] is None
        assert payload["session"]["messages"][0]["content"] == "preserve this turn"
        assert payload["session"]["gateway_routing"] is None
        assert payload["session"]["gateway_routing_history"] == []
        assert payload["session"]["active_stream_id"] is None

        loaded = Session.load(session_id)
        assert loaded is not None
        assert loaded.title == "Move me"
        assert loaded.profile == profile
    finally:
        if session_id:
            _cleanup_session_file(session_id)
        _post("/api/profile/delete", {"name": profile, "force": True})


def test_clone_session_keeps_original_and_routes_copy_to_destination():
    profile = "transfer-clone-target"
    model = TEST_DEFAULT_MODEL
    source_id = None
    clone_id = None
    _create_destination_profile(profile, model)
    try:
        source_id = _create_persisted_session("Clone me")
        payload, status = _post(
            "/api/session/profile-transfer",
            {
                "session_id": source_id,
                "destination_profile": profile,
                "mode": "clone",
            },
        )

        assert status == 200, payload
        assert payload["mode"] == "clone"
        clone = payload["session"]
        clone_id = clone["session_id"]
        assert clone_id != source_id
        assert clone["title"] == "Clone me (copy)"
        assert clone["profile"] == profile
        assert clone["model"] == model
        assert clone["model_provider"] == "openai"
        assert clone["project_id"] is None
        assert clone["messages"][1]["content"] == "preserved reply"
        assert clone["gateway_routing"] is None
        assert clone["gateway_routing_history"] == []

        from api.models import Session

        original = Session.load(source_id)
        copied = Session.load(clone_id)
        assert original is not None and copied is not None
        assert original.profile == "default"
        assert original.title == "Clone me"
        assert original.project_id == "source-project"
        copied.messages[0]["content"] = "changed only in clone"
        assert original.messages[0]["content"] == "preserve this turn"
    finally:
        if source_id:
            _cleanup_session_file(source_id)
        if clone_id:
            _cleanup_session_file(clone_id)
        _post("/api/profile/delete", {"name": profile, "force": True})


def test_profile_transfer_actions_share_context_and_overflow_menu():
    sessions_js = (REPO_ROOT / "static" / "sessions.js").read_text(encoding="utf-8")
    ui_js = (REPO_ROOT / "static" / "ui.js").read_text(encoding="utf-8")
    index_html = (REPO_ROOT / "static" / "index.html").read_text(encoding="utf-8")

    assert "function _appendSessionProfileTransferActions(" in sessions_js
    assert "t('session_move_profile')" in sessions_js
    assert "t('session_clone_profile')" in sessions_js
    assert "'/api/session/profile-transfer'" in sessions_js
    assert "showSelectDialog" in sessions_js

    transfer_start = sessions_js.index("async function _transferSessionToProfile(")
    transfer_end = sessions_js.index("function _appendSessionProfileTransferActions(", transfer_start)
    transfer_body = sessions_js[transfer_start:transfer_end]
    assert transfer_body.index("if(!destination) return;") < transfer_body.index(
        "await switchToProfile(sourceProfile)"
    ), "cancelling the destination dialog must not switch profiles"

    # Both right-click and the three-dot button already converge on this one
    # action-menu builder, so the profile actions must be appended there.
    menu_start = sessions_js.index("function _openSessionActionMenu(")
    menu_end = sessions_js.index("document.addEventListener('click'", menu_start)
    assert "_appendSessionProfileTransferActions(menu, session)" in sessions_js[menu_start:menu_end]
    assert "_openSessionActionMenu(s, actions||el)" in sessions_js

    assert "function showSelectDialog(opts={})" in ui_js
    assert "appDialogSelect" in ui_js
    assert 'id="appDialogSelect"' in index_html
