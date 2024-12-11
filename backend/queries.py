import sqlite3
import backend.session_queue as sq
from backend.flashcard_library import flashcard as f
from datetime import datetime, timezone, timedelta

def database():
    return sqlite3.connect("test.db")

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
    cursor.execute("PRAGMA foreign_keys = ON;")
    cursor.execute("select * from flashcards")
    deck = cursor.fetchall()
    conn.close()
    return deck


def push_deck(deck):
    conn = database()
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_keys = ON;")
    for flashcard in deck:
        sql = '''
        UPDATE flashcards
        SET front = ?, back = ?, review_interval = ?, repetition_no = ?, easiness_factor = ?,
            last_review = ?, next_review = ?
        WHERE front = ?
        '''
        
        front = flashcard.getName()
        back = flashcard.getBack()
        interval = flashcard.interval
        repetition_no = flashcard.repetition_no
        easiness_factor = round(flashcard.easiness_factor, 2)
        last_review = flashcard.last_review
        next_review = flashcard.next_review
        
        cursor.execute(sql, (front, back, interval, repetition_no, easiness_factor,
                             last_review, next_review, front))
        
        conn.commit()
    conn.close()

def delete_subject(subject_id):
    conn = database()
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_keys = ON;")
    cursor.execute('''
                   delete from subjects
                   where subject_id = ?''', (int(subject_id),))
    conn.commit()
    conn.close()

def delete_topic(topic_id):
    conn = database()
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_keys = ON;")
    cursor.execute('''
                   delete from topics
                   where topic_id = ?''', (int(topic_id),))
    conn.commit()
    conn.close()

def delete_flashcard(flashcard_id):
    conn = database()
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_keys = ON;")
    cursor.execute('''
                   delete from flashcards
                   where flashcard_id = ?''', (int(flashcard_id),))
    conn.commit()
    conn.close()

def get_new_subject_position(username):
    conn = database()
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_keys = ON;")
    cursor.execute('''select MAX(position) from subjects where username = ?''', (username,))
    max_position = cursor.fetchone()[0]
    conn.close()
    if max_position is not None:
        return max_position + 1
    else:
        return 0

def get_new_topic_position(subject_id):
    conn = database()
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_keys = ON;")
    cursor.execute('''select max(position) from topics where subject_id = ?''', (subject_id,))
    max_position = cursor.fetchone()[0]
    conn.close()
    if max_position is not None:
        return max_position + 1
    else:
        return 0
    
def get_new_flashcard_position(topic_id):
    conn = database()
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_keys = ON;")
    cursor.execute('''select max(position) from flashcards where topic_id = ?''', (topic_id,))
    max_position = cursor.fetchone()[0]
    conn.close()
    if max_position is not None:
        return max_position + 1
    else:
        return 0
    

def add_subject(subject_name, username):
    conn = database()
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_keys = ON;")
    position = get_new_subject_position(username)
    cursor.execute('''
                   insert into subjects(subject_name, username, position)
                   values (?, ?, ?)''', (subject_name, username, position))
    conn.commit()

    subject_id = cursor.lastrowid
    conn.close()

    return subject_id

def add_topic(topic_name, subject_id):
    conn = database()
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_keys = ON;")
    position = get_new_topic_position(subject_id)
    cursor.execute('''
                   insert into topics(topic_name, subject_id, position)
                   values (?, ?, ?)''', (topic_name, subject_id, position))
    conn.commit()

    topic_id = cursor.lastrowid
    conn.close()

    return topic_id

def add_flashcard(front, back, topic_id):
    conn = database()
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_keys = ON;")
    position = get_new_flashcard_position(topic_id)
    cursor.execute('''
                   insert into flashcards(front, back, topic_id, position)
                   values (?, ?, ?, ?)''', (front, back, topic_id, position))
    conn.commit()
    conn.close()

def get_children(current_class, id):
    conn = database()
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_keys = ON;")

    table = child_tables[current_class]
    id_name = ids[current_class]

    query = f"select * from {table} where {id_name} = ? order by position"
    cursor.execute(query, (id,))
    children = cursor.fetchall()
    conn.close()
    return children

