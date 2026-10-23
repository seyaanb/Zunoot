import os
import psycopg2
import backend.session_queue as sq
from backend.flashcard_library import flashcard as f
from datetime import datetime, timezone, timedelta

def database():
    url = os.environ.get("DATABASE_URL")
    if url:
        url = url.strip().strip('"').strip("'")
    return psycopg2.connect(url)

ids = {
    "Library": "username",
    "Subject": "subject_id",
    "Topic": "topic_id",
    "Flashcard": "flashcard_id"
}

child_tables = {
    "Library": "subjects",
    "Subject": "topics",
    "Topic": "flashcards"
}

#flashcard deck queries
def retrieve_deck():
    conn = database()
    cursor = conn.cursor()
    cursor.execute("select * from flashcards")
    deck = cursor.fetchall()
    conn.close()
    return deck


def push_deck(deck, username):
    '''
    writes the SM-2 state of every reviewed card back to the database in one transaction.

    previously this matched rows with WHERE front = %s, which overwrote every card with the
    same front text, including other users' cards. it now matches on flashcard_id and only
    touches cards owned by `username`. front/back are no longer written: the session only
    holds scheduling state, so it can't clobber an edit made while a review was in progress.
    '''
    conn = database()
    try:
        cursor = conn.cursor()
        sql = '''
        UPDATE flashcards AS f
        SET review_interval = %s, repetition_no = %s, easiness_factor = %s,
            last_review = %s, next_review = %s
        FROM topics t JOIN subjects s ON s.subject_id = t.subject_id
        WHERE f.flashcard_id = %s AND f.topic_id = t.topic_id AND s.username = %s
        '''
        for flashcard in deck:
            cursor.execute(sql, (flashcard.interval, flashcard.repetition_no,
                                 round(flashcard.easiness_factor, 2), flashcard.last_review,
                                 flashcard.next_review, flashcard.flashcard_id, username))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def get_flashcard_text(flashcard_id, username):
    '''returns (front, back) for a card owned by username, or None'''
    conn = database()
    cursor = conn.cursor()
    cursor.execute('''
                   select f.front, f.back from flashcards f
                   join topics t on t.topic_id = f.topic_id
                   join subjects s on s.subject_id = t.subject_id
                   where f.flashcard_id = %s and s.username = %s''', (flashcard_id, username))
    row = cursor.fetchone()
    conn.close()
    return row

def subject_belongs_to_user(subject_id, username):
    conn = database()
    cursor = conn.cursor()
    cursor.execute("select 1 from subjects where subject_id = %s and username = %s", (subject_id, username))
    row = cursor.fetchone()
    conn.close()
    return row is not None

def delete_subject(subject_id):
    conn = database()
    cursor = conn.cursor()
    
    cursor.execute('''
                   delete from subjects
                   where subject_id = %s''', (int(subject_id),))
    conn.commit()
    conn.close()

def delete_topic(topic_id):
    conn = database()
    cursor = conn.cursor()
    
    cursor.execute('''
                   delete from topics
                   where topic_id = %s''', (int(topic_id),))
    conn.commit()
    conn.close()

def delete_flashcard(flashcard_id):
    conn = database()
    cursor = conn.cursor()
    
    cursor.execute('''
                   delete from flashcards
                   where flashcard_id = %s''', (int(flashcard_id),))
    conn.commit()
    conn.close()

def get_new_subject_position(username):
    conn = database()
    cursor = conn.cursor()
    
    cursor.execute('''select MAX(position) from subjects where username = %s''', (username,))
    max_position = cursor.fetchone()[0]
    conn.close()
    if max_position is not None:
        return max_position + 1
    else:
        return 0

def get_new_topic_position(subject_id):
    conn = database()
    cursor = conn.cursor()
    
    cursor.execute('''select max(position) from topics where subject_id = %s''', (subject_id,))
    max_position = cursor.fetchone()[0]
    conn.close()
    if max_position is not None:
        return max_position + 1
    else:
        return 0
    
def get_new_flashcard_position(topic_id):
    conn = database()
    cursor = conn.cursor()
    
    cursor.execute('''select max(position) from flashcards where topic_id = %s''', (topic_id,))
    max_position = cursor.fetchone()[0]
    conn.close()
    if max_position is not None:
        return max_position + 1
    else:
        return 0
    

