"""Smoke tests: the app boots, health endpoints work, auth works, and the core
flashcard flow (subject -> topic -> card -> review) works end to end.

Regression tests for the bugs fixed alongside this suite live in
test_bugfixes.py (see docs/BUGFIXES.md).
"""

import psycopg2

from conftest import login, register


# --- boot and health -------------------------------------------------------

def test_landing_page_renders(client):
    resp = client.get("/auth/")
    assert resp.status_code == 200


def test_root_redirects_to_landing(client):
    resp = client.get("/")
    assert resp.status_code == 302
    assert resp.location.endswith("/auth/")


def test_livez_needs_no_login_and_no_db(client, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("livez must not touch the database")
    monkeypatch.setattr(psycopg2, "connect", boom)
    resp = client.get("/livez")
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "ok"


def test_healthz_reports_db_ok(client):
    resp = client.get("/healthz")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "ok"
    assert body["checks"]["database"]["ok"] is True


def test_healthz_returns_503_when_db_down(client, monkeypatch):
    def down(*a, **k):
        raise psycopg2.OperationalError("connection refused")
    monkeypatch.setattr(psycopg2, "connect", down)
    resp = client.get("/healthz")
    assert resp.status_code == 503
    body = resp.get_json()
    assert body["status"] == "unavailable"
    assert body["checks"]["database"]["error"] == "OperationalError"
    assert "refused" not in resp.get_data(as_text=True)  # no error text leaked


# --- auth ------------------------------------------------------------------

def test_protected_pages_redirect_to_login(client):
    resp = client.get("/library/")
    assert resp.status_code == 302
    assert "/auth/login" in resp.location


def test_register_then_login(client, db_cursor):
    resp = register(client)
    assert resp.status_code == 302 and resp.location.endswith("/auth/login")
    db_cursor.execute("select username, coins from students")
    assert db_cursor.fetchall() == [("alice", 0)]
    db_cursor.execute("select item_id from purchases where username='alice' order by 1")
    assert [r[0] for r in db_cursor.fetchall()] == [1, 13]  # default avatar + theme

    resp = login(client)
    assert resp.status_code == 302 and resp.location.endswith("/library/")
    assert client.get("/library/").status_code == 200


def test_wrong_password_is_rejected(client):
    register(client)
    resp = login(client, password="not-the-password")
    assert resp.location.endswith("/auth/login")
    assert client.get("/library/").status_code == 302


def test_password_is_hashed(client, db_cursor):
    register(client)
    db_cursor.execute("select password from students where username='alice'")
    stored = db_cursor.fetchone()[0]
    assert stored != "password123" and stored.startswith(("scrypt:", "pbkdf2:"))


def test_logout(logged_in):
    logged_in.get("/auth/logout")
    assert logged_in.get("/library/").status_code == 302


def test_csrf_is_enforced(app, client):
    app.config["WTF_CSRF_ENABLED"] = True
    try:
        resp = client.post("/auth/login", data={"username": "x", "password": "y"})
        assert resp.status_code == 400
    finally:
        app.config["WTF_CSRF_ENABLED"] = False


# --- core flashcard flow ---------------------------------------------------

def _make_card(c, subject="Biology", topic="Cells", front="What is ATP?", back="Energy currency"):
    c.post("/library/", data={"new-subject": subject})
    c.post(f"/library/{subject}", data={"new-topic": topic})
    return c.post(f"/library/{subject}/{topic}",
                  data={"new-flashcard-front": front, "new-flashcard-back": back})


def test_create_subject_topic_flashcard(logged_in, db_cursor):
    _make_card(logged_in)
    page = logged_in.get("/library/Biology/Cells")
    assert page.status_code == 200
    assert b"What is ATP?" in page.data
    db_cursor.execute("select front, back, easiness_factor from flashcards")
    assert db_cursor.fetchall() == [("What is ATP?", "Energy currency", 2.5)]
    db_cursor.execute("select coins from students where username='alice'")
    assert db_cursor.fetchone()[0] == 10  # +10 coins for adding a card


def test_library_search(logged_in):
    _make_card(logged_in)
    resp = logged_in.get("/library/search?keyword=atp")
    assert resp.status_code == 200
    assert b"What is ATP?" in resp.data


def test_secondary_pages_render(logged_in):
    for path in ("/guild/guild", "/shop/shop", "/shop/shop?item_type=theme",
                 "/community/", "/community/browse-subjects", "/community/browse-topics"):
        assert logged_in.get(path).status_code == 200, path


def test_spaced_review_updates_sm2_state(logged_in, db_cursor):
    _make_card(logged_in)
    resp = logged_in.post("/library/review", data={"spaced-repetition": "true"})
    assert resp.status_code == 200 and b"What is ATP?" in resp.data
    logged_in.post("/library/spaced-repetition", data={"option": "5"})
    logged_in.post("/library/end-session")
    db_cursor.execute("select review_interval, repetition_no, next_review is not null from flashcards")
    assert db_cursor.fetchone() == (1, 1, True)
    db_cursor.execute("select coins from students where username='alice'")
    assert db_cursor.fetchone()[0] == 12  # 10 for the card + 2 for the review


def test_unspaced_review_cycles_and_does_not_persist(logged_in, db_cursor):
    _make_card(logged_in)
    resp = logged_in.post("/library/review", data={"spaced-repetition": "false"})
    assert resp.status_code == 200 and b"What is ATP?" in resp.data
    logged_in.post("/library/spaced-repetition", data={"option": "5"})
    assert b"What is ATP?" in logged_in.get("/library/review").data  # cycles round
    logged_in.post("/library/end-session")
    db_cursor.execute("select repetition_no from flashcards")
    assert db_cursor.fetchone()[0] == 0
