from flask import render_template, redirect, url_for, flash, request, current_app
from flask_login import login_user, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
import backend.queries as q
import backend.user as u
import re

from . import auth_bp

def get_user(username):
    '''
    helper function which returns the User object given the user's unique username
    '''
    user = q.get_user(username)
    if user:
        return u.User(*user)
    return None

@auth_bp.before_app_request
def require_login():
    '''
    ensures that users cannot access most endpoints without being logged in
    '''
    exempt_endpoints = ["auth.index", "auth.login", "auth.register", "home"]
    if request.endpoint in exempt_endpoints or request.endpoint == "static":
        return

    if not current_user.is_authenticated:
        return redirect(url_for("auth.login"))
    
@auth_bp.route('/')
def index():
    '''
    if the user is logged in, they are taken to their library.
    if not, they are taken to a landing page, where they have a choice of logging in or registering
    '''
    if current_user.is_authenticated:
        return redirect(url_for("library.library"))
    return render_template("landing.html")
    

@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    '''
    user enters a unique username, a first name, last name, a valid email address and a password more than 6 characters long
    their account is created
    they are redirected to the login page
    '''
    if request.method == "POST":
        try:
            username = request.form.get("username")

            if q.check_user_exists(username):
                flash("Someone already has this username... please log in or choose another one")
                return redirect(url_for("auth.login"))
                
            first_name = request.form.get("first-name")
            last_name = request.form.get("last-name")
            email = request.form.get("email")

            for x in [username, first_name, last_name, email]:
                if not x or x.isspace():
                    flash("Invalid input. Try again")
                    return redirect(url_for("auth.register"))

            pattern = r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$"
            if not re.match(pattern, email):
                flash("Invalid email address")
                return redirect(url_for("auth.register"))

            password = request.form.get("password")
            if len(password) <= 6:
                flash("Choose a password longer than 6 characters")
                return redirect(url_for("auth.register"))
                
            password_hash = generate_password_hash(password)

            q.insert_new_user(username, first_name, last_name, password_hash, email)
            flash("Success! You can now log in")

            return redirect(url_for("auth.login"))
        except Exception:
            current_app.logger.exception("Registration failed")
            flash("Whoops, something didn't work. Please try again")
            return redirect(url_for("auth.register"))

    return render_template("register.html")

@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    '''
    user enters a username and password. 
    if this combination matches any in the database, the user is authorised to access the app and is taken to their library
    if not, they are brought back to the same page to try again
    '''
    if request.method == "POST":
        try:
            username = request.form.get("username")
            password = request.form.get("password")

            user = get_user(username)

            if user and check_password_hash(user.get_password_hash(), password):
                login_user(user)
                flash("You're logged in!")
                return redirect(url_for("library.library"))
                
            flash("Wrong username/password. Please try again")
            return redirect(url_for("auth.login"))

        except Exception:
            current_app.logger.exception("Login failed")
            flash("Whoops, something didn't work. Please try again")
            return redirect(url_for("auth.login"))

    return render_template("login.html")

@auth_bp.route("/logout")
def logout():
    '''
    user is logged out of their account and taken back to the landing page
    '''
    try:
        logout_user()
    except:
        flash("Whoops, something went wrong. Please try again")
    else:
        flash("You're logged out")

    return redirect(url_for("auth.index"))

@auth_bp.route("/delete-account")
def delete_account():
    '''
    deletes a user's account and any linked database items, such as subjects or purchases
    '''

    username = current_user.id
    q.delete_user(username)

    return redirect(url_for("home"))

