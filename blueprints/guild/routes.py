from flask import render_template, redirect, url_for, flash, request
from flask_login import current_user
import backend.queries as q
from . import guild_bp


@guild_bp.route("/guild")
def guild():

    '''
    if the user is in a guild, a leaderboard of the guild's members will be displayed as well as a leaderboard ranking every guild
    if the user is the leader of their guild, a requests tab will be present, allowing them to accept or reject requests from other users
    if the user is not in a guild, an option to create a guild will be displayed as well as the option to request to join any current guild
    '''

    q.points_reset()

    guild = current_user.get_guild()
    guilds = q.get_all_guilds()
    guild_requests = q.get_guild_requests(guild)
    role = current_user.get_guild_role()
    intra_leaderboard = q.get_intra_leaderboard(guild)
    inter_leaderboard = q.get_inter_leaderboard()

    return render_template("guild.html", guild=guild,
                                        guilds=guilds,
                                        guild_requests=guild_requests,
                                        role=role,
                                        coins=current_user.get_coins(),
                                        avatar=current_user.get_avatar(),
                                        intra_leaderboard=intra_leaderboard,
                                        inter_leaderboard=inter_leaderboard,
                                        theme=current_user.get_theme())


MAX_GUILD_MEMBERS = 50

# All state-changing guild actions are POST-only so they are covered by CSRF
# protection. As GETs, a link or <img> on any website could make a logged-in
# user create, join, leave or delete a guild.

@guild_bp.route("/create-guild", methods=["POST"])
def create_guild():
    '''
    takes the name of the guild as input and creates a guild, making the user who created it the leader
    '''
    guild_name = request.form.get("guild_name")
    if current_user.get_guild():
        flash("Leave your current guild before creating a new one")
    elif guild_name and not guild_name.isspace() and not q.guild_exists(guild_name):
        q.create_guild(guild_name, current_user.id)
        q.join_guild(current_user.id, guild_name, "leader")
        q.delete_user_requests(current_user.id)
    else:
        flash("Try again with another name")

    return redirect(url_for("guild.guild"))

@guild_bp.route("/join-guild/<guild_name>", methods=["POST"])
def join_guild(guild_name):
    '''
    allows a user to send a request to join a guild
    '''
    if not current_user.get_guild() and q.guild_exists(guild_name) and not q.get_user_requests(current_user.id):
        q.request_guild(current_user.id, guild_name)
        flash(f"Request sent to {guild_name}")
        return redirect(url_for("guild.guild"))

    flash(f"Request to {guild_name} failed")
    return redirect(url_for("guild.guild"))

def _is_leader_of(guild_name):
    guild = q.get_guild(guild_name)
    return guild is not None and guild[1] == current_user.id

@guild_bp.route("/accept-request", methods=["POST"])
def accept_request():
    '''
    allows a leader to accept a user's request and makes the requesting user a member of the guild.

    previously any logged-in user could call this for any guild and any username, which let
    them force-add arbitrary users to arbitrary guilds. it now requires the caller to lead the
    guild, a pending request from that user, room in the guild, and the user not to be in a guild.
    '''
    username = request.form.get("username")
    guild_name = request.form.get("guild_name") or current_user.get_guild()

    if not _is_leader_of(guild_name) or not q.has_pending_request(username, guild_name):
        flash("You can't accept that request")
        return redirect(url_for("guild.guild"))

    guild = q.get_guild(guild_name)
    requester_guild = q.get_user_guild(username)
    if guild[3] >= MAX_GUILD_MEMBERS or (requester_guild and requester_guild[0]):
        q.reject_guild_request(username, guild_name)
        flash("That request can no longer be accepted")
        return redirect(url_for("guild.guild"))

    q.accept_guild_request(username, guild_name)

    q.join_guild(username, guild_name, "member")

    return redirect(url_for("guild.guild"))

@guild_bp.route("/reject-request", methods=["POST"])
def reject_request():
    '''
    allows a leader to reject a user's request to join
    '''
    username = request.form.get("username")
    guild_name = request.form.get("guild_name") or current_user.get_guild()

    if _is_leader_of(guild_name):
        q.reject_guild_request(username, guild_name)

    return redirect(url_for("guild.guild"))

@guild_bp.route("/delete-guild", methods=["POST"])
def delete_guild():
    '''
    allows the leader of a guild to delete it (previously any member could)
    '''
    if current_user.get_guild() and current_user.get_guild_role() == "leader" \
            and _is_leader_of(current_user.get_guild()):
        q.delete_guild(current_user)
    else:
        flash("Only the guild leader can delete the guild")

    return redirect(url_for("guild.guild"))

@guild_bp.route("/leave-guild", methods=["POST"])
def leave_guild():
    '''
    allows a member of a guild to leave it. leaders delete the guild instead, which is what
    the UI offers them; letting a leader leave would leave a guild nobody can manage.
    '''
    if not current_user.get_guild():
        flash("You're not in a guild")
    elif current_user.get_guild_role() == "leader":
        flash("Leaders can't leave their guild. Delete it instead")
    else:
        q.leave_guild(current_user)

    return redirect(url_for("guild.guild"))
