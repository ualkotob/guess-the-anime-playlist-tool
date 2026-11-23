"""Local browser control works without a public tunnel."""

import socket
from types import SimpleNamespace

from core.game_state import state
from _app_scripts.file.web_server import web_client_html, web_server
from _app_scripts.bonus import answers
from _app_scripts.data import config_io
from _app_scripts.ui import menu_registry

assert web_client_html.HTML


def test_auto_start_works_without_tunnel(monkeypatch):
    calls = []
    scheduled = []
    monkeypatch.setattr(state.config, "WEB_SERVER_ENABLED", True)
    monkeypatch.setattr(state.config, "NGROK_DOMAIN", "")
    monkeypatch.setattr(state.config, "CLOUDFLARE_TUNNEL_TOKEN", "")
    monkeypatch.setattr(state.config, "CLOUDFLARE_PUBLIC_URL", "")
    monkeypatch.setattr(state.widgets, "root", SimpleNamespace(after=lambda delay, fn: scheduled.append((delay, fn))))
    monkeypatch.setattr(answers, "_web_poll_started", False)
    monkeypatch.setattr(web_server, "NGROK_AVAILABLE", False)
    monkeypatch.setattr(web_server, "CLOUDFLARED_AVAILABLE", False)
    monkeypatch.setattr(web_server, "start", lambda **kwargs: calls.append(kwargs) or True)

    answers._start_web_server()

    assert calls == [{"port": 8080, "ngrok_domain": None,
                      "cloudflare_token": None, "cloudflare_url": None}]
    assert scheduled == [(1000, answers._poll_web_answers)]


def test_local_url_and_menu_remain_available_with_public_tunnel(monkeypatch):
    monkeypatch.setattr(web_server, "_server_started", True)
    monkeypatch.setattr(web_server, "_server_port", 8080)
    monkeypatch.setattr(web_server, "public_url", "https://example.test")
    monkeypatch.setattr(web_server, "get_local_url", lambda: "http://192.168.1.10:8080")
    assert web_server.get_url() == "https://example.test"

    entries = menu_registry.get_menu_registry()["file"]
    local_entry = next(item for item in entries if isinstance(item, dict) and item.get("id") == "copy_local_web_url")
    assert local_entry["condition"]()
    assert "192.168.1.10:8080" in local_entry["label"]()


def test_local_url_uses_lan_address_without_tunnel(monkeypatch):
    class FakeSocket:
        def settimeout(self, _timeout):
            pass

        def connect(self, _target):
            pass

        def getsockname(self):
            return ("192.168.1.10", 12345)

        def close(self):
            pass

    monkeypatch.setattr(socket, "socket", lambda *_args: FakeSocket())
    monkeypatch.setattr(web_server, "_server_started", True)
    monkeypatch.setattr(web_server, "_server_port", 8080)
    monkeypatch.setattr(web_server, "public_url", None)

    assert web_server.get_url() == "http://192.168.1.10:8080"


def test_local_controls_are_visible_and_enabled_by_default():
    settings = {item["key"]: item for item in config_io.SETTINGS_SCHEMA}
    assert settings["WEB_SERVER_ENABLED"]["default"] is True
    assert "requires_tunnel" not in settings["WEB_SERVER_ENABLED"]
    assert "requires_tunnel" not in settings["HOST_PASSWORD"]


def test_open_local_web_ui_uses_loopback_with_a_public_tunnel(monkeypatch):
    opened = []
    monkeypatch.setattr(web_server, "_server_started", True)
    monkeypatch.setattr(web_server, "_server_port", 8090)
    monkeypatch.setattr(web_server, "public_url", "https://example.test")
    monkeypatch.setattr(menu_registry.webbrowser, "open", opened.append)

    entries = menu_registry.get_menu_registry()["file"]
    entry = next(item for item in entries if isinstance(item, dict) and item.get("id") == "open_local_web_ui")
    assert entry["condition"]()
    entry["command"]()
    assert opened == ["http://127.0.0.1:8090"]


def test_local_page_serves_the_socket_io_browser_bundle(monkeypatch):
    monkeypatch.setattr(web_server, "_app", None)
    monkeypatch.setattr(web_server, "_socketio", None)
    web_server._build_app()
    client = web_server._app.test_client()

    page = client.get("/")
    assert page.status_code == 200
    assert b'src="/assets/socket.io-4.7.5.min.js"' in page.data
    assert b'cdn.socket.io' not in page.data

    javascript = client.get("/assets/socket.io-4.7.5.min.js")
    assert javascript.status_code == 200
    assert javascript.mimetype == "text/javascript"
    assert b'Socket.IO v4.7.5' in javascript.data


def test_public_info_keeps_anilist_details_for_broadcasts_and_new_clients(monkeypatch):
    monkeypatch.setattr(web_server, '_app', None)
    monkeypatch.setattr(web_server, '_socketio', None)
    monkeypatch.setattr(web_server, '_current_metadata', {})
    monkeypatch.setattr(web_server, '_info_public', False)
    monkeypatch.setattr(web_server, 'open_vote_skip', lambda: None)
    web_server._build_app()
    socketio = web_server._socketio
    client = socketio.test_client(web_server._app)

    data = {'title': 'Example', 'score': 8.1, 'anilist_id': 12, 'anilist_score': '82%',
            'anilist_tags': [{'name': 'Example tag'}], 'anilist_characters': [{'name': 'Example character'}]}
    expected = {'show': True, 'metadata': data}

    def revealed_metadata(client):
        return next(event['args'][0] for event in client.get_received() if event['name'] == 'info_public_update')

    web_server.push_metadata(data)
    web_server.set_info_public(True)
    assert revealed_metadata(client) == expected
    web_server.push_metadata(data)
    assert revealed_metadata(client) == expected
    late_client = socketio.test_client(web_server._app)
    assert revealed_metadata(late_client) == expected
