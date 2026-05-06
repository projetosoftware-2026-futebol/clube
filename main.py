import os
import requests
from flask import Flask, jsonify, request
from sqlalchemy import inspect, text
from werkzeug.utils import secure_filename
from db import db
from models import Club, ClubPlayer, LEAGUES

try:
    import jwt
    from jwt import InvalidTokenError, PyJWKClient
except ImportError:
    jwt = None
    InvalidTokenError = Exception
    PyJWKClient = None

PLAYERS_API_URL = os.environ.get("JOGADOR_URL", "http://localhost:5002")
UPLOAD_FOLDER = os.environ.get("UPLOAD_FOLDER", "uploads")
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}
INSECURE_USER_HEADERS = ("X-User-Id", "X-Auth-User", "X-Authenticated-User")


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

    class AuthError(Exception):
        def __init__(self, message, status_code=401):
            super().__init__(message)
            self.message = message
            self.status_code = status_code

    jwks_client_cache = {"url": None, "client": None}

    @app.errorhandler(AuthError)
    def handle_auth_error(error):
        return jsonify({"error": error.message}), error.status_code

    def config_or_env(name, default=None):
        return app.config.get(name) or os.environ.get(name) or default

    def is_truthy(value):
        if isinstance(value, bool):
            return value
        if value is None:
            return False
        return str(value).strip().lower() in {"1", "true", "yes", "on"}

    def insecure_auth_headers_allowed():
        return is_truthy(config_or_env("ALLOW_INSECURE_AUTH_HEADERS"))

    def user_id_from_insecure_header():
        if not insecure_auth_headers_allowed():
            return None

        for header in INSECURE_USER_HEADERS:
            value = request.headers.get(header)
            if value and value.strip():
                return value.strip()

        return None

    def bearer_token():
        auth_header = request.headers.get("Authorization", "")
        parts = auth_header.split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            return parts[1]
        return None

    def auth0_issuer_and_audience():
        domain = config_or_env("AUTH0_DOMAIN") or config_or_env("VITE_AUTH0_DOMAIN")
        audience = config_or_env("AUTH0_AUDIENCE") or config_or_env("VITE_AUTH0_AUDIENCE")

        if not domain:
            return None, audience

        domain = domain.rstrip("/")
        issuer = f"{domain}/" if domain.startswith("http") else f"https://{domain}/"
        return issuer, audience

    def verified_user_id_from_token(token):
        issuer, audience = auth0_issuer_and_audience()
        if not issuer:
            raise AuthError("Authentication is not configured", 500)
        if jwt is None or PyJWKClient is None:
            raise AuthError("JWT support is not installed", 500)

        jwks_url = f"{issuer}.well-known/jwks.json"
        if jwks_client_cache["url"] != jwks_url:
            jwks_client_cache["url"] = jwks_url
            jwks_client_cache["client"] = PyJWKClient(jwks_url)

        try:
            signing_key = jwks_client_cache["client"].get_signing_key_from_jwt(token)
            decode_options = {}
            decode_kwargs = {
                "algorithms": ["RS256"],
                "issuer": issuer,
            }
            if audience:
                decode_kwargs["audience"] = audience
            else:
                decode_options["verify_aud"] = False
            if decode_options:
                decode_kwargs["options"] = decode_options

            payload = jwt.decode(token, signing_key.key, **decode_kwargs)
        except InvalidTokenError:
            raise AuthError("Invalid authentication token", 401)
        except Exception:
            raise AuthError("Unable to validate authentication token", 401)

        user_id = payload.get("sub")
        if not user_id:
            raise AuthError("Authentication token has no subject", 401)

        return user_id

    def current_user_id(required=True):
        header_user_id = user_id_from_insecure_header()
        if header_user_id:
            return header_user_id

        token = bearer_token()
        if not token:
            if required:
                raise AuthError("Authentication required", 401)
            return None

        try:
            return verified_user_id_from_token(token)
        except AuthError as error:
            if not required and error.status_code == 500:
                return None
            raise

    def require_club_owner(club, user_id):
        if not club.owner_user_id:
            raise AuthError("Club has no owner and cannot be edited", 403)
        if club.owner_user_id != user_id:
            raise AuthError("You can only edit clubs created by your user", 403)

    def club_payload(club, user_id=None, full=False):
        data = club.to_dict_full() if full else club.to_dict()
        if user_id is not None:
            data["is_owner"] = club.owner_user_id == user_id
        return data

    def player_is_available(player_data):
        if "status" in player_data:
            return player_data.get("status") == "DISPONIVEL"
        if "available" in player_data:
            return bool(player_data.get("available"))
        return False

    def player_value(player_data, default=0):
        return float(
            player_data.get(
                "valor",
                player_data.get("value", player_data.get("preco", default)),
            )
        )

    def ensure_owner_user_id_column():
        inspector = inspect(db.engine)
        if "clubs" not in inspector.get_table_names():
            return

        columns = {column["name"] for column in inspector.get_columns("clubs")}
        if "owner_user_id" not in columns:
            with db.engine.begin() as connection:
                connection.execute(text("ALTER TABLE clubs ADD COLUMN owner_user_id VARCHAR(255)"))

        inspector = inspect(db.engine)
        index_names = {index["name"] for index in inspector.get_indexes("clubs")}
        if "ix_clubs_owner_user_id" not in index_names:
            with db.engine.begin() as connection:
                connection.execute(text("CREATE INDEX ix_clubs_owner_user_id ON clubs (owner_user_id)"))

    # ── Ligas disponíveis ──────────────────────────────────────────────────────

    @app.route("/clube/leagues", methods=["GET"])
    def get_leagues():
        return jsonify({"leagues": LEAGUES}), 200

    # ── GET /clube/get  →  lista todos os clubes ───────────────────────────────

    @app.route("/clube/get", methods=["GET"])
    def get_clubs():
        user_id = current_user_id(required=False)
        clubs = Club.query.all()
        return jsonify([club_payload(c, user_id) for c in clubs]), 200

    # ── GET /clube/get/<id>  →  detalhe do clube com jogadores ────────────────

    @app.route("/clube/get/<int:club_id>", methods=["GET"])
    def get_club(club_id):
        user_id = current_user_id(required=False)
        club = db.session.get(Club, club_id)
        if not club:
            return jsonify({"error": "Club not found"}), 404
        return jsonify(club_payload(club, user_id, full=True)), 200

    # ── POST /clube/create  →  cria um clube ──────────────────────────────────

    @app.route("/clube/create", methods=["POST"])
    def create_club():
        user_id = current_user_id()
        data = request.get_json(silent=True) or {}
        name = request.form.get("name") or data.get("name")
        league = request.form.get("league") or data.get("league")
        budget = request.form.get("budget") or data.get("budget", 10_000_000.0)
        image_url = data.get("image_url") if request.is_json else None

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
            club = Club(
                name=name,
                league=league,
                budget=float(budget),
                image_url=image_url,
                owner_user_id=user_id,
            )
            db.session.add(club)
            db.session.commit()
            return jsonify(club_payload(club, user_id)), 201
        except Exception as e:
            db.session.rollback()
            return jsonify({"error": str(e)}), 500

    # ── PUT /clube/update/<id>  →  atualiza clube ─────────────────────────────

    @app.route("/clube/update/<int:club_id>", methods=["PUT"])
    def update_club(club_id):
        user_id = current_user_id()
        club = db.session.get(Club, club_id)
        if not club:
            return jsonify({"error": "Club not found"}), 404
        require_club_owner(club, user_id)

        data = request.get_json(silent=True) or {}
        name = request.form.get("name") or data.get("name")
        league = request.form.get("league") or data.get("league")
        budget = request.form.get("budget") or data.get("budget")
        image_url = data.get("image_url") if request.is_json else None

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
            return jsonify(club_payload(club, user_id)), 200
        except Exception as e:
            db.session.rollback()
            return jsonify({"error": str(e)}), 500

    # ── DELETE /clube/delete/<id>  →  deleta clube ────────────────────────────

    @app.route("/clube/delete/<int:club_id>", methods=["DELETE"])
    def delete_club(club_id):
        user_id = current_user_id()
        club = db.session.get(Club, club_id)
        if not club:
            return jsonify({"error": "Club not found"}), 404
        require_club_owner(club, user_id)

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
        user_id = current_user_id()
        data = request.get_json(silent=True)
        if not data or "club_id" not in data or "player_id" not in data:
            return jsonify({"error": "club_id and player_id are required"}), 400

        club_id = data["club_id"]
        player_id = data["player_id"]

        club = db.session.get(Club, club_id)
        if not club:
            return jsonify({"error": "Club not found"}), 404
        require_club_owner(club, user_id)

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

        if not player_is_available(player_data):
            return jsonify({"error": "Player is not available for transfer"}), 400

        price = player_value(player_data)

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
                requests.post(
                    f"{PLAYERS_API_URL}/players/{player_id}/buy",
                    json={"clube_id": club_id},
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
        user_id = current_user_id()
        data = request.get_json(silent=True)
        if not data or "club_id" not in data or "player_id" not in data:
            return jsonify({"error": "club_id and player_id are required"}), 400

        club_id = data["club_id"]
        player_id = data["player_id"]

        club = db.session.get(Club, club_id)
        if not club:
            return jsonify({"error": "Club not found"}), 404
        require_club_owner(club, user_id)

        cp = ClubPlayer.query.filter_by(club_id=club_id, player_id=player_id).first()
        if not cp:
            return jsonify({"error": "Player does not belong to this club"}), 404

        sell_price = cp.purchase_price
        try:
            response = requests.get(f"{PLAYERS_API_URL}/players/{player_id}", timeout=5)
            if response.status_code == 200:
                sell_price = player_value(response.json(), cp.purchase_price)
        except Exception:
            pass

        try:
            club.budget += sell_price
            db.session.delete(cp)
            db.session.commit()

            try:
                requests.post(
                    f"{PLAYERS_API_URL}/players/{player_id}/sell",
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
        ensure_owner_user_id_column()

    return app


if __name__ == "__main__":
    app = create_app()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
