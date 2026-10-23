from flask import render_template, url_for, redirect, request, flash, current_app
from flask_login import current_user
import backend.queries as q
import backend.flashcard_library.library as l
from . import community_bp


@community_bp.route("/")
def community():
    '''
    renders a page which allows users to choose whether they want to browse user-uploaded subjects or topics
    '''
    return render_template("community.html", coins=current_user.get_coins(),
                                             avatar=current_user.get_avatar(),
                                             theme=current_user.get_theme())

@community_bp.route("/browse-subjects")
def browse_subjects():

    '''
    renders all subjects previously uploaded by current users
    '''

    keyword = request.args.get("keyword")

    if keyword:
        subjects = q.get_community_subjects_from_keyword(keyword)
    else:
        subjects = q.get_community_subjects()

    return render_template("browse_subjects.html", subjects=subjects,
                                                   user=current_user.id,
                                                   coins=current_user.get_coins(),
                                                   avatar=current_user.get_avatar(),
                                                   theme=current_user.get_theme())

@community_bp.route("/browse-subjects/<subject_id>/<subject_name>")
def view_subject(subject_id, subject_name):
    '''
    allows a user to see the topics and flashcards within a subject which has been uploaded by another user
    '''
    children = {}

    topics = q.get_community_topics_from_subject(subject_id)
    for topic in topics:
        flashcards = q.get_community_flashcards(topic[0])
        children[topic[1]] = flashcards 

    return render_template("view_community_subject.html", children=children, subject_name=subject_name, subject_id=subject_id,
                           coins=current_user.get_coins(),
                           avatar=current_user.get_avatar(),
                           theme=current_user.get_theme())

@community_bp.route("/browse-topics")
def browse_topics():

    '''
    renders all topics previously uploaded by current users
    '''

    keyword = request.args.get("keyword")
    if keyword:
        topics = q.get_community_topics_from_keyword(keyword)
    else:
        topics = q.get_community_topics()


    return render_template("browse_topics.html", topics=topics,
                                                 user=current_user.id,
                                                 coins=current_user.get_coins(),
                                                 avatar=current_user.get_avatar(),
                                                 theme=current_user.get_theme())

@community_bp.route("/browse-topics/<topic_id>/<topic_name>")
def view_topic(topic_id, topic_name):

    '''
    allows a user to see the topics and flashcards within a subject which has been uploaded by another user
    '''

    flashcards = q.get_community_flashcards(topic_id)

    subjects = q.get_children("Library", current_user.id)


    return render_template("view_community_topic.html", flashcards=flashcards, topic_name=topic_name, topic_id=topic_id, user_subjects=subjects,
                           coins=current_user.get_coins(),
                           avatar=current_user.get_avatar(),
                           theme=current_user.get_theme())


def _load_library():
    library = l.Library(current_user.id)
    library.initialiseLibrary(current_user.id)
    return library


@community_bp.route("/upload-subject", methods=["POST"])
def upload_subject():
    '''
    allows a user to upload a subject they have made to the community library
    if they have already uploaded a subject of the same name, this will be replaced

    this used to read session["library"], which stopped existing when the library tree was
    moved out of the session, so every upload failed. the subject is now loaded from the
    database, and the replace + insert happen in one transaction.
    '''
    try:
        subject_name = request.form.get("name")
        subject_object = _load_library().getChildByName(subject_name)
        if subject_object is None:
            flash("We couldn't find that subject")
            return redirect(url_for("library.library"))

        q.add_community_subject(subject_object, current_user.id)

        flash("Subject added to the community library")
        return redirect(url_for("library.library"))
    
    except Exception:
        current_app.logger.exception("Community subject upload failed")
        flash("We couldn't add your subject to the community library. Please try again")
        return redirect(url_for("library.library"))
        

