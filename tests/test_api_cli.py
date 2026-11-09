import json
import threading
import urllib.request
from http.server import ThreadingHTTPServer

from harrowgate.__main__ import main
from harrowgate.api import assist, make_handler
from harrowgate.system import System
from harrowgate.world import default_world


def test_assist_validates_input():
    s = System(default_world())
    assert assist({"passenger_id": "P-9999", "text": "hi"}, s)[0] == 404
    assert assist({"passenger_id": "P-1001", "text": "x" * 501}, s)[0] == 400
    assert assist({"passenger_id": "P-1001", "text": "hi", "admin": True}, s)[0] == 400


def test_assist_answers_without_personal_data():
    code, body = assist({"passenger_id": "P-1001", "text": "Which gate is SK204?"}, System(default_world()))
    assert code == 200 and body["destination"] == "B4" and "Asha" not in json.dumps(body)


def test_http_round_trip():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(System(default_world())))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        base = f"http://127.0.0.1:{srv.server_address[1]}"
        assert json.loads(urllib.request.urlopen(base + "/healthz").read()) == {"ok": True}
        req = urllib.request.Request(base + "/v1/assist", method="POST",
                                     data=json.dumps({"passenger_id": "P-1002", "text": "Is BF117 on time?"}).encode())
        assert json.loads(urllib.request.urlopen(req).read())["destination"] == "C3"
    finally:
        srv.shutdown()


def test_cli_ask(capsys):
    assert main(["ask", "P-1001", "Which gate is SK204?"]) == 0
    assert "B4" in capsys.readouterr().out
