def _auth_headers(access_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token}"}


def test_register_login_and_me(client):
    register_resp = client.post(
        "/api/v1/auth/register",
        json={"email": "user@example.com", "password": "Password123"},
    )
    assert register_resp.status_code == 200
    body = register_resp.json()
    assert body["success"] is True
    token_payload = body["data"]
    assert "access_token" in token_payload
    assert "refresh_token" in token_payload

    me_resp = client.get("/api/v1/auth/me", headers=_auth_headers(token_payload["access_token"]))
    assert me_resp.status_code == 200
    assert me_resp.json()["data"]["email"] == "user@example.com"

    login_resp = client.post(
        "/api/v1/auth/login",
        json={"email": "user@example.com", "password": "Password123"},
    )
    assert login_resp.status_code == 200
    assert "access_token" in login_resp.json()["data"]


def test_watchlist_crud_duplicate_and_limit(client):
    register_resp = client.post(
        "/api/v1/auth/register",
        json={"email": "watcher@example.com", "password": "Password123"},
    )
    token = register_resp.json()["data"]["access_token"]
    headers = _auth_headers(token)

    add_resp = client.post(
        "/api/v1/watchlist",
        json={"symbol": "tcs", "exchange": "NSE"},
        headers=headers,
    )
    assert add_resp.status_code == 201
    assert add_resp.json()["data"]["symbol"] == "TCS"

    dup_resp = client.post(
        "/api/v1/watchlist",
        json={"symbol": "TCS", "exchange": "NSE"},
        headers=headers,
    )
    assert dup_resp.status_code == 409
    assert dup_resp.json()["success"] is False

    for i in range(2, 16):
        resp = client.post(
            "/api/v1/watchlist",
            json={"symbol": f"STK{i}", "exchange": "NSE"},
            headers=headers,
        )
        assert resp.status_code == 201

    limit_resp = client.post(
        "/api/v1/watchlist",
        json={"symbol": "EXTRA", "exchange": "NSE"},
        headers=headers,
    )
    assert limit_resp.status_code == 400
    assert limit_resp.json()["success"] is False

    list_resp = client.get("/api/v1/watchlist", headers=headers)
    assert list_resp.status_code == 200
    assert len(list_resp.json()["data"]) == 15

    stock_id = list_resp.json()["data"][0]["id"]
    delete_resp = client.delete(f"/api/v1/watchlist/{stock_id}", headers=headers)
    assert delete_resp.status_code == 200
    assert delete_resp.json()["success"] is True


def test_watchlist_accepts_company_name(client):
    register_resp = client.post(
        "/api/v1/auth/register",
        json={"email": "namecheck@example.com", "password": "Password123"},
    )
    token = register_resp.json()["data"]["access_token"]
    headers = _auth_headers(token)

    add_resp = client.post(
        "/api/v1/watchlist",
        json={"symbol": "Tata  Motors", "exchange": "NSE"},
        headers=headers,
    )
    assert add_resp.status_code == 201
    assert add_resp.json()["data"]["symbol"] == "TATA MOTORS"

    dup_resp = client.post(
        "/api/v1/watchlist",
        json={"symbol": "tata motors", "exchange": "NSE"},
        headers=headers,
    )
    assert dup_resp.status_code == 409


def test_refresh_and_logout(client):
    register_resp = client.post(
        "/api/v1/auth/register",
        json={"email": "rotate@example.com", "password": "Password123"},
    )
    initial_refresh = register_resp.json()["data"]["refresh_token"]

    refresh_resp = client.post("/api/v1/auth/refresh", json={"refresh_token": initial_refresh})
    assert refresh_resp.status_code == 200
    rotated_refresh = refresh_resp.json()["data"]["refresh_token"]

    logout_resp = client.post("/api/v1/auth/logout", json={"refresh_token": rotated_refresh})
    assert logout_resp.status_code == 200
    assert logout_resp.json()["success"] is True

    refresh_after_logout_resp = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": rotated_refresh},
    )
    assert refresh_after_logout_resp.status_code == 401


def test_validation_error_is_standardized(client):
    invalid_resp = client.post(
        "/api/v1/auth/register",
        json={"email": "invalid-email", "password": "short"},
    )
    assert invalid_resp.status_code == 422
    body = invalid_resp.json()
    assert body["success"] is False
    assert body["error"]["code"] == "VALIDATION_ERROR"
