def test_register_returns_global_response(client):
    response = client.post(
        "/api/v1/auth/register",
        json={"email": "foldercheck@example.com", "password": "Password123"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert "data" in body
    assert "access_token" in body["data"]
