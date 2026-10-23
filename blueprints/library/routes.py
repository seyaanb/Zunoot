from flask import session, render_template, redirect, url_for, flash, request, jsonify, current_app
from flask_login import current_user
import backend.queries as q
import backend.flashcard_library.library as l
from backend.session_queue import SessionQueue
from . import library_bp

@library_bp.route("/", methods=["GET", "POST"])
def library():
    '''
    a tree (library) of objects is initialised locally for the request
    the subjects within the library are rendered and an option to add new subjects is given
    '''
    try:
        username = current_user.id

        current_library = l.Library(username)
        current_library.initialiseLibrary(username)

        subjects = current_library.getChildren()

        if request.method =="POST":
            new_subject_name = request.form.get("new-subject")
            if new_subject_name and not new_subject_name.isspace() and not q.check_subject_exists(new_subject_name, current_user.id):
                current_library.addChild(new_subject_name)
                return redirect(url_for("library.library"))

        return render_template("library.html", title= f"{current_user.first_name}'s Library",
                                            type="library",
                                            subjects=subjects,
                                            coins=current_user.get_coins(),
                                            avatar=current_user.get_avatar(),
                                            theme=current_user.get_theme())
    except Exception:
        current_app.logger.exception("library.library failed")
        flash("We struggled to load your library. Please try again")
        return redirect(url_for("auth.index"))

@library_bp.route("/<subject_name>", methods=["GET", "POST"])
def subject(subject_name):
    '''
    users are taken to this route if they click on a subject in the previous route.
    the topics within that subject are rendered and an option to add new topics is given
    '''
    try:
        current_library = l.Library(current_user.id)
        current_library.initialiseLibrary(current_user.id)
        
        subject_node = current_library.getChildByName(subject_name)
        if not subject_node:
            return redirect(url_for("library.library"))
            
        topics = subject_node.getChildren()

        if request.method == "POST":
            new_topic_name = request.form.get("new-topic")
            if new_topic_name and not new_topic_name.isspace() and not q.check_topic_exists(new_topic_name, subject_node.subject_id):
                subject_node.addChild(new_topic_name)
                return redirect(url_for("library.subject", subject_name=subject_node.getName()))
        
        return render_template("library.html", title=subject_node.getName(),
                                            type="subject",
                                            current_subject=subject_node,
                                            topics=topics,
                                            coins=current_user.get_coins(),
                                            avatar=current_user.get_avatar(),
                                            theme=current_user.get_theme())
    except Exception:
        current_app.logger.exception("library.subject failed")
        flash("We struggled to load this subject. Please try again")
        return redirect(url_for("library.library"))

@library_bp.route("/<subject_name>/<topic_name>", methods=["GET", "POST"])
def topic(subject_name, topic_name):
    '''
    users are taken to this route if they click on a topic in the previous route.
    the topics within that subject are rendered and an option to add new flashcards is given
    '''
    try:
        current_library = l.Library(current_user.id)
        current_library.initialiseLibrary(current_user.id)
        
        subject_node = current_library.getChildByName(subject_name)
        if not subject_node:
            return redirect(url_for("library.library"))
            
        topic_node = subject_node.getChildByName(topic_name)
        if not topic_node:
            return redirect(url_for("library.subject", subject_name=subject_name))
        
        if request.method == "POST":
            flashcard_front = request.form.get("new-flashcard-front")
            flashcard_back = request.form.get("new-flashcard-back") 
            if flashcard_front and flashcard_back and not flashcard_front.isspace() and not flashcard_back.isspace():
                topic_node.addChild(flashcard_front, flashcard_back)
                # rewards are given only once a card has actually been created. they used to be
                # given for any POST, so submitting an empty form repeatedly farmed coins/points.
                current_user.add_coins(10)
                if current_user.get_guild():
                    current_user.add_points(5)
                return redirect(url_for("library.topic", subject_name=subject_node.getName(), topic_name=topic_node.getName()))

        flashcards = topic_node.getChildren()

        return render_template("library.html", title=topic_node.getName(),
                                            type="topic",
                                            flashcards=flashcards,
                                            coins=current_user.get_coins(),
                                            avatar=current_user.get_avatar(),
                                            theme=current_user.get_theme())
    except Exception:
        current_app.logger.exception("library.topic failed")
        flash("We struggled to load this topic. Please try again")
        return redirect(url_for("library.subject", subject_name=subject_name))

