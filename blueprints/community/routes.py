from flask import render_template, url_for, redirect, request, session, flash
from flask_login import current_user
import backend.queries as q
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


@community_bp.route("/upload-subject", methods=["GET", "POST"])
def upload_subject():
    '''
    allows a user to upload a subject they have made to the community library
    if they have already uploaded a subject of the same name, this will be replaced
    '''
    try:
        subject_name = request.form.get("name")
        subject_object = session["library"].getChildByName(subject_name)

        existing_subject = q.check_community_subject_exists(current_user.id, subject_name)
        print(existing_subject)
        if existing_subject:
            q.delete_community_subject(existing_subject[0][0])

        q.add_community_subject(subject_object, current_user.id)

        flash("Subject added to the community library")
        return redirect(url_for("library.library"))
    
    except:
        flash("We couldn't add your subject to the community library. Please try again")
        return redirect(url_for("library.library"))
        

@community_bp.route("/upload-topic", methods=["GET", "POST"])
def upload_topic():
    '''
    allows a user to upload a topic they have made to the community library
    if they have already uploaded a topic of the same name, this will be replaced
    '''
    try:
        topic_name = request.form.get("name")
        topic_object = session["library"].current_node.getChildByName(topic_name)

        existing_topic = q.check_community_topic_exists(current_user.id, topic_name)
        if existing_topic:
            q.delete_community_topic(existing_topic[0])

        q.add_community_topic(topic_object, current_user.id)
        flash("Topic added to the community library")
        return redirect(url_for("library.subject", subject_name=topic_object.getParent().getName()))
    except:
        flash("We couldn't add your topic to the community library. Please try again")
        return redirect(url_for("library.subject", subject_name=topic_object.getParent().getName()))

@community_bp.route("/import-subject/<subject_id>/<subject_name>")
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
    except:
        flash("We couldn't add this subject to your library. Please try again")
        return redirect(url_for("library.library"))

@community_bp.route("/import-topic/<topic_id>/<topic_name>/<subject_id>")
def import_topic(topic_id, topic_name, subject_id):
    '''
    allows a user to import a community-made topic into their own library
    they will choose one of their pre-existing subjects to add this to
    '''
    try:
        if q.check_subject_exists(topic_name, current_user.id):
            flash(f"You already have a topic named {topic_name.capitalize()} in your library")
            return redirect(url_for("community.browse_topics"))
        q.import_community_topic(subject_id, topic_id, topic_name)
        flash("Topic added to your library")
        return redirect(url_for("library.library")) 
    except:
        flash("We couldn't add this topic to your library. Please try again")
        return redirect(url_for("library.library"))

@community_bp.route("/delete_subject")
def delete_community_subject():
    '''
    allows a user to delete a community subject which they had uploaded
    '''
    try:
        subject_id = request.args.get("subject_id")

        q.delete_community_subject(subject_id)
        flash("Subject deleted")
        return redirect(url_for("community.browse_subjects"))
    except:
        flash("We couldn't delete this subject. Please try again")
        return redirect(url_for("community.browse_subjects"))

@community_bp.route("/delete_topic")
def delete_community_topic():
    '''
    allows a user to delete a community subject which they had uploaded
    '''
    try:
        topic_id = request.args.get("topic_id")

        q.delete_community_topic(topic_id)
        flash("Topic deleted")
        return redirect(url_for("community.browse_topics"))
    except:
        flash("We couldn't delete this topic. Please try again")
        return redirect(url_for("community.browse_topics"))