from flask import Blueprint

library_bp = Blueprint("library", __name__, url_prefix="/library")

from . import routes