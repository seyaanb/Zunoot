"""Regression tests: one per bug in docs/BUGFIXES.md (BUG-n numbers match).
Every test here fails against the code as it was before the fix."""

from datetime import date, timedelta

import pytest
from flask import session

from backend import queries as q
from backend.flashcard_library.flashcard import Flashcard
from backend.session_queue import SessionQueue
from conftest import login, register


def _seed_card(cur, username, front="Same front", subject="S", topic="T"):
    cur.execute("insert into students(username, first_name, last_name, password, email_address)"
                " values (%s,'a','b','x',%s) on conflict do nothing", (username, f"{username}@e.com"))
    cur.execute("insert into subjects(subject_name, username) values (%s, %s) returning subject_id",
                (subject, username))
    sid = cur.fetchone()[0]
    cur.execute("insert into topics(topic_name, subject_id) values (%s, %s) returning topic_id", (topic, sid))
    tid = cur.fetchone()[0]
    cur.execute("insert into flashcards(front, back, topic_id) values (%s, 'b', %s) returning flashcard_id",
                (front, tid))
    return sid, tid, cur.fetchone()[0]


def _as(client, username):
    client.get("/auth/logout")
    register(client, username)
    login(client, username)
    return client


# BUG-1: review session could not be stored -> every review was a 500
def test_bug1_review_queue_round_trips_through_plain_data():
    queue = SessionQueue(True)
    card = Flashcard(7, "f", "b", 6, 2, 2.36, date(2026, 1, 1), date(2026, 1, 7), 1, 0, None)
    queue.addFlashcard(card)
    data = queue.to_dict()
    import msgspec
    msgspec.msgpack.encode(data)  # what Flask-Session 0.8 does; used to raise TypeError
    restored = SessionQueue.from_dict(data).items[0]
    assert (restored.flashcard_id, restored.interval, restored.repetition_no) == (7, 6, 2)
    assert restored.next_review == date(2026, 1, 7)


# BUG-2: ending a session overwrote other users' cards with the same front text
def test_bug2_push_deck_only_touches_the_owners_reviewed_card(db_cursor):
    _, u1_topic, u1_card = _seed_card(db_cursor, "u1")
    _, _, u2_card = _seed_card(db_cursor, "u2")
    card = Flashcard(u1_card, None, None, 0, 0, 2.5, None, None, u1_topic, 0, None)
    card.reviewFlashcard(5)

    q.push_deck([card], "u2")  # wrong owner: must not write anything
    db_cursor.execute("select repetition_no from flashcards where flashcard_id = %s", (u1_card,))
    assert db_cursor.fetchone()[0] == 0

    q.push_deck([card], "u1")
    db_cursor.execute("select flashcard_id, repetition_no from flashcards order by 1")
    assert db_cursor.fetchall() == [(u1_card, 1), (u2_card, 0)]


# BUG-3: joining a guild incremented every guild's member count
def test_bug3_join_guild_only_increments_that_guild(client, db_cursor):
    for user in ("leader1", "leader2"):
        _as(client, user)
        client.post("/guild/create-guild", data={"guild_name": f"g_{user}"})
    db_cursor.execute("select guild_name, no_of_members from guilds order by 1")
    assert db_cursor.fetchall() == [("g_leader1", 1), ("g_leader2", 1)]


# BUG-4: community uploads read session["library"], which no longer exists
def test_bug4_upload_subject_and_topic_to_community(logged_in, db_cursor):
    logged_in.post("/library/", data={"new-subject": "Bio"})
    logged_in.post("/library/Bio", data={"new-topic": "Cells"})
    logged_in.post("/library/Bio/Cells", data={"new-flashcard-front": "Q", "new-flashcard-back": "A"})

    logged_in.post("/community/upload-subject", data={"name": "Bio"})
    logged_in.post("/community/upload-subject", data={"name": "Bio"})  # re-upload replaces
    resp = logged_in.post("/community/upload-topic", data={"subject": "Bio", "name": "Cells"})
    assert resp.status_code == 302 and resp.location.endswith("/library/Bio")

    db_cursor.execute("select community_subject_name from communitysubjects")
    assert db_cursor.fetchall() == [("Bio",)]
    db_cursor.execute("select community_topic_name, community_subject_id is null from communitytopics order by 2")
    assert db_cursor.fetchall() == [("Cells", False), ("Cells", True)]
    db_cursor.execute("select count(*) from communityflashcards")
    assert db_cursor.fetchone()[0] == 2


