from unittest.mock import patch, MagicMock


def _mock_player(available=True, value=1_000_000):
    mock = MagicMock()
    mock.status_code = 200
    mock.json.return_value = {"id": 10, "name": "Jogador Teste", "available": available, "value": value}
    mock.raise_for_status = MagicMock()
    return mock


def test_get_leagues(client):
    response = client.get("/leagues")
    assert response.status_code == 200
    assert "leagues" in response.get_json()
    assert len(response.get_json()["leagues"]) > 0


def test_get_clube_404(client):
    response = client.get("/clube/get/999")
    assert response.status_code == 404


def test_create_and_get_clube_and_delete_clube(client):
    create_response = client.post("/clube/create", json={
        "name": "FC Pedro",
        "league": "Premier League",
        "budget": 50_000_000
    })
    assert create_response.status_code == 201

    created = create_response.get_json()
    assert created["name"] == "FC Pedro"
    assert created["league"] == "Premier League"
    assert created["budget"] == 50_000_000
    assert "id" in created

    club_id = created["id"]

    get_response = client.get(f"/clube/get/{club_id}")
    assert get_response.status_code == 200

    fetched = get_response.get_json()
    assert fetched["id"] == club_id
    assert fetched["name"] == "FC Pedro"
    assert fetched["league"] == "Premier League"

    delete_response = client.delete(f"/clube/delete/{club_id}")
    assert delete_response.status_code == 200

    get_after_delete = client.get(f"/clube/get/{club_id}")
    assert get_after_delete.status_code == 404


def test_create_and_delete_clube(client):
    create_response = client.post("/clube/create", json={
        "name": "FC Maria",
        "league": "La Liga"
    })
    assert create_response.status_code == 201

    club_id = create_response.get_json()["id"]

    delete_response = client.delete(f"/clube/delete/{club_id}")
    assert delete_response.status_code == 200

    get_response = client.get(f"/clube/get/{club_id}")
    assert get_response.status_code == 404


def test_create_two_clubes_and_list_and_delete_both(client):
    response1 = client.post("/clube/create", json={
        "name": "FC Joao",
        "league": "Serie A"
    })
    assert response1.status_code == 201
    club1 = response1.get_json()

    response2 = client.post("/clube/create", json={
        "name": "FC Ana",
        "league": "Bundesliga"
    })
    assert response2.status_code == 201
    club2 = response2.get_json()

    list_response = client.get("/clube/get")
    assert list_response.status_code == 200

    clubes = list_response.get_json()
    assert len(clubes) == 2

    ids = [c["id"] for c in clubes]
    assert club1["id"] in ids
    assert club2["id"] in ids

    assert client.delete(f"/clube/delete/{club1['id']}").status_code == 200
    assert client.delete(f"/clube/delete/{club2['id']}").status_code == 200

    final_list = client.get("/clube/get")
    assert final_list.status_code == 200
    assert final_list.get_json() == []


def test_create_clube_invalid_league(client):
    response = client.post("/clube/create", json={
        "name": "FC Invalido",
        "league": "Liga Inventada"
    })
    assert response.status_code == 400
    assert "available" in response.get_json()


def test_create_clube_duplicate_name(client):
    client.post("/clube/create", json={"name": "FC Dup", "league": "Ligue 1"})

    response = client.post("/clube/create", json={"name": "FC Dup", "league": "Ligue 1"})
    assert response.status_code == 409


def test_create_and_update_clube(client):
    create_response = client.post("/clube/create", json={
        "name": "FC Update",
        "league": "La Liga",
        "budget": 10_000_000
    })
    assert create_response.status_code == 201
    club_id = create_response.get_json()["id"]

    update_response = client.put(f"/clube/update/{club_id}", json={"budget": 99_000_000})
    assert update_response.status_code == 200
    assert update_response.get_json()["budget"] == 99_000_000

    get_response = client.get(f"/clube/get/{club_id}")
    assert get_response.get_json()["budget"] == 99_000_000


def test_buy_player_and_check_budget(client):
    create_response = client.post("/clube/create", json={
        "name": "FC Buy",
        "league": "Premier League",
        "budget": 5_000_000
    })
    assert create_response.status_code == 201
    club_id = create_response.get_json()["id"]

    with patch("main.requests.get", return_value=_mock_player(available=True, value=1_000_000)), \
         patch("main.requests.patch"):
        buy_response = client.post("/clube/buy", json={"club_id": club_id, "player_id": 10})

    assert buy_response.status_code == 200
    data = buy_response.get_json()
    assert data["price_paid"] == 1_000_000
    assert data["remaining_budget"] == 4_000_000

    players_response = client.get(f"/clube/{club_id}/players")
    assert players_response.status_code == 200
    assert len(players_response.get_json()["players"]) == 1


def test_buy_and_sell_player(client):
    create_response = client.post("/clube/create", json={
        "name": "FC BuySell",
        "league": "Brasileirão Série A",
        "budget": 5_000_000
    })
    assert create_response.status_code == 201
    club_id = create_response.get_json()["id"]

    with patch("main.requests.get", return_value=_mock_player(available=True, value=1_000_000)), \
         patch("main.requests.patch"):
        client.post("/clube/buy", json={"club_id": club_id, "player_id": 10})

    with patch("main.requests.get", return_value=_mock_player(value=1_200_000)), \
         patch("main.requests.patch"):
        sell_response = client.post("/clube/sell", json={"club_id": club_id, "player_id": 10})

    assert sell_response.status_code == 200
    assert sell_response.get_json()["sell_price"] == 1_200_000
    assert sell_response.get_json()["new_budget"] == 5_200_000

    players_response = client.get(f"/clube/{club_id}/players")
    assert len(players_response.get_json()["players"]) == 0


def test_buy_player_insufficient_budget(client):
    create_response = client.post("/clube/create", json={
        "name": "FC Poor",
        "league": "Primeira Liga",
        "budget": 500_000
    })
    assert create_response.status_code == 201
    club_id = create_response.get_json()["id"]

    with patch("main.requests.get", return_value=_mock_player(available=True, value=1_000_000)):
        response = client.post("/clube/buy", json={"club_id": club_id, "player_id": 10})

    assert response.status_code == 400
    assert "Insufficient budget" in response.get_json()["error"]


def test_sell_player_not_in_clube(client):
    create_response = client.post("/clube/create", json={
        "name": "FC NoPlayer",
        "league": "Serie A"
    })
    assert create_response.status_code == 201
    club_id = create_response.get_json()["id"]

    response = client.post("/clube/sell", json={"club_id": club_id, "player_id": 99})
    assert response.status_code == 404