def add_subject(subject_name, username):
    conn = database()
    cursor = conn.cursor()
    
    position = get_new_subject_position(username)
    cursor.execute('''
                   insert into subjects(subject_name, username, position)
                   values (%s, %s, %s) RETURNING subject_id''', (subject_name, username, position))
                   
    subject_id = cursor.fetchone()[0]
    conn.commit()
    conn.close()

    return subject_id

def add_topic(topic_name, subject_id):
    conn = database()
    cursor = conn.cursor()
    
    position = get_new_topic_position(subject_id)
    cursor.execute('''
                   insert into topics(topic_name, subject_id, position)
                   values (%s, %s, %s) RETURNING topic_id''', (topic_name, subject_id, position))
                   
    topic_id = cursor.fetchone()[0]
    conn.commit()
    conn.close()

    return topic_id

def add_flashcard(front, back, topic_id):
    conn = database()
    cursor = conn.cursor()
    
    position = get_new_flashcard_position(topic_id)
    cursor.execute('''
                   insert into flashcards(front, back, topic_id, position)
                   values (%s, %s, %s, %s)''', (front, back, topic_id, position))
    conn.commit()
    conn.close()

def get_children(current_class, id):
    conn = database()
    cursor = conn.cursor()
    

    table = child_tables[current_class]
    id_name = ids[current_class]

    query = f"select * from {table} where {id_name} = %s order by position"
    cursor.execute(query, (id,))
    children = cursor.fetchall()
    conn.close()
    return children

def edit_subject_name(subject_id, new_name):
    conn = database()
    cursor = conn.cursor()
    

    query = '''update subjects
               set subject_name = %s
               where subject_id = %s'''
    cursor.execute(query, (new_name, subject_id))
    conn.commit()
    conn.close()

def edit_topic_name(topic_id, new_name):
    conn = database()
    cursor = conn.cursor()
    

    query = '''update topics
               set topic_name = %s
               where topic_id = %s'''
    cursor.execute(query, (new_name, topic_id))
    conn.commit()
    conn.close()

def edit_flashcard(flashcard_id, front, back):
    conn = database()
    cursor = conn.cursor()
    

    query = '''update flashcards
               set front = %s, back = %s
               where flashcard_id = %s'''
    cursor.execute(query, (front, back, flashcard_id))
    conn.commit()
    conn.close()

def check_subject_exists(subject, username):
    conn = database()
    cursor = conn.cursor()

    cursor.execute("select * from subjects where subject_name = %s and username = %s", (subject, username))
    subject = cursor.fetchone()
    conn.close()
    if subject:
        return True
    return False

def check_topic_exists(topic, subject_id):
    conn = database()
    cursor = conn.cursor()

    cursor.execute("select * from topics where topic_name = %s and subject_id = %s", (topic, subject_id))
    topic = cursor.fetchone()
    conn.close()
    if topic:
        return True
    return False

def get_subject_id(subject, username):
    conn = database()
    cursor = conn.cursor()

    cursor.execute("select subject_id from subjects where subject_name = %s and username = %s", (subject, username))
    subject_id = int(cursor.fetchone()[0])
    conn.close()

    return subject_id

def get_topic_id(topic, subject_id):
    conn = database()
    cursor = conn.cursor()

    cursor.execute("select topic_id from topics where topic_name = %s and subject_id = %s", (topic, subject_id))
    topic_id = int(cursor.fetchone()[0])
    conn.close()

    return topic_id

# ownership-scoped reorder statements. previously any logged-in user could reorder any
# other user's subjects/topics/flashcards by sending their IDs.
_reorder_sql = {
    "Subject": '''update subjects set position = %s
                  where subject_id = %s and username = %s''',
    "Topic": '''update topics t set position = %s
                from subjects s
                where t.topic_id = %s and s.subject_id = t.subject_id and s.username = %s''',
    "Flashcard": '''update flashcards f set position = %s
                    from topics t join subjects s on s.subject_id = t.subject_id
                    where f.flashcard_id = %s and t.topic_id = f.topic_id and s.username = %s''',
}

def update_order(item_type, order, username):
    if item_type not in _reorder_sql:
        raise ValueError(f"Invalid item_type: {item_type}")

    conn = database()
    try:
        cursor = conn.cursor()
        for item in order:
            cursor.execute(_reorder_sql[item_type], (int(item["position"]), int(item["id"]), username))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


