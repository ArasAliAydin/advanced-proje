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


def test_v3_web_assets(client):
    """v3: dil dosyası ve Yönetim ekranları ayrı dosyalarda; sayfa üçünü de yükler."""
    page = client.get("/").text
    for name in ("i18n.js", "app.js", "admin.js"):
        assert f"/static/{name}" in page
        r = client.get(f"/static/{name}")
        assert r.status_code == 200 and "javascript" in r.headers["content-type"]
    assert "theme-toggle" in page and "lang-toggle" in page
    i18n = client.get("/static/i18n.js").text
    assert '"nav.admin": ["Yönetim", "Admin"]' in i18n
