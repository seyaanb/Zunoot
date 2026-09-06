from flask import session, render_template, redirect, url_for, flash, request, jsonify
from flask_login import current_user
import backend.queries as q
import backend.flashcard_library.library as l
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
    except Exception as e:
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
    except Exception as e:
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
            current_user.add_coins(10)
            if current_user.get_guild():
                current_user.add_points(5)
            flashcard_front = request.form.get("new-flashcard-front")
            flashcard_back = request.form.get("new-flashcard-back") 
            if flashcard_front and flashcard_back and not flashcard_front.isspace() and not flashcard_back.isspace():
                topic_node.addChild(flashcard_front, flashcard_back)
                return redirect(url_for("library.topic", subject_name=subject_node.getName(), topic_name=topic_node.getName()))

        flashcards = topic_node.getChildren()

        return render_template("library.html", title=topic_node.getName(),
                                            type="topic",
                                            flashcards=flashcards,
                                            coins=current_user.get_coins(),
                                            avatar=current_user.get_avatar(),
                                            theme=current_user.get_theme())
    except Exception as e:
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
    except Exception as e:
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
    except Exception as e:
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

        if new_name and old_name != new_name:
            current_library = l.Library(current_user.id)
            current_library.initialiseLibrary(current_user.id)
            
            # Find the topic anywhere in the library and update it
            for sub in current_library.getChildren():
                topic_node = sub.getChildByName(old_name)
                if topic_node:
                    topic_node.editName(new_name)
                    return redirect(url_for("library.subject", subject_name=sub.getName()))
        
        return redirect(url_for("library.library"))
    except Exception as e:
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

        if new_front and new_back:
            current_library = l.Library(current_user.id)
            current_library.initialiseLibrary(current_user.id)
            
            # Find the flashcard anywhere in the library and update it
            for sub in current_library.getChildren():
                for top in sub.getChildren():
                    flashcard_node = top.getChildByName(old_front)
                    if flashcard_node:
                        flashcard_node.editFlashcard(new_front, new_back)
                        return redirect(url_for("library.topic", subject_name=sub.getName(), topic_name=top.getName()))
        
        return redirect(url_for("library.library"))
    except Exception as e:
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
    except Exception as e:
        flash("We couldn't delete the item. Please try again")
        return redirect(url_for("library.library"))
    
@library_bp.route("/update-order/<itemType>", methods=["POST"])
def update_order(itemType):
    '''
    updates the order in which subjects/topics/flashcards are displayed on the screen
    '''
    order = request.json.get("order")
    q.update_order(itemType, order)
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
            
            if spaced_repetition == "true":
                session["queue"] = current_library.makeSessionQueue(True)
            else:
                session["queue"] = current_library.makeSessionQueue(False)

        next_flashcard = session["queue"].getNextFlashcard()

        if next_flashcard:
            return render_template("review.html", title="Review Flashcards",
                                                front=next_flashcard.getName(),
                                                back=next_flashcard.getBack(),
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
    except Exception as e:
        flash("Something went wrong. Please try again")
        return redirect(url_for('library.library'))

@library_bp.route("/spaced-repetition", methods=["GET","POST"])
def spaced_repetition():
    '''
    takes feedback from the user on their perceived difficulty of the flashcard
    uses this input in the SM2 spaced repetition algorithm to update the priority queue
    '''
    try:
        option = request.form.get("option")
        current_flashcard = session["queue"].getCurrentFlashcard()
        current_flashcard.reviewFlashcard(option)

        current_user.add_coins(2)
        if current_user.get_guild():
            current_user.add_points(1)

        return redirect(url_for("library.review_page"))
    except Exception as e:
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
            if session["queue"].spaced_repetition:
                deck = session["queue"].items
                q.push_deck(deck)
            session.pop("queue", None)
        flash("Your session has been ended")
        return redirect(url_for("library.library"))
    except Exception as e:
        flash("We couldn't end your session.")
        return redirect(url_for("library.library"))