def test_root_serves_web_ui(client):
    r = client.get("/")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    assert "<title>StudySpot</title>" in r.text and "/static/app.js" in r.text


def test_static_assets_and_swagger(client):
    js = client.get("/static/app.js")
    assert js.status_code == 200 and "javascript" in js.headers["content-type"]
    assert 'const API = "/api/v1"' in js.text
    assert client.get("/static/style.css").headers["content-type"].startswith("text/css")
    assert client.get("/docs").status_code == 200
    assert client.get("/static/yok.js").status_code == 404