@library_bp.route("/search")
def search_library():
    '''
    names of subjects and topics, and fronts and backs of flashcards within the tree are searched for a given keyword
    '''
    try:
        current_library = l.Library(current_user.id)
        current_library.initialiseLibrary(current_user.id)
        
        keyword = request.args.get("keyword")
        results = current_library.searchLibrary(keyword)
        subject_list, topic_list, flashcard_list = results

        return render_template("library_search.html", subjects=subject_list,
                                                    topics=topic_list,
                                                    flashcards=flashcard_list,
                                                    coins=current_user.get_coins(),
                                                    avatar=current_user.get_avatar(),
                                                    theme=current_user.get_theme())
    except Exception:
        current_app.logger.exception("library.search_library failed")
        flash("We struggled to load the search results. Please try again")
        return redirect(url_for("library.library"))
    
@library_bp.route("/edit-subject", methods=["POST"])
def edit_subject():
    '''
    allows the user to update the name of a subject
    '''
    try:
        old_name = request.form.get("old-subject-name")
        new_name = request.form.get("new-subject-name")

        if new_name and old_name != new_name:
            current_library = l.Library(current_user.id)
            current_library.initialiseLibrary(current_user.id)
            subject_node = current_library.getChildByName(old_name)
            if subject_node:
                subject_node.editName(new_name)

        return redirect(url_for("library.library"))
    except Exception:
        current_app.logger.exception("library.edit_subject failed")
        flash("Something went wrong. Please try again")
        return redirect(url_for("library.library"))

@library_bp.route("/edit-topic", methods=["POST"])
def edit_topic():
    '''
    allows the user to update the name of a topic
    '''
    try:
        old_name = request.form.get("old-topic-name")
        new_name = request.form.get("new-topic-name")
        topic_id = request.form.get("topic-id")

        if new_name and old_name != new_name:
            current_library = l.Library(current_user.id)
            current_library.initialiseLibrary(current_user.id)
            
            # Find the topic in the user's library and update it. Match on ID: matching on
            # name renamed the first topic with that name in *any* subject (e.g. every
            # subject's "Chapter 1"). Name matching remains only as a fallback for pages
            # rendered before this change.
            for sub in current_library.getChildren():
                if topic_id:
                    topic_node = next((t for t in sub.getChildren() if str(t.topic_id) == topic_id), None)
                else:
                    topic_node = sub.getChildByName(old_name)
                if topic_node:
                    topic_node.editName(new_name)
                    return redirect(url_for("library.subject", subject_name=sub.getName()))
        
        return redirect(url_for("library.library"))
    except Exception:
        current_app.logger.exception("library.edit_topic failed")
        flash("Something went wrong. Please try again")
        return redirect(url_for("library.library"))

@library_bp.route("/edit-flashcard", methods=["POST"])
def edit_flashcard():
    '''
    allows the user to update the front and/or back of a flashcard
    '''
    try:
        old_front = request.form.get("old-flashcard-front")
        new_front = request.form.get("new-flashcard-front")
        new_back = request.form.get("new-flashcard-back")
        flashcard_id = request.form.get("flashcard-id")

        if new_front and new_back:
            current_library = l.Library(current_user.id)
            current_library.initialiseLibrary(current_user.id)
            
            # Find the flashcard in the user's library by ID (matching on front text edited
            # the first card with that text anywhere in the library); name is a fallback only.
            for sub in current_library.getChildren():
                for top in sub.getChildren():
                    if flashcard_id:
                        flashcard_node = next((c for c in top.getChildren()
                                               if str(c.flashcard_id) == flashcard_id), None)
                    else:
                        flashcard_node = top.getChildByName(old_front)
                    if flashcard_node:
                        flashcard_node.editFlashcard(new_front, new_back)
                        return redirect(url_for("library.topic", subject_name=sub.getName(), topic_name=top.getName()))
        
        return redirect(url_for("library.library"))
    except Exception:
        current_app.logger.exception("library.edit_flashcard failed")
        flash("Something went wrong. Please try again")
        return redirect(url_for("library.library"))
    
