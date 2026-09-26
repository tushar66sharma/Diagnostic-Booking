def test_error_responses_are_documented(client):
    paths = client.get("/openapi.json").json()["paths"]

    assert {"401", "404"} <= paths["/bookings/{booking_id}/"]["get"]["responses"].keys()
    assert {"401", "404", "409"} <= paths["/payments/"]["post"]["responses"].keys()
    assert {"401", "403", "404"} <= paths["/centres/{centre_id}/"]["patch"]["responses"].keys()
    assert "429" in paths["/auth/login/"]["post"]["responses"]


def test_webhook_request_body_is_documented(client):
    webhook = client.get("/openapi.json").json()["paths"]["/payments/webhook/"]["post"]

    schema = webhook["requestBody"]["content"]["application/json"]["schema"]
    assert set(schema["required"]) == {"event_id", "provider_ref", "status"}
    assert any(p["name"] == "x-signature" for p in webhook["parameters"])
