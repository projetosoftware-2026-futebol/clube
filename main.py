import os
import requests
from flask import Flask, jsonify, request
from werkzeug.utils import secure_filename
from db import db
from models import Club, ClubPlayer, LEAGUES

PLAYERS_API_URL = os.environ.get("JOGADOR_URL", "http://localhost:5002")
UPLOAD_FOLDER = os.environ.get("UPLOAD_FOLDER", "uploads")
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def create_app(test_config=None):
    app = Flask(__name__)

    db_host = os.environ.get("MYSQL_HOST", "localhost")
    db_port = os.environ.get("MYSQL_PORT", "3306")
    db_user = os.environ.get("MYSQL_USER", "root")
    db_password = os.environ.get("MYSQL_PASSWORD", "football-password")
    db_name = os.environ.get("MYSQL_DATABASE", "football")

    app.config["SQLALCHEMY_DATABASE_URI"] = (
        f"mysql+pymysql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"
    )
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

    if test_config:
        app.config.update(test_config)

    os.makedirs(UPLOAD_FOLDER, exist_ok=True)

    db.init_app(app)

    # ── Ligas disponíveis ──────────────────────────────────────────────────────

    @app.route("/leagues", methods=["GET"])
    def get_leagues():
        return jsonify({"leagues": LEAGUES}), 200

    # ── GET /clube/get  →  lista todos os clubes ───────────────────────────────

    @app.route("/clube/get", methods=["GET"])
    def get_clubs():
        clubs = Club.query.all()
        return jsonify([c.to_dict() for c in clubs]), 200

    # ── GET /clube/get/<id>  →  detalhe do clube com jogadores ────────────────

    @app.route("/clube/get/<int:club_id>", methods=["GET"])
    def get_club(club_id):
        club = db.session.get(Club, club_id)
        if not club:
            return jsonify({"error": "Club not found"}), 404
        return jsonify(club.to_dict_full()), 200

    # ── POST /clube/create  →  cria um clube ──────────────────────────────────

    @app.route("/clube/create", methods=["POST"])
    def create_club():
        name = request.form.get("name") or (request.json or {}).get("name")
        league = request.form.get("league") or (request.json or {}).get("league")
        budget = request.form.get("budget") or (request.json or {}).get("budget", 10_000_000.0)
        image_url = (request.json or {}).get("image_url") if request.is_json else None

        if not name or not league:
            return jsonify({"error": "name and league are required"}), 400

        if league not in LEAGUES:
            return jsonify({"error": "Invalid league", "available": LEAGUES}), 400

        if Club.query.filter_by(name=name).first():
            return jsonify({"error": "Club name already exists"}), 409

        file = request.files.get("image")
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)
            file.save(filepath)
            image_url = f"/uploads/{filename}"

        try:
            club = Club(name=name, league=league, budget=float(budget), image_url=image_url)
            db.session.add(club)
            db.session.commit()
            return jsonify(club.to_dict()), 201
        except Exception as e:
            db.session.rollback()
            return jsonify({"error": str(e)}), 500

    # ── PUT /clube/update/<id>  →  atualiza clube ─────────────────────────────

    @app.route("/clube/update/<int:club_id>", methods=["PUT"])
    def update_club(club_id):
        club = db.session.get(Club, club_id)
        if not club:
            return jsonify({"error": "Club not found"}), 404

        name = request.form.get("name") or (request.json or {}).get("name")
        league = request.form.get("league") or (request.json or {}).get("league")
        budget = request.form.get("budget") or (request.json or {}).get("budget")
        image_url = (request.json or {}).get("image_url") if request.is_json else None

        if league and league not in LEAGUES:
            return jsonify({"error": "Invalid league", "available": LEAGUES}), 400

        if name and name != club.name and Club.query.filter_by(name=name).first():
            return jsonify({"error": "Club name already exists"}), 409

        file = request.files.get("image")
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)
            file.save(filepath)
            image_url = f"/uploads/{filename}"

        try:
            if name:
                club.name = name
            if league:
                club.league = league
            if budget is not None:
                club.budget = float(budget)
            if image_url:
                club.image_url = image_url
            db.session.commit()
            return jsonify(club.to_dict()), 200
        except Exception as e:
            db.session.rollback()
            return jsonify({"error": str(e)}), 500

    # ── DELETE /clube/delete/<id>  →  deleta clube ────────────────────────────

    @app.route("/clube/delete/<int:club_id>", methods=["DELETE"])
    def delete_club(club_id):
        club = db.session.get(Club, club_id)
        if not club:
            return jsonify({"error": "Club not found"}), 404

        try:
            db.session.delete(club)
            db.session.commit()
            return jsonify({"message": "Club deleted"}), 200
        except Exception as e:
            db.session.rollback()
            return jsonify({"error": str(e)}), 500

    # ── GET /clube/<id>/players  →  jogadores do clube ────────────────────────

    @app.route("/clube/<int:club_id>/players", methods=["GET"])
    def get_club_players(club_id):
        club = db.session.get(Club, club_id)
        if not club:
            return jsonify({"error": "Club not found"}), 404
        return jsonify({"club": club.name, "players": [p.to_dict() for p in club.players]}), 200

    # ── POST /clube/buy  →  compra jogador da API de jogadores ───────────────
    # Body: { "club_id": 1, "player_id": 10 }

    @app.route("/clube/buy", methods=["POST"])
    def buy_player():
        data = request.get_json()
        if not data or "club_id" not in data or "player_id" not in data:
            return jsonify({"error": "club_id and player_id are required"}), 400

        club_id = data["club_id"]
        player_id = data["player_id"]

        club = db.session.get(Club, club_id)
        if not club:
            return jsonify({"error": "Club not found"}), 404

        if ClubPlayer.query.filter_by(club_id=club_id, player_id=player_id).first():
            return jsonify({"error": "Player already in this club"}), 409

        try:
            response = requests.get(f"{PLAYERS_API_URL}/players/{player_id}", timeout=5)
            if response.status_code == 404:
                return jsonify({"error": "Player not found"}), 404
            response.raise_for_status()
            player_data = response.json()
        except requests.exceptions.ConnectionError:
            return jsonify({"error": "Players API unavailable"}), 503
        except Exception as e:
            return jsonify({"error": f"Players API error: {str(e)}"}), 502

        if not player_data.get("available", True):
            return jsonify({"error": "Player is not available for transfer"}), 400

        price = float(player_data.get("value", 0))

        if club.budget < price:
            return jsonify({
                "error": "Insufficient budget",
                "budget": club.budget,
                "player_price": price,
            }), 400

        try:
            club.budget -= price
            cp = ClubPlayer(club_id=club_id, player_id=player_id, purchase_price=price)
            db.session.add(cp)
            db.session.commit()

            try:
                requests.patch(
                    f"{PLAYERS_API_URL}/players/{player_id}",
                    json={"club_id": club_id, "available": False},
                    timeout=5,
                )
            except Exception:
                pass

            return jsonify({
                "message": "Player bought successfully",
                "player_id": player_id,
                "price_paid": price,
                "remaining_budget": club.budget,
            }), 200
        except Exception as e:
            db.session.rollback()
            return jsonify({"error": str(e)}), 500

    # ── POST /clube/sell  →  vende jogador de volta ao mercado ───────────────
    # Body: { "club_id": 1, "player_id": 10 }

    @app.route("/clube/sell", methods=["POST"])
    def sell_player():
        data = request.get_json()
        if not data or "club_id" not in data or "player_id" not in data:
            return jsonify({"error": "club_id and player_id are required"}), 400

        club_id = data["club_id"]
        player_id = data["player_id"]

        club = db.session.get(Club, club_id)
        if not club:
            return jsonify({"error": "Club not found"}), 404

        cp = ClubPlayer.query.filter_by(club_id=club_id, player_id=player_id).first()
        if not cp:
            return jsonify({"error": "Player does not belong to this club"}), 404

        sell_price = cp.purchase_price
        try:
            response = requests.get(f"{PLAYERS_API_URL}/players/{player_id}", timeout=5)
            if response.status_code == 200:
                sell_price = float(response.json().get("value", cp.purchase_price))
        except Exception:
            pass

        try:
            club.budget += sell_price
            db.session.delete(cp)
            db.session.commit()

            try:
                requests.patch(
                    f"{PLAYERS_API_URL}/players/{player_id}",
                    json={"club_id": None, "available": True},
                    timeout=5,
                )
            except Exception:
                pass

            return jsonify({
                "message": "Player sold successfully",
                "player_id": player_id,
                "sell_price": sell_price,
                "new_budget": club.budget,
            }), 200
        except Exception as e:
            db.session.rollback()
            return jsonify({"error": str(e)}), 500

    with app.app_context():
        db.create_all()

    return app


if __name__ == "__main__":
    app = create_app()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