def test_bug4_upload_topic_failure_is_not_a_500(logged_in):
    resp = logged_in.post("/community/upload-topic", data={"subject": "Nope", "name": "Nope"})
    assert resp.status_code == 302


# BUG-5a: any user could reorder any other user's items
def test_bug5a_update_order_is_scoped_to_owner(client, db_cursor):
    sid, _, _ = _seed_card(db_cursor, "victim")
    _as(client, "attacker")
    resp = client.post("/library/update-order/Subject", json={"order": [{"id": sid, "position": 99}]})
    assert resp.status_code == 200
    db_cursor.execute("select position from subjects where subject_id = %s", (sid,))
    assert db_cursor.fetchone()[0] == 0
    assert client.post("/library/update-order/Library", json={"order": []}).status_code == 400


def test_bug5a_owner_can_still_reorder(logged_in, db_cursor):
    for name in ("A", "B"):
        logged_in.post("/library/", data={"new-subject": name})
    db_cursor.execute("select subject_id from subjects order by subject_name")
    a, b = [r[0] for r in db_cursor.fetchall()]
    logged_in.post("/library/update-order/Subject",
                   json={"order": [{"id": b, "position": 0}, {"id": a, "position": 1}]})
    db_cursor.execute("select subject_name from subjects order by position")
    assert [r[0] for r in db_cursor.fetchall()] == ["B", "A"]


# BUG-5b: anyone could accept/reject requests for any guild (and force-add users)
def test_bug5b_only_the_leader_can_accept_requests(client, db_cursor):
    _as(client, "leader")
    client.post("/guild/create-guild", data={"guild_name": "g"})
    _as(client, "applicant")
    client.post("/guild/join-guild/g")
    _as(client, "outsider")
    client.post("/guild/accept-request", data={"username": "applicant", "guild_name": "g"})
    client.post("/guild/accept-request", data={"username": "outsider", "guild_name": "g"})
    db_cursor.execute("select username from students where guild_name = 'g' order by 1")
    assert db_cursor.fetchall() == [("leader",)]

    _as(client, "leader")
    client.post("/guild/accept-request", data={"username": "applicant", "guild_name": "g"})
    db_cursor.execute("select username, guild_role from students where guild_name = 'g' order by 1")
    assert db_cursor.fetchall() == [("applicant", "member"), ("leader", "leader")]
    db_cursor.execute("select no_of_members from guilds")
    assert db_cursor.fetchone()[0] == 2


# BUG-5c: any member could delete the guild
def test_bug5c_only_the_leader_can_delete_the_guild(client, db_cursor):
    _as(client, "leader")
    client.post("/guild/create-guild", data={"guild_name": "g"})
    _as(client, "member")
    client.post("/guild/join-guild/g")
    _as(client, "leader")
    client.post("/guild/accept-request", data={"username": "member", "guild_name": "g"})
    _as(client, "member")
    client.post("/guild/delete-guild")
    db_cursor.execute("select count(*) from guilds")
    assert db_cursor.fetchone()[0] == 1
    client.post("/guild/leave-guild")  # members can still leave
    db_cursor.execute("select guild_name from students where username = 'member'")
    assert db_cursor.fetchone()[0] is None
    db_cursor.execute("select no_of_members from guilds")
    assert db_cursor.fetchone()[0] == 1


# BUG-5d: anyone could delete anyone's community upload
def test_bug5d_only_the_uploader_can_delete_community_items(client, db_cursor):
    _as(client, "owner")
    db_cursor.execute("insert into communitysubjects(community_subject_name, uploader_username)"
                      " values ('S', 'owner') returning community_subject_id")
    sid = db_cursor.fetchone()[0]
    db_cursor.execute("insert into communitytopics(community_topic_name, uploader_username)"
                      " values ('T', 'owner') returning community_topic_id")
    tid = db_cursor.fetchone()[0]
    _as(client, "attacker")
    client.post("/community/delete_subject", data={"subject_id": sid})
    client.post("/community/delete_topic", data={"topic_id": tid})
    db_cursor.execute("select (select count(*) from communitysubjects), (select count(*) from communitytopics)")
    assert db_cursor.fetchone() == (1, 1)
    _as(client, "owner")
    client.post("/community/delete_subject", data={"subject_id": sid})
    client.post("/community/delete_topic", data={"topic_id": tid})
    db_cursor.execute("select (select count(*) from communitysubjects), (select count(*) from communitytopics)")
    assert db_cursor.fetchone() == (0, 0)


