#import libraries and modules
from flask import Flask, send_from_directory, redirect, url_for
from flask_session import Session
from flask_login import LoginManager
from flask_wtf.csrf import CSRFProtect
from flask_sqlalchemy import SQLAlchemy
from blueprints.auth import auth_bp
from blueprints.library import library_bp
from blueprints.community import community_bp
from blueprints.guild import guild_bp
from blueprints.shop import shop_bp
from config import Config
import backend.queries as q
import backend.user as u
import os

#initialise Flask app
app = Flask(__name__, instance_relative_config=True)
app.config.from_object(Config)

#SQLAlchemy instance used only for session storage, not for app queries
db = SQLAlchemy(app)
app.config["SESSION_SQLALCHEMY"] = db

#initialise CSRF Protection
csrf = CSRFProtect(app)

#initialise and configure flask login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "auth.login"

#loads a user object into flask's login manager
@login_manager.user_loader
def load_user(username):
    user = q.get_user(username)
    if user:
        return u.User(*user)
    return None

#initialise session
Session(app)
with app.app_context():
    db.create_all()

#default route
@app.route("/")
def home():
    return redirect(url_for("auth.index"))

#register the blueprints
app.register_blueprint(auth_bp, url_prefix="/auth")
app.register_blueprint(library_bp, url_prefix="/library")
app.register_blueprint(community_bp, url_prefix="/community")
app.register_blueprint(guild_bp, url_prefix="/guild")
app.register_blueprint(shop_bp, url_prefix="/shop")

#create a route to serve the service worker
@app.route("/service-worker.js")
def service_worker():
    return send_from_directory(".", "service-worker.js", mimetype="application/javascript")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)