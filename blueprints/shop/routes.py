from flask import render_template, request, redirect, url_for, flash
from flask_login import current_user
import backend.queries as q
from . import shop_bp



@shop_bp.route("/shop")
def shop():
    '''
    displays avatars and app themes which can be purchased for a varying number of coins
    '''
    item_type = request.args.get("item_type", "avatar")
    purchased_items = q.get_purchased_items(item_type, current_user.id)
    shop_items = q.get_shop_items(item_type, current_user.id)

    return render_template("shop.html",
                           item_type=item_type,
                           purchased_items=purchased_items,
                           shop_items=shop_items,
                           coins=current_user.get_coins(),
                           avatar=current_user.get_avatar(),
                           theme=current_user.get_theme())

@shop_bp.route("/purchase/<int:item_id>", methods=["POST"])
def purchase(item_id):
    '''
    allows a user to trade coins they have for an avatar or app theme
    '''
    username = current_user.id 

    item_price = q.get_item_price(item_id)[0]

    if item_price <= current_user.get_coins():
        current_user.deduct_coins(item_price)
        q.add_purchase(item_id, username)
        flash("Purchase successful!", "success")
    else:
        flash("Not enough coins!", "error")
    
    return redirect(url_for("shop.shop"))

@shop_bp.route("/equip/<int:item_id>", methods=["POST"])
def equip(item_id):
    '''
    allows a user to equip an avatar or app theme
    '''
    item_details = q.get_item_details(item_id)
    item_type = item_details[2]
    item_name = item_details[1]

    purchased_items = q.get_purchased_items(item_type, current_user.id)
    if any(item[0] == item_id for item in purchased_items):
        if item_type == "avatar":
            q.equip_avatar(current_user.id, item_name)
        elif item_type == "theme":
            q.equip_theme(current_user.id, item_name)
    
    flash(f"{item_name.capitalize()} has been equipped")    
    return redirect(url_for("shop.shop", item_type=item_type))