def edit_subject_name(subject_id, new_name):
    conn = database()
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_keys = ON;")

    query = f'''update subjects
                set subject_name = ?
                where subject_id = {subject_id}'''
    cursor.execute(query, (new_name,))
    conn.commit()
    conn.close()

def edit_topic_name(topic_id, new_name):
    conn = database()
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_keys = ON;")

    query = f'''update topics
                set topic_name = ?
                where topic_id = {topic_id}'''
    cursor.execute(query, (new_name,))
    conn.commit()
    conn.close()

def edit_flashcard(flashcard_id, front, back):
    conn = database()
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_keys = ON;")

    query = f'''update flashcards
                set front = ?, back = ?
                where flashcard_id = {flashcard_id}'''
    cursor.execute(query, (front, back))
    conn.commit()
    conn.close()

def check_subject_exists(subject, username):
    conn = database()
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_keys = ON;")
    cursor.execute("select * from subjects where subject_name = ? and username = ?", (subject, username))
    subject = cursor.fetchone()
    if subject:
        return True
    return False

def check_topic_exists(topic, subject_id):
    conn = database()
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_keys = ON;")
    cursor.execute("select * from topics where topic_name = ? and subject_id = ?", (topic, subject_id))
    topic = cursor.fetchone()
    if topic:
        return True
    return False

def get_subject_id(subject, username):
    conn = database()
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_keys = ON;")
    cursor.execute("select subject_id from subjects where subject_name = ? and username = ?", (subject, username))
    subject_id = int(cursor.fetchone()[0])
    
    return subject_id

def get_topic_id(topic, subject_id):
    conn = database()
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_keys = ON;")
    cursor.execute("select topic_id from topics where topic_name = ? and subject_id = ?", (topic, subject_id))
    topic_id = int(cursor.fetchone()[0])
    
    return topic_id

def update_order(item_type, order):
    conn = database()
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_keys = ON;")
    
    for item in order:
        sql = f'''update {item_type.lower()}s set position = ? where {ids[item_type]} = ?'''
        cursor.execute(sql, (item["position"], item["id"]))
    conn.commit()
    conn.close()


#community queries
def add_community_subject(subject_object, username):
    conn = database()
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_keys = ON;")
    cursor.execute("insert into communitysubjects (community_subject_name, uploader_username) values (?, ?) ", (subject_object.getName(), username))
    conn.commit()
    subject_id = cursor.lastrowid
    for topic in subject_object.children:
        cursor.execute("PRAGMA foreign_keys = ON;")
        cursor.execute("insert into communitytopics (community_topic_name, community_subject_id, uploader_username) values (?, ?, ?)", (topic.getName(), subject_id, username))
        conn.commit()
        topic_id = cursor.lastrowid
        for flashcard in topic.children:
            cursor.execute("PRAGMA foreign_keys = ON;")
            cursor.execute("insert into communityflashcards (community_topic_id, front, back) values (?, ?, ?)", (topic_id, flashcard.getName(), flashcard.getBack()))
            conn.commit()
    conn.close()

def add_community_topic(topic_object, username):
    conn = database()
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_keys = ON;")
    cursor.execute("insert into communitytopics (community_topic_name, uploader_username) values (?, ?)", (topic_object.getName(), username))
    conn.commit()
    topic_id = cursor.lastrowid
    for flashcard in topic_object.children:
        cursor.execute("PRAGMA foreign_keys = ON;")
        cursor.execute("insert into communityflashcards (community_topic_id, front, back) values (?, ?, ?)", (topic_id, flashcard.getName(), flashcard.getBack()))
        conn.commit()
    conn.close()

def get_community_subjects():
    conn = database()
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_keys = ON;")
    cursor.execute("select * from communitysubjects order by community_subject_name asc")
    subjects = cursor.fetchall()
    conn.close()

    return subjects