# BUG-5e: topics could be imported into another user's subject
def test_bug5e_import_topic_requires_owning_the_target_subject(client, db_cursor):
    victim_subject, _, _ = _seed_card(db_cursor, "victim")
    db_cursor.execute("insert into communitytopics(community_topic_name, uploader_username)"
                      " values ('T2', 'victim') returning community_topic_id")
    ctid = db_cursor.fetchone()[0]
    _as(client, "attacker")
    for send in (client.get, client.post):  # the old route was a GET
        send(f"/community/import-topic/{ctid}/T2/{victim_subject}")
    db_cursor.execute("select count(*) from topics where subject_id = %s", (victim_subject,))
    assert db_cursor.fetchone()[0] == 1  # unchanged


def test_bug5e_import_topic_into_own_subject(logged_in, db_cursor):
    logged_in.post("/library/", data={"new-subject": "Mine"})
    db_cursor.execute("select subject_id from subjects")
    sid = db_cursor.fetchone()[0]
    db_cursor.execute("insert into communitytopics(community_topic_name, uploader_username)"
                      " values ('Imported', 'alice') returning community_topic_id")
    ctid = db_cursor.fetchone()[0]
    db_cursor.execute("insert into communityflashcards(community_topic_id, front, back) values (%s,'q','a')", (ctid,))
    logged_in.post(f"/community/import-topic/{ctid}/Imported/{sid}")
    logged_in.post(f"/community/import-topic/{ctid}/Imported/{sid}")  # duplicate is refused
    db_cursor.execute("select count(*) from topics where subject_id = %s", (sid,))
    assert db_cursor.fetchone()[0] == 1


# BUG-6: state-changing endpoints accepted GET (cross-site request forgery)
@pytest.mark.parametrize("path", [
    "/auth/delete-account", "/guild/create-guild?guild_name=x", "/guild/join-guild/x",
    "/guild/delete-guild", "/guild/leave-guild", "/community/delete_subject?subject_id=1",
    "/community/delete_topic?topic_id=1", "/community/import-subject/1/x", "/community/import-topic/1/x/1",
])
def test_bug6_state_changes_reject_get(logged_in, path):
    assert logged_in.get(path).status_code == 405


def test_bug6_delete_account_needs_csrf_token(app, logged_in, db_cursor):
    app.config["WTF_CSRF_ENABLED"] = True
    try:
        assert logged_in.post("/auth/delete-account").status_code == 400
    finally:
        app.config["WTF_CSRF_ENABLED"] = False
    db_cursor.execute("select count(*) from students")
    assert db_cursor.fetchone()[0] == 1
    logged_in.post("/auth/delete-account")
    db_cursor.execute("select count(*) from students")
    assert db_cursor.fetchone()[0] == 0
    assert logged_in.get("/library/").status_code == 302  # logged out too


# BUG-7: posting an empty flashcard form still awarded coins
def test_bug7_no_coins_for_invalid_flashcard_posts(logged_in, db_cursor):
    logged_in.post("/library/", data={"new-subject": "S"})
    logged_in.post("/library/S", data={"new-topic": "T"})
    for _ in range(5):
        logged_in.post("/library/S/T", data={"new-flashcard-front": "", "new-flashcard-back": ""})
    db_cursor.execute("select coins from students")
    assert db_cursor.fetchone()[0] == 0


# BUG-8: buying an owned item took the coins and then 500'd
def test_bug8_purchase_is_atomic(logged_in, db_cursor):
    db_cursor.execute("update students set coins = 150")
    assert logged_in.post("/shop/purchase/2").status_code == 302  # chimp, 100
    assert logged_in.post("/shop/purchase/2").status_code == 302  # already owned
    assert logged_in.post("/shop/purchase/3").status_code == 302  # 100 > 50 left
    assert logged_in.post("/shop/purchase/999").status_code == 302  # unknown item
    db_cursor.execute("select coins from students")
    assert db_cursor.fetchone()[0] == 50
    db_cursor.execute("select item_id from purchases order by 1")
    assert [r[0] for r in db_cursor.fetchall()] == [1, 2, 13]
    assert logged_in.post("/shop/equip/999").status_code == 302


