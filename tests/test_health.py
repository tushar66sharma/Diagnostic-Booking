def test_health_reports_ok_and_request_id(client):
    res = client.get("/health", headers={"X-Request-ID": "abc123"})

    assert res.status_code == 200
    assert res.json() == {"status": "ok"}
    assert res.headers["X-Request-ID"] == "abc123"
