from flask import Blueprint

shop_bp = Blueprint("shop", __name__, url_prefix="/shop")

from . import routes