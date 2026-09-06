import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev")

    SESSION_PERMANENT = False
    SESSION_TYPE = "sqlalchemy"

    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL")
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    if os.environ.get("FLASK_ENV") == "production" and SECRET_KEY == "dev":
        raise ValueError("No SECRET_KEY set for production application!")