@community_bp.route("/upload-topic", methods=["POST"])
def upload_topic():
    '''
    allows a user to upload a topic they have made to the community library
    if they have already uploaded a topic of the same name, this will be replaced

    previously read session["library"] (gone, so it always failed) and its error handler
    referenced a variable that was never assigned, turning the failure into a 500.
    '''
    subject_name = request.form.get("subject")
    try:
        topic_name = request.form.get("name")
        subject_object = _load_library().getChildByName(subject_name)
        topic_object = subject_object.getChildByName(topic_name) if subject_object else None
        if topic_object is None:
            flash("We couldn't find that topic")
            return redirect(url_for("library.library"))

        q.add_community_topic(topic_object, current_user.id)
        flash("Topic added to the community library")
        return redirect(url_for("library.subject", subject_name=subject_name))
    except Exception:
        current_app.logger.exception("Community topic upload failed")
        flash("We couldn't add your topic to the community library. Please try again")
        if subject_name:
            return redirect(url_for("library.subject", subject_name=subject_name))
        return redirect(url_for("library.library"))

@community_bp.route("/import-subject/<subject_id>/<subject_name>", methods=["POST"])
def import_subject(subject_id, subject_name):
    '''
    allows a user to import a community-made subject into their own library
    '''
    try:
        if q.check_subject_exists(subject_name, current_user.id):
            flash(f"You already have a subject named {subject_name.capitalize()} in your library")
            return redirect(url_for("community.browse_subjects"))
        q.import_community_subject(current_user.id, subject_id, subject_name)
        flash("Subject added to your library")
        return redirect(url_for("library.library"))
    except Exception:
        current_app.logger.exception("Community subject import failed")
        flash("We couldn't add this subject to your library. Please try again")
        return redirect(url_for("library.library"))

@community_bp.route("/import-topic/<topic_id>/<topic_name>/<subject_id>", methods=["POST"])
def import_topic(topic_id, topic_name, subject_id):
    '''
    allows a user to import a community-made topic into their own library
    they will choose one of their pre-existing subjects to add this to

    previously: the target subject was not checked, so a topic could be imported into another
    user's subject; and the duplicate check looked for a *subject* with the topic's name
    rather than a topic of that name inside the chosen subject.
    '''
    try:
        if not q.subject_belongs_to_user(subject_id, current_user.id):
            flash("We couldn't find that subject in your library")
            return redirect(url_for("community.browse_topics"))
        if q.check_topic_exists(topic_name, subject_id):
            flash(f"You already have a topic named {topic_name.capitalize()} in that subject")
            return redirect(url_for("community.browse_topics"))
        q.import_community_topic(subject_id, topic_id, topic_name)
        flash("Topic added to your library")
        return redirect(url_for("library.library")) 
    except Exception:
        current_app.logger.exception("Community topic import failed")
        flash("We couldn't add this topic to your library. Please try again")
        return redirect(url_for("library.library"))

@community_bp.route("/delete_subject", methods=["POST"])
def delete_community_subject():
    '''
    allows a user to delete a community subject which they had uploaded
    (previously anyone could delete anyone's upload by ID, via a CSRF-able GET)
    '''
    try:
        subject_id = request.form.get("subject_id")

        if q.delete_community_subject(subject_id, current_user.id):
            flash("Subject deleted")
        else:
            flash("You can only delete subjects you uploaded")
        return redirect(url_for("community.browse_subjects"))
    except Exception:
        current_app.logger.exception("Community subject delete failed")
        flash("We couldn't delete this subject. Please try again")
        return redirect(url_for("community.browse_subjects"))

@community_bp.route("/delete_topic", methods=["POST"])
def delete_community_topic():
    '''
    allows a user to delete a community topic which they had uploaded
    '''
    try:
        topic_id = request.form.get("topic_id")

        if q.delete_community_topic(topic_id, current_user.id):
            flash("Topic deleted")
        else:
            flash("You can only delete topics you uploaded")
        return redirect(url_for("community.browse_topics"))
    except Exception:
        current_app.logger.exception("Community topic delete failed")
        flash("We couldn't delete this topic. Please try again")
        return redirect(url_for("community.browse_topics"))
