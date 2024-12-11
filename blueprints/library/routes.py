from flask import session, render_template, redirect, url_for, flash, request, jsonify
from flask_login import current_user
import backend.queries as q
import backend.flashcard_library.library as l
from . import library_bp


@library_bp.route("/", methods=["GET", "POST"])
def library():
    '''
    a tree (library) of objects (subjects, topics and flashcards) is initialised
    the tree is added to the session
    the subjects within the library are rendered and an option to add new subjects is given
    '''
    try:
        username = current_user.id

        session["library"] = l.Library(username)
        session["library"].initialiseLibrary(username)

        subjects = session["library"].getChildren()

        if request and request.method =="POST":
            new_subject_name = request.form.get("new-subject")
            if new_subject_name and not new_subject_name.isspace() and not q.check_subject_exists(new_subject_name, current_user.id):
                session["library"].addChild(new_subject_name)
                return redirect(url_for("library.library"))

        return render_template("library.html", title= f"{current_user.first_name}'s Library",
                                            type="library",
                                            subjects=subjects,
                                            coins=current_user.get_coins(),
                                            avatar=current_user.get_avatar(),
                                            theme=current_user.get_theme())
    except:
        flash("We struggled to load your library. Please try again")
        return redirect(url_for("auth.index"))

@library_bp.route("/<subject_name>", methods=["GET", "POST"])
def subject(subject_name):
    '''
    users are taken to this route if they click on a subject in the previous route.
    the topics within that subject are rendered and an option to add new topics is given

    param subject_name: a string representing the name of the subject clicked by the user
    '''

    try:
        session["library"].initialiseLibrary(current_user.id)
        
        subject = session["library"].getChildByName(subject_name)
        session["library"].updateCurrentNode(subject)
        topics = subject.getChildren()
        

        if request and request.method == "POST":
            new_topic_name = request.form.get("new-topic")
            if new_topic_name and not new_topic_name.isspace() and not q.check_topic_exists(new_topic_name, subject.subject_id):
                subject.addChild(new_topic_name)
                session["library"].initialiseLibrary(current_user.id)
                return redirect(url_for("library.subject", subject_name=subject.getName()))
        
        return render_template("library.html", title=subject.getName(),
                                            type="subject",
                                            current_subject=subject,
                                            topics=topics,
                                            coins=current_user.get_coins(),
                                            avatar=current_user.get_avatar(),
                                            theme=current_user.get_theme())
    except:
        flash("We struggled to load this subject. Please try again")
        return redirect(url_for("library.library"))

@library_bp.route("/<subject_name>/<topic_name>", methods=["GET", "POST"])
def topic(subject_name, topic_name):
    '''
    users are taken to this route if they click on a topic in the previous route.
    the topics within that subject are rendered and an option to add new flashcards is given

    param topic_name: a string representing the name of the topic clicked by the user
    '''
    try:
        session["library"].initialiseLibrary(current_user.id)
        subject = session["library"].getChildByName(subject_name)
        topic = subject.getChildByName(topic_name)
        session["library"].updateCurrentNode(topic)
        

        if request and request.method == "POST":
            current_user.add_coins(10)
            if current_user.get_guild():
                current_user.add_points(5)
            flashcard_front = request.form.get("new-flashcard-front")
            flashcard_back = request.form.get("new-flashcard-back") 
            if flashcard_front and flashcard_back and not flashcard_front.isspace() and not flashcard_back.isspace():
                topic.addChild(flashcard_front, flashcard_back)
                session["library"].initialiseLibrary(current_user.id)
                return redirect(url_for("library.topic", subject_name=subject.getName(), topic_name=topic.getName()))

        flashcards = topic.getChildren()

        return render_template("library.html", title=topic.getName(),
                                            type="topic",
                                            flashcards=flashcards,
                                            coins=current_user.get_coins(),
                                            avatar=current_user.get_avatar(),
                                            theme=current_user.get_theme())
    except:
        flash("We struggled to load this topic. Please try again")
        return redirect(url_for("library.subject", subject_name=subject_name))

