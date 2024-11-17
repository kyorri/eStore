from flask import Flask, render_template, redirect, url_for, request, flash, jsonify
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from flask_wtf.csrf import generate_csrf
import paypalrestsdk
import random

from models import OrderItem, db, User, Product, Cart, Order

paypalrestsdk.configure({
    "mode": "sandbox",
    "client_id": "",
    "client_secret": ""
})

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = "sqlite:///estore.db"

app.config['SECRET_KEY'] = ""
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

with app.app_context():
    db.create_all()

@app.route('/')
def home():
    products = Product.query.all()
    random_products = random.sample(products, min(len(products), 4)) if len(
        products) > 0 else []
    return render_template('index.html', products=random_products)

@app.route('/admin/products', methods=['GET', 'POST'])
@login_required
def manage_products():
    if current_user.role != 'admin':
        flash("You do not have permission to view this page.")
        return redirect(url_for('home'))

    if request.method == 'POST':
        name = request.form['name']
        description = request.form['description']
        price = round(float(request.form['price']), 2)
        stock = int(request.form['stock'])
        new_product = Product(
            name=name, description=description, price=price, stock=stock)

        try:
            db.session.add(new_product)
            db.session.commit()
            flash("Product added successfully!", "success")
        except Exception as e:
            flash(f"An error occurred: {str(e)}", "danger")
        return redirect(url_for('manage_products'))

    products = Product.query.all()
    return render_template('admin_products.html', products=products)


@app.route('/admin/product/edit/<int:id>', methods=['GET', 'POST'])
@login_required
def edit_product(id):
    if current_user.role != 'admin':
        flash("You do not have permission to view this page.")
        return redirect(url_for('home'))

    product = Product.query.get(id)
    if request.method == 'POST':
        # Update product details
        product.name = request.form['name']
        product.description = request.form['description']
        product.price = float(request.form['price'])
        product.stock = int(request.form['stock'])
        db.session.commit()
        flash("Product updated successfully!")
        return redirect(url_for('manage_products'))

    return render_template('edit_product.html', product=product)


