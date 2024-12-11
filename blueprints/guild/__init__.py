from flask import Blueprint

guild_bp = Blueprint("guild", __name__, url_prefix="/guild")

from . import routes