@library_bp.route("/delete", methods=["POST"])
def delete():
    '''
    allows the user to delete a subject, topic or flashcard
    '''
    try:
        type = request.form.get("type")
        item_id = str(request.form.get("id"))

        current_library = l.Library(current_user.id)
        current_library.initialiseLibrary(current_user.id)

        if type == "subject":
            subject_node = current_library.getChildByID(item_id)
            if subject_node:
                subject_node.deleteSubject()
                flash("Subject deleted")
            return redirect(url_for("library.library"))

        elif type == "topic":
            for sub in current_library.getChildren():
                for top in sub.getChildren():
                    if str(top.topic_id) == item_id:
                        top.deleteTopic()
                        flash("Topic deleted")
                        return redirect(url_for("library.subject", subject_name=sub.getName()))

        elif type == "flashcard":
            for sub in current_library.getChildren():
                for top in sub.getChildren():
                    for f in top.getChildren():
                        if str(f.flashcard_id) == item_id:
                            f.deleteFlashcard()
                            flash("Flashcard deleted")
                            return redirect(url_for("library.topic", subject_name=sub.getName(), topic_name=top.getName()))
                            
        return redirect(url_for("library.library"))
    except Exception:
        current_app.logger.exception("library.delete failed")
        flash("We couldn't delete the item. Please try again")
        return redirect(url_for("library.library"))
    
@library_bp.route("/update-order/<itemType>", methods=["POST"])
def update_order(itemType):
    '''
    updates the order in which subjects/topics/flashcards are displayed on the screen
    '''
    payload = request.get_json(silent=True) or {}
    order = payload.get("order")
    if itemType not in ("Subject", "Topic", "Flashcard") or not isinstance(order, list):
        return jsonify({"status": "error"}), 400
    try:
        q.update_order(itemType, order, current_user.id)
    except (KeyError, TypeError, ValueError):
        return jsonify({"status": "error"}), 400
    return jsonify({"status": "success"})

@library_bp.route('/review', methods=["GET", "POST"])
def review_page():
    '''
    initialises a session queue object and adds it to the session
    the user may click option buttons to go through the queue of flashcards
    '''
    try:
        spaced_repetition = request.form.get("spaced-repetition")

        if "queue" not in session:
            current_library = l.Library(current_user.id)
            current_library.initialiseLibrary(current_user.id)
            queue = current_library.makeSessionQueue(spaced_repetition == "true")
        else:
            queue = SessionQueue.from_dict(session["queue"])

        next_flashcard = queue.getNextFlashcard()
        # the session stores plain data only (see SessionQueue.to_dict); reassigning also
        # marks the session as modified so the advanced pointer is saved.
        session["queue"] = queue.to_dict()

        card_text = q.get_flashcard_text(next_flashcard.flashcard_id, current_user.id) if next_flashcard else None

        if card_text:
            return render_template("review.html", title="Review Flashcards",
                                                front=card_text[0],
                                                back=card_text[1],
                                                hidden="",
                                                avatar=current_user.get_avatar(),
                                                coins=current_user.get_coins(),
                                                theme=current_user.get_theme())
        
        return render_template("review.html", title="Review Flashcards",
                                            front="No flashcards remaining",
                                            back="No flashcards remaining",
                                            hidden="hidden",
                                            avatar=current_user.get_avatar(),
                                            coins=current_user.get_coins(),
                                            theme=current_user.get_theme())
    except Exception:
        current_app.logger.exception("library.review_page failed")
        flash("Something went wrong. Please try again")
        return redirect(url_for('library.library'))

@library_bp.route("/spaced-repetition", methods=["GET","POST"])
def spaced_repetition():
    '''
    takes feedback from the user on their perceived difficulty of the flashcard
    uses this input in the SM2 spaced repetition algorithm to update the priority queue
    '''
    try:
        option = int(request.form.get("option"))
        if not 0 <= option <= 5:
            raise ValueError("rating must be between 0 and 5")
        queue = SessionQueue.from_dict(session["queue"])
        current_flashcard = queue.getCurrentFlashcard()
        current_flashcard.reviewFlashcard(option)
        session["queue"] = queue.to_dict()

        current_user.add_coins(2)
        if current_user.get_guild():
            current_user.add_points(1)

        return redirect(url_for("library.review_page"))
    except Exception:
        current_app.logger.exception("library.spaced_repetition failed")
        flash("Something went wrong. Please try again")
        return redirect(url_for("library.review_page"))

@library_bp.route("/end-session", methods=["GET", "POST"])
def end_session():
    '''
    stores the state of the flashcards in the database upon the user's prompt
    removes the queue from the session
    '''
    try:
        if "queue" in session:
            queue = SessionQueue.from_dict(session["queue"])
            if queue.spaced_repetition:
                q.push_deck(queue.items, current_user.id)
            session.pop("queue", None)
        flash("Your session has been ended")
        return redirect(url_for("library.library"))
    except Exception:
        current_app.logger.exception("library.end_session failed")
        flash("We couldn't end your session.")
        return redirect(url_for("library.library"))