#community queries
def add_community_subject(subject_object, username):
    '''
    uploads a subject (with its topics and flashcards) to the community library, replacing any
    earlier upload by the same user with the same name. the delete and the inserts run in one
    transaction, so a failure part-way through can no longer leave a half-uploaded subject or
    lose the previous upload.
    '''
    conn = database()
    try:
        cursor = conn.cursor()
        cursor.execute('''delete from communitysubjects
                          where uploader_username = %s and community_subject_name = %s''',
                       (username, subject_object.getName()))
        cursor.execute('''
                       insert into communitysubjects (community_subject_name, uploader_username)
                       values (%s, %s) RETURNING community_subject_id
                       ''', (subject_object.getName(), username))
        subject_id = cursor.fetchone()[0]

        for topic in subject_object.children:
            cursor.execute('''
                           insert into communitytopics (community_topic_name, community_subject_id, uploader_username)
                           values (%s, %s, %s) RETURNING community_topic_id
                           ''', (topic.getName(), subject_id, username))
            topic_id = cursor.fetchone()[0]
            for flashcard in topic.children:
                cursor.execute('''
                               insert into communityflashcards (community_topic_id, front, back)
                               values (%s, %s, %s)
                               ''', (topic_id, flashcard.getName(), flashcard.getBack()))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def add_community_topic(topic_object, username):
    '''uploads a standalone topic, replacing an earlier standalone upload with the same name'''
    conn = database()
    try:
        cursor = conn.cursor()
        cursor.execute('''delete from communitytopics
                          where uploader_username = %s and community_topic_name = %s
                          and community_subject_id is null''',
                       (username, topic_object.getName()))
        cursor.execute('''
                       insert into communitytopics (community_topic_name, uploader_username)
                       values (%s, %s) RETURNING community_topic_id
                       ''', (topic_object.getName(), username))
        topic_id = cursor.fetchone()[0]
        for flashcard in topic_object.children:
            cursor.execute('''
                           insert into communityflashcards (community_topic_id, front, back)
                           values (%s, %s, %s)
                           ''', (topic_id, flashcard.getName(), flashcard.getBack()))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def get_community_subjects():
    conn = database()
    cursor = conn.cursor()
    
    cursor.execute("select * from communitysubjects order by community_subject_name asc")
    subjects = cursor.fetchall()
    conn.close()

    return subjects

def get_community_subjects_from_keyword(keyword):
    conn = database()
    cursor = conn.cursor()
    
    query = "select * from communitysubjects where community_subject_name like %s order by community_subject_name asc"
    cursor.execute(query, (f"%{keyword}%",))
    subjects = cursor.fetchall()
    conn.close()

    return subjects


def get_community_topics_from_subject(subject_id):
    conn = database()
    cursor = conn.cursor()
    
    cursor.execute('''select community_topic_id, community_topic_name
                      from communitytopics
                      where community_subject_id = %s
                      order by community_topic_name asc''', (subject_id,))
    topics = cursor.fetchall()
    conn.close()

    return topics

def get_community_topics():
    conn = database()
    cursor = conn.cursor()
    
    cursor.execute("select * from communitytopics order by community_topic_name asc")
    topics = cursor.fetchall()
    conn.close()

    return topics

def get_community_topics_from_keyword(keyword):
    conn = database()
    cursor = conn.cursor()
    
    query = "select * from communitytopics where community_topic_name like %s order by community_topic_name asc"
    cursor.execute(query, (f"%{keyword}%",))
    topics = cursor.fetchall()
    conn.close()

    return topics

def get_community_flashcards(topic_id):
    conn = database()
    cursor = conn.cursor()
    
    cursor.execute('''select community_flashcard_id, front, back
                      from communityflashcards
                      where community_topic_id = %s
                      order by front asc''', (topic_id,))
    
    flashcards = cursor.fetchall()

    conn.close()

    return flashcards

def import_community_subject(username, community_subject_id, subject_name):
    
    subject_id = add_subject(subject_name, username)

    topics = get_community_topics_from_subject(community_subject_id)
    for topic in topics:
        topic_id = add_topic(topic[1],subject_id)
        flashcards = get_community_flashcards(topic[0])
        for flashcard in flashcards:
            add_flashcard(flashcard[1], flashcard[2], topic_id)


