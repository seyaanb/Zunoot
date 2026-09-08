import os
from dotenv import load_dotenv

load_dotenv()

def _clean_database_url(url):
    if url is None:
        return url
    return url.strip().strip('"').strip("'")

class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev")

    SESSION_PERMANENT = False
    SESSION_TYPE = "sqlalchemy"

    SQLALCHEMY_DATABASE_URI = _clean_database_url(os.environ.get("DATABASE_URL"))
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    if os.environ.get("FLASK_ENV") == "production" and SECRET_KEY == "dev":
        raise ValueError("No SECRET_KEY set for production application!")