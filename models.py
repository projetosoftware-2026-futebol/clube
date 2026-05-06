from datetime import datetime
from db import db

LEAGUES = [
    "Premier League",
    "La Liga",
    "Serie A",
    "Bundesliga",
    "Ligue 1",
    "Brasileirão Série A",
    "Primeira Liga",
]


class Club(db.Model):
    __tablename__ = "clubs"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    image_url = db.Column(db.String(500))
    league = db.Column(db.String(100), nullable=False)
    budget = db.Column(db.Float, nullable=False, default=10_000_000.0)
    owner_user_id = db.Column(db.String(255), nullable=True, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    players = db.relationship(
        "ClubPlayer", back_populates="club", cascade="all, delete-orphan"
    )

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "image_url": self.image_url,
            "league": self.league,
            "budget": self.budget,
            "player_count": len(self.players),
            "player_ids": [p.player_id for p in self.players],
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    def to_dict_full(self):
        data = self.to_dict()
        data["players"] = [p.to_dict() for p in self.players]
        return data


class ClubPlayer(db.Model):
    __tablename__ = "club_players"

    id = db.Column(db.Integer, primary_key=True)
    club_id = db.Column(db.Integer, db.ForeignKey("clubs.id"), nullable=False)
    player_id = db.Column(db.Integer, nullable=False)
    purchase_price = db.Column(db.Float, nullable=False)
    joined_at = db.Column(db.DateTime, default=datetime.utcnow)

    club = db.relationship("Club", back_populates="players")

    def to_dict(self):
        return {
            "id": self.id,
            "player_id": self.player_id,
            "purchase_price": self.purchase_price,
            "joined_at": self.joined_at.isoformat(),
        }