def import_community_topic(subject_id, community_topic_id, topic_name):
    topic_id = add_topic(topic_name, subject_id)

    flashcards = get_community_flashcards(community_topic_id)
    for flashcard in flashcards:
        add_flashcard(flashcard[1], flashcard[2], topic_id)


def delete_community_subject(subject_id, username):
    '''deletes a community subject only if `username` uploaded it; returns True if deleted'''
    conn = database()
    cursor = conn.cursor()
    
    cursor.execute(''' delete from communitysubjects
                       where community_subject_id = %s and uploader_username = %s''', (subject_id, username))
    deleted = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return deleted

def delete_community_topic(topic_id, username):
    '''deletes a community topic only if `username` uploaded it; returns True if deleted'''
    conn = database()
    cursor = conn.cursor()
    
    cursor.execute(''' delete from communitytopics
                       where community_topic_id = %s and uploader_username = %s''', (topic_id, username))
    deleted = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return deleted

def check_community_subject_exists(username, subject_name):
    conn = database()
    cursor = conn.cursor()
    
    cursor.execute('''select community_subject_id from communitysubjects
                   where uploader_username = %s and community_subject_name = %s''', (username, subject_name))
    subject = cursor.fetchall()
    conn.close()
    return subject

def check_community_topic_exists(username, topic_name):
    conn = database()
    cursor = conn.cursor()

    cursor.execute('''
                   select community_topic_id from communitytopics
                   where uploader_username = %s and community_topic_name = %s''', (username, topic_name))
    topic = cursor.fetchall()
    conn.close()
    return topic



#user queries
def check_user_exists(username):
    conn = database()
    cursor = conn.cursor()
    
    cursor.execute("select * from students where username = %s", (username,))
    user = cursor.fetchall()
    conn.close()
    if user:
        return True
    return False
    
