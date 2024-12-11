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


@guild_bp.route("/create-guild")
def create_guild():
    '''
    takes the name of the guild as input and creates a guild, making the user who created it the leader
    '''
    guild_name = request.args.get("guild_name")
    if guild_name and not q.guild_exists(guild_name) and not guild_name.isspace():
        q.create_guild(guild_name, current_user.id)
        q.join_guild(current_user.id, guild_name, "leader")
        q.delete_user_requests(current_user.id)
    else:
        flash("Try again with another name")

    return redirect(url_for("guild.guild"))

@guild_bp.route("/join-guild/<guild_name>")
def join_guild(guild_name):
    '''
    allows a user to send a request to join a guild
    '''
    if not q.get_user_requests(current_user.id):
        q.request_guild(current_user.id, guild_name)
        flash(f"Request sent to {guild_name}")
        return redirect(url_for("guild.guild"))

    flash(f"Request to {guild_name} failed")
    return redirect(url_for("guild.guild"))

@guild_bp.route("/accept-request", methods=["POST"])
def accept_request():
    '''
    allows a leader to accept a user's request and makes the requesting user a member of the guild
    '''
    username = request.form.get("username")
    guild_name = request.form.get("guild_name")

    q.accept_guild_request(username, guild_name)

    q.join_guild(username, guild_name, "member")

    return redirect(url_for("guild.guild"))

@guild_bp.route("/reject-request", methods=["POST"])
def reject_request():
    '''
    allows a leader to reject a user's request to join
    '''
    username = request.form.get("username")
    guild_name = request.form.get("guild_name")

    q.reject_guild_request(username, guild_name)

    return redirect(url_for("guild.guild"))

@guild_bp.route("/delete-guild")
def delete_guild():
    '''
    allows the leader of a guild to delete it
    '''

    q.delete_guild(current_user)

    return redirect(url_for("guild.guild"))

@guild_bp.route("/leave-guild")
def leave_guild():
    '''
    allows a member of a guild to leave it
    '''
    q.leave_guild(current_user)

    return redirect(url_for("guild.guild"))