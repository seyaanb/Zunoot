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

    the balance check, deduction and purchase now happen in one transaction
    (queries.purchase_item). previously buying an item you already owned took the coins and
    then failed with a 500, and an unknown item_id was a 500.
    '''
    result = q.purchase_item(current_user.id, item_id)

    if result == "ok":
        flash("Purchase successful!", "success")
    elif result == "owned":
        flash("You already own this!", "error")
    elif result == "missing":
        flash("That item doesn't exist", "error")
    else:
        flash("Not enough coins!", "error")
    
    return redirect(url_for("shop.shop"))

@shop_bp.route("/equip/<int:item_id>", methods=["POST"])
def equip(item_id):
    '''
    allows a user to equip an avatar or app theme
    '''
    item_details = q.get_item_details(item_id)
    if item_details is None:
        flash("That item doesn't exist")
        return redirect(url_for("shop.shop"))
    item_type = item_details[2]
    item_name = item_details[1]

    purchased_items = q.get_purchased_items(item_type, current_user.id)
    if any(item[0] == item_id for item in purchased_items):
        if item_type == "avatar":
            q.equip_avatar(current_user.id, item_name)
        elif item_type == "theme":
            q.equip_theme(current_user.id, item_name)
        flash(f"{item_name.capitalize()} has been equipped")
    else:
        flash("You need to buy this first")
    return redirect(url_for("shop.shop", item_type=item_type))