@library_bp.route("/search")
def search_library():
    '''
    names of subjects and topics, and fronts and backs of flashcards within the tree are searched for a given keyword
    subjects, topics and/or flashcards found are displayed to the user
    '''

    try:
        keyword = request.args.get("keyword")
        results = session["library"].searchLibrary(keyword)
        subject_list, topic_list, flashcard_list = results


        return render_template("library_search.html", subjects=subject_list,
                                                    topics=topic_list,
                                                    flashcards=flashcard_list,
                                                    coins=current_user.get_coins(),
                                                    avatar=current_user.get_avatar(),
                                                    theme=current_user.get_theme())
    except:
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
            subject = session["library"].getChildByName(old_name)
            subject.editName(new_name)

        return redirect(url_for("library.library"))

    except:
        flash("Something went wrong. Please try again")
        return redirect(url_for("library.library"))

@library_bp.route("/edit-topic", methods=["POST"])
def edit_topic():
    '''
    allows the user to update the name of a topic
    '''
    try:
        subject = session["library"].current_node
        old_name = request.form.get("old-topic-name")
        new_name = request.form.get("new-topic-name")

        if new_name and old_name != new_name:
            topic = subject.getChildByName(old_name)
            topic.editName(new_name)
            session["library"].initialiseLibrary(current_user.id)
        
        return redirect(url_for("library.subject", subject_name=subject.getName()))
    except:
        flash("Something went wrong. Please try again")
        return redirect(url_for("library.subject", subject_name=subject.getName()))

@library_bp.route("/edit-flashcard", methods=["POST"])
def edit_flashcard():
    '''
    allows the user to update the front and/or back of a flashcard
    '''
    try:
        topic = session["library"].current_node
        old_front = request.form.get("old-flashcard-front")
        new_front = request.form.get("new-flashcard-front")
        new_back = request.form.get("new-flashcard-back")


        if new_front and new_back:
            flashcard = topic.getChildByName(old_front)
            flashcard.editFlashcard(new_front, new_back)
            session["library"].initialiseLibrary(current_user.id)
        
        subject = topic.getParent()
        
        return redirect(url_for("library.topic", subject_name=subject.getName(), topic_name=topic.getName()))
    except:
        flash("Something went wrong. Please try again")
        return redirect(url_for("library.topic", subject_name=subject.getName(), topic_name = topic.getName()))
    

@library_bp.route("/delete", methods=["POST"])
def delete():
    '''
    allows the user to delete a subject, topic or flashcard
    '''

    try:
        type = request.form.get("type")
        id = request.form.get("id")

        parent = session["library"].current_node
        current_node = parent.getChildByID(id)


        if type == "subject":
            current_node.deleteSubject()
            flash("Subject deleted")
            return redirect(url_for("library.library"))

        elif type == "topic":
            current_node.deleteTopic()
            session["library"].initialiseLibrary(current_user.id)
            flash("Topic deleted")
            return redirect(url_for("library.subject", subject_name=parent.getName()))


        elif type == "flashcard":
            current_node.deleteFlashcard()
            subject = parent.getParent()
            session["library"].initialiseLibrary(current_user.id)
            flash("Flashcard deleted")
            return redirect(url_for("library.topic", subject_name=subject.getName(), topic_name=parent.getName()))
    except:
        ("We couldn't delete the item. Please try again")
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
            if spaced_repetition == "true":
                session["queue"] = session["library"].makeSessionQueue(True)
            else:
                session["queue"] = session["library"].makeSessionQueue(False)

        next_flashcard = session["queue"].getNextFlashcard()

        
        if next_flashcard:
            front = next_flashcard.getName()
            back = next_flashcard.getBack()
            return render_template("review.html", title="Review Flashcards",
                                                front=front,
                                                back=back,
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
    except:
        flash("Something went wrong. Please try again")
        return redirect("url_for('library.library')")

@library_bp.route("/spaced-repetition", methods=["GET","POST"])
def spaced_repetition():
    '''
    takes feedback from the user on their perceived difficulty of the flashcard
    uses this input in the SM2 spaced repetition algorithm to update the priority queue
    gives users coins and points for reviewing a flashcard
    '''
    try:
        option = request.form.get("option")
        current_flashcard = session["queue"].getCurrentFlashcard()
        current_flashcard.reviewFlashcard(option)

        current_user.add_coins(2)

        if current_user.get_guild():
            current_user.add_points(1)

        return redirect(url_for("library.review_page"))
    except:
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
    except:
        flash("We couldn't end your session.")
        return redirect(url_for("library.library"))