def insert_new_user(username, first_name, last_name, password_hash, email_address):
    conn = database()
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
                       insert into students(username, first_name, last_name, password, email_address, date_joined)
                       values(%s, %s, %s, %s, %s, %s)
                       ''', (username, first_name, last_name, password_hash, email_address, datetime.now().date()))
        
        cursor.execute('''
                       insert into purchases (username, item_id)
                       values (%s, 1)''', (username,))
        
        cursor.execute('''
                       insert into purchases (username, item_id)
                       values (%s, 13)''', (username,))
        
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()

def get_user(username):
    conn = database()
    cursor = conn.cursor()
    
    cursor.execute('''
                   select * from students
                   where username = %s
                   ''', (username,))
    user = cursor.fetchone()
    conn.close()
    return user 

def get_user_guild(username):
    conn = database()
    cursor = conn.cursor()
    
    cursor.execute('''
                   select guild_name from students
                   where username = %s
                   ''', (username,))
    user = cursor.fetchone()
    conn.close()
    return user

def add_coins_db(username, quantity):
    conn = database()
    cursor = conn.cursor()
    
    cursor.execute('''
                   update students
                   set coins = coins + %s
                   where username = %s''', (quantity, username))
    conn.commit()
    conn.close()

def add_points_db(username, quantity):
    conn = database()
    cursor = conn.cursor()
    
    cursor.execute('''
                   update students
                   set points = points + %s
                   where username = %s''', (quantity, username))
    conn.commit()
    conn.close()

    user_guild = get_user_guild(username)
    if user_guild:
        conn = database()
        cursor = conn.cursor()
        
        cursor.execute('''
                       update guilds
                       set points = points + %s
                       where guild_name = %s''', (quantity, user_guild[0]))
        conn.commit()
        conn.close()

def delete_user(username):
    conn = database()
    cursor = conn.cursor()
    
    cursor.execute('''delete from students
                      where username = %s''', (username,))
    conn.commit()
    conn.close()


#guild queries
def create_guild(guild_name, leader_username):
    conn = database()
    cursor = conn.cursor()
    
    cursor.execute('''
                   insert into guilds(guild_name, leader_username)
                   values (%s, %s)''', (guild_name, leader_username))
    conn.commit()
    conn.close()

def get_all_guilds():
    conn = database()
    cursor = conn.cursor()
    
    cursor.execute('''
                   select * from guilds
                   where no_of_members < 50''')
    guilds = cursor.fetchall()

    conn.close()
    
    return guilds

def join_guild(username, guild_name, user_role):
    conn = database()
    cursor = conn.cursor()
    
    cursor.execute('''update students
                      set guild_name = %s, guild_role = %s
                      where username = %s''', (guild_name, user_role, username))
    conn.commit()
    conn.close()

    conn = database()
    cursor = conn.cursor()
    
    cursor.execute('''update guilds
                      set no_of_members = no_of_members + 1
                      where guild_name = %s''', (guild_name,))
    conn.commit()
    conn.close()


def request_guild(username, guild_name):
    conn = database()
    cursor = conn.cursor()
    cursor.execute('''insert into guildrequests(request_username, status, guild_name)
                      values(%s, 'pending', %s)''', (username, guild_name))
    conn.commit()
    conn.close()

def get_user_requests(username):
    conn = database()
    cursor = conn.cursor()
    cursor.execute('''
                   select * from guildrequests
                   where request_username = %s
                   and status = 'pending' ''', (username, ))
    requests = cursor.fetchall()
    conn.close()
    return requests

def delete_user_requests(username):
    conn = database()
    cursor = conn.cursor()
    
    cursor.execute('''delete from guildrequests
                      where request_username = %s''', (username,))
    conn.commit()
    conn.close()

def get_guild_requests(guild_name):
    conn = database()
    cursor = conn.cursor()
    cursor.execute('''select * from guildrequests
                   where guild_name = %s
                   and status = 'pending' ''', (guild_name, ))
    requests = cursor.fetchall()
    conn.close()
    return requests

def accept_guild_request(username, guild_name):
    conn = database()
    cursor = conn.cursor()
    cursor.execute('''
                   update guildrequests
                   set status = 'accepted'
                   where request_username = %s
                   and guild_name = %s''', (username, guild_name))
    conn.commit()
    conn.close()

def reject_guild_request(username, guild_name):
    conn = database()
    cursor = conn.cursor()
    cursor.execute('''
                   update guildrequests
                   set status = 'declined'
                   where request_username = %s
                   and guild_name = %s''', (username, guild_name))
    conn.commit()
    conn.close()

def delete_guild(current_user):
    guild_name = current_user.get_guild()
    conn = database()
    cursor = conn.cursor()
    

    cursor.execute('''
                   update students
                   set guild_role = null, points = 0, guild_name = null
                   where guild_name = %s''', (guild_name,))
    conn.commit()

    
    cursor.execute('''
                   delete from guilds
                   where guild_name = %s''', (guild_name,))
    conn.commit()
    conn.close()

def leave_guild(current_user):
    username = current_user.id
    guild_name = current_user.get_guild()
    conn = database()
    cursor = conn.cursor()
    

    cursor.execute('''select points from students
                   where username = %s''', (username,))
    points = cursor.fetchone()

    cursor.execute('''update guilds
                   set points = points - %s, no_of_members = no_of_members - 1
                   where guild_name = %s''', (points[0], guild_name))
    conn.commit()

    
    cursor.execute('''
                   update students
                   set guild_name = null, guild_role = null, points = 0
                   where username = %s''', (username,))
    conn.commit()
    conn.close()

def get_intra_leaderboard(guild_name):
    conn = database()
    cursor = conn.cursor()
    
    cursor.execute('''select avatar, username, points from students
                    where guild_name = %s
                   order by points desc''', (guild_name,))
    leaderboard = cursor.fetchall()
    conn.close()
    return leaderboard

def get_inter_leaderboard():
    conn = database()
    cursor = conn.cursor()
    
    cursor.execute('''select guild_name, points from guilds
                   order by points desc''')
    leaderboard = cursor.fetchall()
    conn.close()
    return leaderboard

def points_reset():
    '''
    resets everyone's weekly points once per week (Monday 00:00 UTC), on the first request
    after the deadline.

    previously this opened a second connection inside the first and only closed one, leaking a
    database connection on every guild page view. it now uses one connection, and the
    pointsreset row is claimed with a conditional UPDATE, so if two requests race past the
    deadline exactly one of them performs the reset.
    '''
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    monday = now - timedelta(days=now.weekday())
    monday_midnight = monday.replace(hour=0, minute=0, second=0, microsecond=0)

    conn = database()
    try:
        cursor = conn.cursor()
        cursor.execute('''update pointsreset set last_reset = %s
                          where last_reset < %s''', (str(now), str(monday_midnight)))
        if cursor.rowcount > 0:
            cursor.execute('update students set points = 0')
            cursor.execute('update guilds set points = 0')
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def get_guild(guild_name):
    '''returns (guild_name, leader_username, points, no_of_members) or None'''
    conn = database()
    cursor = conn.cursor()
    cursor.execute('select guild_name, leader_username, points, no_of_members from guilds where guild_name = %s',
                   (guild_name,))
    guild = cursor.fetchone()
    conn.close()
    return guild

def has_pending_request(username, guild_name):
    conn = database()
    cursor = conn.cursor()
    cursor.execute('''select 1 from guildrequests
                      where request_username = %s and guild_name = %s and status = 'pending' ''',
                   (username, guild_name))
    row = cursor.fetchone()
    conn.close()
    return row is not None

def guild_exists(guild_name):
    conn = database()
    cursor = conn.cursor()
    cursor.execute('select guild_name from guilds where guild_name = %s', (guild_name,))
    guild = cursor.fetchone()
    conn.close()
    if guild:
        return True
    return False
        

#shop queries
def get_purchased_items(item_type, username):
    conn = database()
    cursor = conn.cursor()
    
    cursor.execute('''
                   select * from shopitems
                   join purchases on purchases.item_id = shopitems.item_id
                   where shopitems.item_type = %s
                   and purchases.username = %s''', (item_type, username))
    purchased_items = cursor.fetchall()
    conn.close()
    return purchased_items

def get_shop_items(item_type, username):
    conn = database()
    cursor = conn.cursor()
    
    cursor.execute('''
                   select shopitems.* from shopitems
                   left join purchases on shopitems.item_id = purchases.item_id
                   and purchases.username = %s
                   where purchases.item_id is null
                   and shopitems.item_type = %s''', (username, item_type))
    shop_items = cursor.fetchall()
    conn.close()
    return shop_items

def get_item_price(item_id):
    conn = database()
    cursor = conn.cursor()
    
    cursor.execute('''
                   select price from shopitems
                   where item_id = %s''', (item_id, ))
    price = cursor.fetchone()
    conn.close()

    return price

def add_purchase(item_id, username):
    conn = database()
    cursor = conn.cursor()
    
    cursor.execute('''
                   insert into purchases(username, item_id)
                   values (%s, %s)''', (username, item_id))
    conn.commit()
    conn.close()

def purchase_item(username, item_id):
    '''
    buys an item in one transaction. returns "ok", "owned", "insufficient" or "missing".

    previously the route deducted coins first and then inserted the purchase in a separate
    connection, so buying an item you already owned took the coins and then raised a primary
    key violation (500). two concurrent purchases could also both pass the balance check.
    '''
    conn = database()
    try:
        cursor = conn.cursor()
        cursor.execute('select price from shopitems where item_id = %s', (item_id,))
        row = cursor.fetchone()
        if row is None:
            return "missing"
        price = row[0]
        cursor.execute('select 1 from purchases where username = %s and item_id = %s', (username, item_id))
        if cursor.fetchone():
            return "owned"
        cursor.execute('''update students set coins = coins - %s
                          where username = %s and coins >= %s''', (price, username, price))
        if cursor.rowcount == 0:
            conn.rollback()
            return "insufficient"
        cursor.execute('insert into purchases(username, item_id) values (%s, %s)', (username, item_id))
        conn.commit()
        return "ok"
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def get_item_details(item_id):
    conn = database()
    cursor = conn.cursor()
    
    cursor.execute('''
                   select item_id, item_name, item_type
                   from shopitems
                   where item_id = %s''', (item_id, ))
    item_details = cursor.fetchone()
    cursor.close()
    conn.close()

    return item_details

def equip_avatar(username, avatar_name):
    conn = database()
    cursor = conn.cursor()
    
    cursor.execute('''
                   update students
                   set avatar = %s
                   where username = %s''', (avatar_name, username))
    conn.commit()
    conn.close()

def equip_theme(username, theme_name):
    conn = database()
    cursor = conn.cursor()
    
    cursor.execute('''
                   update students
                   set theme = %s
                   where username = %s''', (theme_name, username))
    conn.commit()
    conn.close()