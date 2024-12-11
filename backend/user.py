from flask_login import UserMixin
from backend import queries as q

class User(UserMixin):

    def __init__(self, username, first_name, last_name, password, email, date_joined, guild_name, coins, avatar, theme, last_login, guild_role, points):
        self.id = username
        self.first_name = first_name
        self.last_name = last_name
        self.__password_hash = password
        self.email = email
        self.date_joined = date_joined
        self.__guild = guild_name
        self.__coins = coins
        self.__avatar = avatar
        self.__theme = theme
        self.last_login = last_login
        self.__guild_role = guild_role
        self.__points = points
    
    def get_password_hash(self):
        return self.__password_hash
    
    def get_coins(self):
        return self.__coins
    
    def add_coins(self, quantity):
        self.__coins += quantity
        q.add_coins_db(self.id, quantity)
    
    def deduct_coins(self, quantity):
        self.__coins -= quantity
        q.add_coins_db(self.id, quantity * -1)

    def add_points(self, quantity):
        self.__points += quantity
        q.add_points_db(self.id, quantity)

    def get_avatar(self):
        return self.__avatar
    
    def get_guild(self):
        return self.__guild
    
    def get_guild_role(self):
        return self.__guild_role
    
    def get_theme(self):
        return self.__theme

    