# BUG-9: points_reset leaked a connection and could double-reset
def test_bug9_points_reset_runs_once_per_week(db_cursor, monkeypatch):
    opened = []
    real_database = q.database

    def tracking_database():
        conn = real_database()
        opened.append(conn)
        return conn
    monkeypatch.setattr(q, "database", tracking_database)

    db_cursor.execute("insert into students(username, first_name, last_name, password, email_address, points)"
                      " values ('p','a','b','x','p@e.com', 40)")
    db_cursor.execute("update pointsreset set last_reset = '2000-01-01 00:00:00'")
    q.points_reset()
    q.points_reset()
    db_cursor.execute("select points from students")
    assert db_cursor.fetchone()[0] == 0
    assert opened and all(conn.closed for conn in opened)  # previously one leaked per call


# BUG-10: spaced review recursed once per skipped card -> RecursionError
def test_bug10_large_not_due_library_does_not_recurse():
    queue = SessionQueue(True)
    future = date.today() + timedelta(days=30)
    for i in range(5000):
        queue.addFlashcard(Flashcard(i, "f", "b", 6, 2, 2.5, date.today(), future, 1, i, None))
    assert queue.getNextFlashcard() is None
    assert queue.isEmpty()


def test_bug10_due_card_after_many_not_due():
    queue = SessionQueue(True)
    future = date.today() + timedelta(days=30)
    for i in range(3000):
        queue.addFlashcard(Flashcard(i, "f", "b", 6, 2, 2.5, date.today(), future, 1, i, None))
    queue.addFlashcard(Flashcard(9999, "f", "b", 0, 0, 2.5, None, None, 1, 0, None))
    assert queue.getNextFlashcard().flashcard_id == 9999


# BUG-11: a review queue survived logout into the next user's session
def test_bug11_review_queue_cleared_on_logout(client):
    _as(client, "first")
    client.post("/library/", data={"new-subject": "S"})
    client.post("/library/S", data={"new-topic": "T"})
    client.post("/library/S/T", data={"new-flashcard-front": "first's secret", "new-flashcard-back": "b"})
    client.post("/library/review", data={"spaced-repetition": "false"})
    with client:
        client.get("/auth/logout")
        assert "queue" not in session
    _as(client, "second")
    resp = client.post("/library/review", data={"spaced-repetition": "false"})
    assert b"first's secret" not in resp.data


# BUG-16: renaming a topic / editing a card matched by name across the whole library
def test_bug16_edit_topic_and_flashcard_match_by_id(logged_in, db_cursor):
    for subject in ("Maths", "Physics"):
        logged_in.post("/library/", data={"new-subject": subject})
        logged_in.post(f"/library/{subject}", data={"new-topic": "Chapter 1"})
        logged_in.post(f"/library/{subject}/Chapter 1",
                       data={"new-flashcard-front": "Define it", "new-flashcard-back": subject})
    db_cursor.execute("select t.topic_id from topics t join subjects s using (subject_id) where subject_name='Physics'")
    physics_topic = db_cursor.fetchone()[0]
    db_cursor.execute("select flashcard_id from flashcards where back = 'Physics'")
    physics_card = db_cursor.fetchone()[0]

    logged_in.post("/library/edit-topic", data={
        "old-topic-name": "Chapter 1", "new-topic-name": "Kinematics", "topic-id": str(physics_topic)})
    logged_in.post("/library/edit-flashcard", data={
        "old-flashcard-front": "Define it", "new-flashcard-front": "Velocity?",
        "new-flashcard-back": "Physics", "flashcard-id": str(physics_card)})
    db_cursor.execute("select subject_name, topic_name from topics join subjects using (subject_id) order by 1")
    assert db_cursor.fetchall() == [("Maths", "Chapter 1"), ("Physics", "Kinematics")]
    db_cursor.execute("select back, front from flashcards order by 1")
    assert db_cursor.fetchall() == [("Maths", "Define it"), ("Physics", "Velocity?")]


def test_rating_must_be_between_0_and_5(logged_in, db_cursor):
    logged_in.post("/library/", data={"new-subject": "S"})
    logged_in.post("/library/S", data={"new-topic": "T"})
    logged_in.post("/library/S/T", data={"new-flashcard-front": "f", "new-flashcard-back": "b"})
    logged_in.post("/library/review", data={"spaced-repetition": "true"})
    logged_in.post("/library/spaced-repetition", data={"option": "500"})
    logged_in.post("/library/end-session")
    db_cursor.execute("select easiness_factor from flashcards")
    assert db_cursor.fetchone()[0] == 2.5