@app.route('/admin/product/delete/<int:id>', methods=['POST'])
@login_required
def delete_product(id):
    if current_user.role != 'admin':
        flash("You do not have permission to view this page.")
        return redirect(url_for('home'))

    product = Product.query.get(id)
    db.session.delete(product)
    db.session.commit()
    flash("Product deleted successfully!")
    return redirect(url_for('manage_products'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        user = User.query.filter_by(username=username).first()

        if user and check_password_hash(user.password, password):
            login_user(user)
            flash("Login successful!")
            return redirect(url_for('home'))

        flash("Login failed. Check username and/or password.")

    return render_template('login.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('home'))


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        user = User.query.filter_by(username=username).first()
        if user:
            flash("Username already exists. Please choose another one.")
            return redirect(url_for('register'))

        hashed_password = generate_password_hash(password)

        user = User(username=username, password=hashed_password)

        db.session.add(user)
        db.session.commit()

        flash("Registration successful. Please log in.")
        return redirect(url_for('login'))

    return render_template('register.html')


@app.route('/add_to_cart/<int:product_id>', methods=['POST'])
@login_required
def add_to_cart(product_id):
    product = Product.query.get_or_404(product_id)

    if product.stock <= 0:
        flash(f"{product.name} is out of stock!")
        return redirect(url_for('home'))

    quantity = int(request.form['quantity'])

    if quantity > product.stock:
        flash(f"Sorry, only {product.stock} items are in stock for {
              product.name}.")
        return redirect(url_for('home'))

    existing_cart_item = Cart.query.filter_by(
        user_id=current_user.id, product_id=product.id).first()

    if existing_cart_item:
        if existing_cart_item.quantity + quantity <= product.stock:
            existing_cart_item.quantity += quantity
            db.session.commit()
            flash(f"Added {quantity} more of {product.name} to your cart!")
        else:
            flash(f"Not enough stock for {product.name}.")
    else:
        new_cart_item = Cart(user_id=current_user.id,
                             product_id=product.id, quantity=quantity)
        db.session.add(new_cart_item)
        db.session.commit()
        flash(f"Added {quantity} of {product.name} to your cart!")

    return redirect(url_for('shop'))


@app.route('/remove_from_cart/<int:cart_id>', methods=['POST'])
@login_required
def remove_from_cart(cart_id):
    cart_item = Cart.query.get_or_404(cart_id)

    if cart_item.user_id == current_user.id:
        db.session.delete(cart_item)
        db.session.commit()
        flash("Item removed from cart!")
    else:
        flash("You cannot remove this item from the cart.")

    return redirect(url_for('view_cart'))


@app.route('/update_cart/<int:cart_id>', methods=['POST'])
@login_required
def update_cart(cart_id):
    cart_item = Cart.query.get_or_404(cart_id)

    if cart_item.user_id != current_user.id:
        return jsonify({"error": "You cannot update this item in the cart."}), 400

    new_quantity = int(request.form['quantity'])

    if new_quantity > cart_item.product.stock:
        return jsonify({"error": f"Not enough stock for {cart_item.product.name}. You can only buy {cart_item.product.stock} items."}), 400

    cart_item.quantity = new_quantity
    db.session.commit()

    item_total = round(cart_item.product.price *
                       cart_item.quantity, 2)
    total_price = round(sum(item.product.price * item.quantity for item in Cart.query.filter_by(
        user_id=current_user.id).all()), 2)

    return jsonify({
        "item_total": item_total,
        "total_price": total_price
    })


@app.route('/cart')
@login_required
def view_cart():
    cart_items = Cart.query.filter_by(user_id=current_user.id).all()

    total_price = round(
        sum(item.product.price * item.quantity for item in cart_items), 2)
    print(f"Total Cart Price: ${total_price}")

    csrf_token = generate_csrf()

    cart_count = sum(item.quantity for item in cart_items)

    return render_template(
        'cart.html',
        cart_items=cart_items,
        total_price=total_price,
        csrf_token=csrf_token,
        cart_count=cart_count
    )


@app.route('/shop')
def shop():
    products = Product.query.all()
    cart_count = 0
    if current_user.is_authenticated:
        cart_count = sum(item.quantity for item in Cart.query.filter_by(
            user_id=current_user.id).all())

    return render_template('shop.html', products=products, cart_count=cart_count)


@app.route('/checkout', methods=['POST'])
@login_required
def checkout():
    cart_items = Cart.query.filter_by(user_id=current_user.id).all()
    total_price = sum(item.product.price *
                      item.quantity for item in cart_items)

    if total_price <= 0:
        flash("Your cart is empty or there's an issue with your cart.")
        return redirect(url_for('view_cart'))

    payment = paypalrestsdk.Payment({
        "intent": "sale",
        "payer": {
            "payment_method": "paypal"
        },
        "transactions": [{
            "amount": {
                "total": str(total_price),
                "currency": "USD"
            },
            "description": "eStore purchase"
        }],
        "redirect_urls": {
            "return_url": url_for('payment_success', _external=True),
            "cancel_url": url_for('payment_cancel', _external=True)
        }
    })

    if payment.create():
        for link in payment.links:
            if link.rel == "approval_url":
                return redirect(link.href)
    else:
        flash("Error creating PayPal payment.")
        return redirect(url_for('view_cart'))


@app.route('/payment_success', methods=['GET'])
@login_required
def payment_success():
    payment_id = request.args.get('paymentId')
    payer_id = request.args.get('PayerID')

    payment = paypalrestsdk.Payment.find(payment_id)
    if payment.execute({"payer_id": payer_id}):
        cart_items = Cart.query.filter_by(user_id=current_user.id).all()
        total_price = sum(item.product.price *
                          item.quantity for item in cart_items)

        order = Order(user_id=current_user.id, total_price=total_price)
        db.session.add(order)
        db.session.commit()

        for cart_item in cart_items:
            order_item = OrderItem(
                order_id=order.id,
                product_id=cart_item.product_id,
                quantity=cart_item.quantity,
                price=cart_item.product.price
            )
            db.session.add(order_item)

        db.session.commit()

        Cart.query.filter_by(user_id=current_user.id).delete()
        db.session.commit()

        flash("Payment successful! Your order has been placed.")
        return redirect(url_for('home'))

    else:
        flash("Payment execution failed.")
        return redirect(url_for('view_cart'))


@app.route('/payment_cancel', methods=['GET'])
@login_required
def payment_cancel():
    flash("Payment was canceled. You can try again later.")
    return redirect(url_for('view_cart'))


if __name__ == '__main__':
    app.run(debug=True)