def get_community_subjects_from_keyword(keyword):
    conn = database()
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_keys = ON;")
    query = f"select * from communitysubjects where community_subject_name like '%{keyword}%' order by community_subject_name asc"
    cursor.execute(query)
    subjects = cursor.fetchall()
    conn.close()

    return subjects


def get_community_topics_from_subject(subject_id):
    conn = database()
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_keys = ON;")
    cursor.execute('''select community_topic_id, community_topic_name
                      from communitytopics
                      where community_subject_id = ?
                      order by community_topic_name asc''', (subject_id,))
    topics = cursor.fetchall()

    return topics

def get_community_topics():
    conn = database()
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_keys = ON;")
    cursor.execute("select * from communitytopics order by community_topic_name asc")
    topics = cursor.fetchall()
    conn.close()

    return topics

def get_community_topics_from_keyword(keyword):
    conn = database()
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_keys = ON;")
    query = f"select * from communitytopics where community_topic_name like '%{keyword}%' order by community_topic_name asc"
    cursor.execute(query)
    topics = cursor.fetchall()
    conn.close()

    return topics

def get_community_flashcards(topic_id):
    conn = database()
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_keys = ON;")
    cursor.execute('''select community_flashcard_id, front, back
                      from communityflashcards
                      where community_topic_id = ?
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


def delete_community_subject(subject_id):
    conn = database()
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_keys = ON;")
    cursor.execute(''' delete from communitysubjects
                       where community_subject_id = ?''', (subject_id,))
    conn.commit()
    conn.close()

def delete_community_topic(topic_id):
    conn = database()
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_keys = ON;")
    cursor.execute(''' delete from communitytopics
                       where community_topic_id = ?''', (topic_id,))
    conn.commit()
    conn.close()

def check_community_subject_exists(username, subject_name):
    conn = database()
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_keys = ON;")
    cursor.execute('''select community_subject_id from communitysubjects
                   where uploader_username = ? and community_subject_name = ?''', (username, subject_name))
    subject = cursor.fetchall()
    return subject

def check_community_topic_exists(username, topic_name):
    conn = database()
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_keys = ON;")
    cursor.execute('''
                   select community_topic_id from communitytopics
                   where uploader_username = ? and community_topic_name = ?''', (username, topic_name))
    topic = cursor.fetchall()
    return topic



#user queries
def check_user_exists(username):
    conn = database()
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_keys = ON;")
    cursor.execute("select * from students where username = ?", (username,))
    user = cursor.fetchall()
    conn.close()
    if user:
        return True
    return False
    
def insert_new_user(username, first_name, last_name, password_hash, email_address):
    conn = database()
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_keys = ON;")
    cursor.execute('''
                   insert into students(username, first_name, last_name, password, email_address, date_joined)
                   values(?, ?, ?, ?, ?, ?)
                   ''', (username, first_name, last_name, password_hash, email_address, datetime.now().date()))
    conn.commit()
    cursor.execute("PRAGMA foreign_keys = ON;")
    cursor.execute('''
                   insert into purchases (username, item_id)
                   values (?, 1)''', (username,))
    conn.commit()
    cursor.execute("PRAGMA foreign_keys = ON;")
    cursor.execute('''
                   insert into purchases (username, item_id)
                   values (?, 13)''', (username,))
    conn.commit()
    conn.close()

def get_user(username):
    conn = database()
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_keys = ON;")
    cursor.execute('''
                   select * from students
                   where username = ?
                   ''', (username,))
    user = cursor.fetchone()
    conn.close()
    return user 

def get_user_guild(username):
    conn = database()
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_keys = ON;")
    cursor.execute('''
                   select guild_name from students
                   where username = ?
                   ''', (username,))
    user = cursor.fetchone()
    conn.close()
    return user

def add_coins_db(username, quantity):
    conn = database()
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_keys = ON;")
    cursor.execute('''
                   update students
                   set coins = coins + ?
                   where username = ?''', (quantity, username))
    conn.commit()
    conn.close()

def add_points_db(username, quantity):
    conn = database()
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_keys = ON;")
    cursor.execute('''
                   update students
                   set points = points + ?
                   where username = ?''', (quantity, username))
    conn.commit()
    conn.close()

    user_guild = get_user_guild(username)
    print(user_guild)
    if user_guild:
        conn = database()
        cursor = conn.cursor()
        cursor.execute("PRAGMA foreign_keys = ON;")
        cursor.execute('''
                       update guilds
                       set points = points + ?
                       where guild_name = ?''', (quantity, user_guild[0]))
        conn.commit()
        conn.close()

def delete_user(username):
    conn = database()
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_keys = ON;")
    cursor.execute('''delete from students
                      where username = ?''', (username,))
    conn.commit()
    conn.close()


#guild queries
def create_guild(guild_name, leader_username):
    conn = database()
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_keys = ON;")
    cursor.execute('''
                   insert into guilds(guild_name, leader_username)
                   values (?, ?)''', (guild_name, leader_username))
    conn.commit()
    conn.close()

def get_all_guilds():
    conn = database()
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_keys = ON;")
    cursor.execute('''
                   select * from guilds
                   where no_of_members < 50''')
    guilds = cursor.fetchall()

    conn.close()
    
    return guilds

def join_guild(username, guild_name, user_role):
    conn = database()
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_keys = ON;")
    cursor.execute('''update students
                      set guild_name = ?, guild_role = ?
                      where username = ?''', (guild_name, user_role, username))
    conn.commit()
    conn.close()

    conn = database()
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_keys = ON;")
    cursor.execute('''update guilds
                      set no_of_members = no_of_members + 1''')
    conn.commit()
    conn.close()


def request_guild(username, guild_name):
    conn = database()
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_keys = ON;")
    cursor.execute('''insert into guildrequests(request_username, status, guild_name)
                      values(?, "pending", ?)''', (username, guild_name))
    conn.commit()
    conn.close()

def get_user_requests(username):
    conn = database()
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_keys = ON;")
    cursor.execute('''
                   select * from guildrequests
                   where request_username = ?
                   and status = "pending"''', (username, ))
    requests = cursor.fetchall()
    conn.close()
    return requests

def delete_user_requests(username):
    conn = database()
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_keys = ON;")
    cursor.execute('''delete from guildrequests
                      where request_username = ?''', (username,))
    conn.commit()
    conn.close()

def get_guild_requests(guild_name):
    conn = database()
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_keys = ON;")
    cursor.execute('''select * from guildrequests
                   where guild_name = ?
                   and status = "pending"''', (guild_name, ))
    requests = cursor.fetchall()
    conn.close()
    return requests

def accept_guild_request(username, guild_name):
    conn = database()
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_keys = ON;")
    cursor.execute('''
                   update guildrequests
                   set status = "accepted"
                   where request_username = ?
                   and guild_name = ?''', (username, guild_name))
    conn.commit()
    conn.close()

def reject_guild_request(username, guild_name):
    conn = database()
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_keys = ON;")
    cursor.execute('''
                   update guildrequests
                   set status = "declined"
                   where request_username = ?
                   and guild_name = ?''', (username, guild_name))
    conn.commit()
    conn.close()

def delete_guild(current_user):
    guild_name = current_user.get_guild()
    conn = database()
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_keys = ON;")

    cursor.execute('''
                   update students
                   set guild_role = null, points = 0, guild_name = null
                   where guild_name = ?''', (guild_name,))
    conn.commit()

    cursor.execute("PRAGMA foreign_keys = ON;")
    cursor.execute('''
                   delete from guilds
                   where guild_name = ?''', (guild_name,))
    conn.commit()
    conn.close()

def leave_guild(current_user):
    username = current_user.id
    guild_name = current_user.get_guild()
    conn = database()
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_keys = ON;")

    cursor.execute('''select points from students
                   where username = ?''', (username,))
    points = cursor.fetchone()

    cursor.execute('''update guilds
                   set points = points - ?, no_of_members = no_of_members - 1
                   where guild_name = ?''', (points[0], guild_name))
    conn.commit()

    cursor.execute("PRAGMA foreign_keys = ON;")
    cursor.execute('''
                   update students
                   set guild_name = null, guild_role = null, points = 0
                   where username = ?''', (username,))
    conn.commit()
    conn.close()

def get_intra_leaderboard(guild_name):
    conn = database()
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_keys = ON;")
    cursor.execute('''select avatar, username, points from students
                    where guild_name = ?
                   order by points desc''', (guild_name,))
    leaderboard = cursor.fetchall()
    print(leaderboard)
    conn.close()
    return leaderboard

def get_inter_leaderboard():
    conn = database()
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_keys = ON;")
    cursor.execute('''select guild_name, points from guilds
                   order by points desc''')
    leaderboard = cursor.fetchall()
    conn.close()
    return leaderboard

def points_reset():
    conn = database()
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_keys = ON;")
    cursor.execute('''select last_reset from pointsreset''')
    last_reset = cursor.fetchone()[0]


    now = datetime.now(timezone.utc).replace(tzinfo=None)
    monday = now - timedelta(days=now.weekday())
    monday_midnight = monday.replace(hour=0, minute=0, second=0, microsecond=0)

    if last_reset < str(monday_midnight):
        conn = database()
        cursor = conn.cursor()
        cursor.execute("PRAGMA foreign_keys = ON;")
        cursor.execute('update students set points = 0')
        cursor.execute('update guilds set points = 0')               
        cursor.execute('update pointsreset set last_reset = ?', (now,))
        conn.commit()
    conn.close()

def guild_exists(guild_name):
    conn = database()
    cursor = conn.cursor()
    cursor.execute('select guild_name from guilds where guild_name = ?', (guild_name,))
    guild = cursor.fetchone()
    if guild:
        return True
    return False
        

#shop queries
def get_purchased_items(item_type, username):
    conn = database()
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_keys = ON;")
    cursor.execute('''
                   select * from shopitems
                   join purchases on purchases.item_id = shopitems.item_id
                   where shopitems.item_type = ? 
                   and purchases.username = ?''', (item_type, username))
    purchased_items = cursor.fetchall()
    return purchased_items

def get_shop_items(item_type, username):
    conn = database()
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_keys = ON;")
    cursor.execute('''
                   select shopitems.* from shopitems
                   left join purchases on shopitems.item_id = purchases.item_id
                   and purchases.username = ?
                   where purchases.item_id is null
                   and shopitems.item_type = ?''', (username, item_type))
    shop_items = cursor.fetchall()
    return shop_items

def get_item_price(item_id):
    conn = database()
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_keys = ON;")
    cursor.execute('''
                   select price from shopitems
                   where item_id = ?''', (item_id, ))
    price = cursor.fetchone()

    return price

def add_purchase(item_id, username):
    conn = database()
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_keys = ON;")
    cursor.execute('''
                   insert into purchases(username, item_id)
                   values (?, ?)''', (username, item_id))
    conn.commit()
    conn.close()

def get_item_details(item_id):
    conn = database()
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_keys = ON;")
    cursor.execute('''
                   select item_id, item_name, item_type
                   from shopitems
                   where item_id = ?''', (item_id, ))
    item_details = cursor.fetchone()
    cursor.close()
    conn.close()

    return item_details

def equip_avatar(username, avatar_name):
    conn = database()
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_keys = ON;")
    cursor.execute('''
                   update students
                   set avatar = ?
                   where username = ?''', (avatar_name, username))
    conn.commit()
    conn.close()

def equip_theme(username, theme_name):
    conn = database()
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_keys = ON;")
    cursor.execute('''
                   update students
                   set theme = ?
                   where username = ?''', (theme_name, username))
    conn.commit()
    conn.close()

def give_coins():
    conn = database()
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_keys = ON;")
    cursor.execute('''
                   update students set coins = 10000000 where username = "sbudhkar"
                   ''')
    conn.commit()
    conn.close()