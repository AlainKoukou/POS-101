from datetime import datetime
import io
import os
from flask import Flask, render_template, request, redirect, session, jsonify, send_file
import psycopg2
from psycopg2.extras import RealDictCursor
import sqlite3
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = "your_secret_key_here"

UPLOAD_FOLDER = "static/uploads"
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER


def get_db_connection():
    database_url = os.environ.get("DATABASE_URL")
    if database_url:
        # Connect to Supabase PostgreSQL in production
        conn = psycopg2.connect(database_url, cursor_factory=RealDictCursor)
        return conn
    else:
        # Fallback to local SQLite for local testing
        conn = sqlite3.connect("pos.db")
        conn.row_factory = sqlite3.Row
        return conn


@app.route("/")
def index():
    if "username" not in session:
        return redirect("/login")

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT name, price FROM items ORDER BY name ASC")
    items = cursor.fetchall()
    conn.close()

    return render_template("index.html", username=session["username"], role=session["role"], items=items)


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM users WHERE username = %s AND password = %s",
            (username, password),
        )
        user = cursor.fetchone()
        conn.close()

        if user:
            session["username"] = user["username"]
            session["role"] = user["role"]
            return redirect("/")
        else:
            return render_template("login.html", error="Invalid credentials")
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT username FROM users ORDER BY username")
    usernames = cursor.fetchall()
    conn.close()
    return render_template("login.html", usernames=usernames)


@app.route("/admin")
def admin():
    if "role" not in session or session["role"] != "admin":
        return redirect("/login")

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM categories")
    categories = cursor.fetchall()

    cursor.execute(
        "SELECT name, category_name, price FROM items"
    )
    items = cursor.fetchall()

    cursor.execute("SELECT username, role FROM users")
    users = cursor.fetchall()

    conn.close()
    
    return render_template(
        "admin.html", 
        categories=categories, 
        items=items, 
        users=users, 
        username=session.get("username"), 
        role=session.get("role")
    )


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")


@app.route("/update_price", methods=["POST"])
def update_price():
    if "role" not in session or session["role"] != "admin":
        return redirect("/login")

    item_name = request.form.get("name")
    new_price = request.form.get("new_price")

    conn = get_db_connection()
    cursor = conn.cursor()

    if new_price and new_price.strip() != "":
        cursor.execute(
            "UPDATE items SET price = %s WHERE name = %s",
            (float(new_price), item_name)
        )

    conn.commit()
    conn.close()
    return redirect("/admin")


@app.route("/add_user", methods=["POST"])
def add_user():
    if "role" not in session or session["role"] != "admin":
        return redirect("/login")

    username = request.form.get("username")
    password = request.form.get("password")
    role = request.form.get("role", "cashier")

    if not username or not password:
        return redirect("/admin")

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO users (username, password, role) VALUES (%s, %s, %s)",
            (username, password, role)
        )
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"Error adding user: {e}")

    return redirect("/admin")


@app.route("/add_item", methods=["POST"])
def add_item():
    if "role" not in session or session["role"] != "admin":
        return redirect("/login")

    name = request.form["name"]
    category_name = request.form["category_name"]

    price_usd_str = request.form.get("price", "")
    price_lbp_str = request.form.get("price_lbp", "")

    try:
        if price_usd_str and float(price_usd_str) > 0:
            price = float(price_usd_str)
        elif price_lbp_str and float(price_lbp_str) > 0:
            price = float(price_lbp_str) / 90000.0
        else:
            return "Error: A valid price in USD or LBP must be provided."
    except ValueError:
        return "Error: Invalid price format."

    if price < 0:
        return "Error: Price cannot be negative."

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute(
            """
            INSERT INTO items (name, category_name, price)
            VALUES (%s, %s, %s)
            ON CONFLICT (name) DO UPDATE 
            SET category_name = EXCLUDED.category_name, 
                price = EXCLUDED.price
            """,
            (name, category_name, price),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error adding/updating item: {e}")
        return f"Error: Could not save item. {e}"

    return redirect("/admin")


@app.route("/delete_item", methods=["POST"])
def delete_item():
    if "role" not in session or session["role"] != "admin":
        return redirect("/login")

    item_name = request.form.get("name")

    if not item_name:
        return redirect("/admin")

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM items WHERE name = %s",
            (item_name,)
        )
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"Error deleting item: {e}")

    return redirect("/admin")


@app.route("/delete_category", methods=["POST"])
def delete_category():
    if "role" not in session or session["role"] != "admin":
        return redirect("/login")

    category_name = request.form.get("name")

    if not category_name:
        return redirect("/admin")

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM categories WHERE name = %s",
            (category_name,)
        )
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"Error deleting category: {e}")

    return redirect("/admin")


@app.route("/delete_user", methods=["POST"])
def delete_user():
    if "role" not in session or session["role"] != "admin":
        return redirect("/login")

    username = request.form.get("username")

    if not username:
        return redirect("/admin")

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM users WHERE username = %s",
            (username,)
        )
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"Error deleting user: {e}")

    return redirect("/admin")


@app.route("/update_user_password", methods=["POST"])
def update_user_password():
    if "role" not in session or session["role"] != "admin":
        return redirect("/login")

    username = request.form.get("username")
    new_password = request.form.get("new_password")

    if not username or not new_password:
        return redirect("/admin")

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE users SET password = %s WHERE username = %s",
            (new_password, username)
        )
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"Error updating password: {e}")

    return redirect("/admin")


@app.route("/checkout", methods=["POST"])
def checkout():
    if "username" not in session:
        return jsonify({"message": "Unauthorized"}), 401

    data = request.get_json()
    cart = data.get("cart", [])
    total = data.get("total", 0)
    cashier = session["username"]

    if not cart:
        return jsonify({"message": "Cart is empty"}), 400

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT INTO sales (cashier_name, total_amount, sale_datetime)
        VALUES (%s, %s, NOW())
        RETURNING sale_id
    """,
        (cashier, total),
    )
    
    sale_id_row = cursor.fetchone()
    sale_id = sale_id_row["sale_id"] if sale_id_row else None

    for item in cart:
        cursor.execute(
            """
            INSERT INTO sale_items (sale_id, item_name, quantity, line_total)
            VALUES (%s, %s, %s, %s)
        """,
            (sale_id, item["name"], item["quantity"], item["line_total"]),
        )

    conn.commit()
    conn.close()

    return jsonify({"message": "Checkout successful!"})


@app.route("/daily_report")
def daily_report():
    if "role" not in session or session["role"] != "admin":
        return redirect("/login")

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT si.sale_id, si.item_name, si.quantity, si.line_total, s.sale_datetime, s.cashier_name
        FROM sale_items si
        JOIN sales s ON si.sale_id = s.sale_id
        WHERE DATE(s.sale_datetime) = CURRENT_DATE
    """)
    report_items = cursor.fetchall()
    
    grand_total = sum(float(item["line_total"]) for item in report_items) if report_items else 0.0

    cursor.execute("""
        SELECT 
            COALESCE(i.category_name, 'Uncategorized') as category_name,
            si.item_name, 
            SUM(si.line_total) as total_sales, 
            SUM(si.quantity) as total_qty
        FROM sale_items si
        JOIN sales s ON si.sale_id = s.sale_id
        LEFT JOIN items i ON si.item_name = i.name
        WHERE DATE(s.sale_datetime) = CURRENT_DATE
        GROUP BY COALESCE(i.category_name, 'Uncategorized'), si.item_name
    """)
    aggregated_items = cursor.fetchall()

    item_summary_by_category = {}
    for item in aggregated_items:
        category = item["category_name"]
        if category not in item_summary_by_category:
            item_summary_by_category[category] = []
        item_summary_by_category[category].append(item)

    cursor.execute("""
        SELECT si.item_name, si.line_total as price, v.void_datetime 
        FROM void_items v
        JOIN sale_items si ON v.sale_item_id = si.sale_item_id
        ORDER BY v.void_datetime DESC
    """)
    voided_items = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template(
        "daily_report.html", 
        report_items=report_items, 
        grand_total=grand_total, 
        item_summary_by_category=item_summary_by_category,
        voided_items=voided_items,
        username=session["username"], 
        role=session["role"]
    )


@app.route("/void_page", methods=["GET", "POST"])
def void_page():
    if "role" not in session or session["role"] != "admin":
        return redirect("/login")

    conn = get_db_connection()
    cursor = conn.cursor()

    if request.method == "POST":
        sale_item_id = request.form.get("sale_item_id")

        if sale_item_id:
            cursor.execute(
                """
                INSERT INTO void_items (sale_item_id, void_datetime)
                VALUES (%s, NOW())
            """,
                [sale_item_id]
            )
            conn.commit()

        conn.close()
        return redirect("/void_page")

    cursor.execute(
        """
        SELECT si.sale_item_id, s.sale_id, s.cashier_name, si.item_name, si.quantity, si.line_total, s.sale_datetime
        FROM sale_items si
        JOIN sales s ON si.sale_id = s.sale_id
        WHERE si.sale_item_id NOT IN (
            SELECT sale_item_id FROM void_items WHERE sale_item_id IS NOT NULL
        )
        ORDER BY s.sale_datetime DESC
        LIMIT 50
    """
    )
    sale_items = cursor.fetchall()
    conn.close()

    return render_template(
        "void_page.html",
        sale_items=sale_items,
        username=session["username"],
        role=session["role"],
    )


@app.route("/reset_today", methods=["POST"])
def reset_today():
    if "role" not in session or session["role"] != "admin":
        return redirect("/login")

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("DELETE FROM void_items")
        cursor.execute("DELETE FROM sale_items")
        cursor.execute("DELETE FROM sales")
        
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"Error resetting today's sales: {e}")

    return redirect("/daily_report")


@app.route("/add_category", methods=["POST"])
def add_category():
    if "role" not in session or session["role"] != "admin":
        return redirect("/login")

    category_name = request.form.get("name")

    if not category_name:
        return redirect("/admin")

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO categories (name) VALUES (%s)",
            (category_name,)
        )
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"Error adding category: {e}")

    return redirect("/admin")


@app.route("/download_report")
def download_report():
    if "role" not in session or session["role"] != "admin":
        return redirect("/login")

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT 
            COALESCE(i.category_name, 'Uncategorized') as cat_name,
            si.item_name, 
            SUM(si.quantity) as total_qty, 
            SUM(si.line_total) as total_line
        FROM sale_items si
        JOIN sales s ON si.sale_id = s.sale_id
        LEFT JOIN items i ON si.item_name = i.name
        WHERE DATE(s.sale_datetime) = CURRENT_DATE
        AND si.sale_item_id NOT IN (
            SELECT sale_item_id FROM void_items WHERE sale_item_id IS NOT NULL
        )
        GROUP BY cat_name, si.item_name
        ORDER BY cat_name
    """
    )
    raw_items = cursor.fetchall()

    pdf_categories = {}
    for row in raw_items:
        cat = row["cat_name"]
        if cat not in pdf_categories:
            pdf_categories[cat] = []
        pdf_categories[cat].append((row["item_name"], row["total_qty"], row["total_line"]))

    cursor.execute(
        """
        SELECT COALESCE(SUM(si.line_total),0) as total_sum
        FROM sale_items si
        JOIN sales s ON si.sale_id = s.sale_id
        WHERE DATE(s.sale_datetime) = CURRENT_DATE
        AND si.sale_item_id NOT IN (
            SELECT sale_item_id FROM void_items WHERE sale_item_id IS NOT NULL
        )
    """
    )
    total_row = cursor.fetchone()
    total = total_row["total_sum"] if total_row else 0
    conn.close()

    from reportlab.pdfgen import canvas

    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer)

    report_date = datetime.now().strftime("%Y-%m-%d")
    y = 800

    pdf.setFont("Helvetica-Bold", 18)
    pdf.drawString(200, y, "Daily Sales Report")

    y -= 30
    pdf.setFont("Helvetica", 12)
    pdf.drawString(50, y, f"Report Date: {report_date}")

    y -= 25
    pdf.setFont("Helvetica-Bold", 14)
    total_lbp = total * 90000
    pdf.drawString(50, y, f"Grand Total: ${total:.2f}  ({total_lbp:,.0f} LBP)")

    y -= 35

    for category_name, items in pdf_categories.items():
        if y < 120:
            pdf.showPage()
            y = 800

        cat_total = sum(item[2] for item in items)
        cat_total_lbp = cat_total * 90000

        pdf.setFont("Helvetica-Bold", 12)
        pdf.drawString(50, y, f"Category: {category_name}")

        pdf.setFont("Helvetica-Bold", 10)
        pdf.drawRightString(
            550, y, f"Subtotal: ${cat_total:.2f} ({cat_total_lbp:,.0f} LBP)"
        )

        y -= 20
        pdf.setFont("Helvetica-Bold", 10)
        pdf.drawString(60, y, "Item Name")
        pdf.drawString(240, y, "Qty")
        pdf.drawString(320, y, "Sales Total")
        y -= 15

        pdf.setFont("Helvetica", 10)
        for item in items:
            if y < 50:
                pdf.showPage()
                y = 800
            item_sales_lbp = item[2] * 90000
            pdf.drawString(60, y, str(item[0]))
            pdf.drawString(240, y, str(item[1]))
            pdf.drawString(320, y, f"${item[2]:.2f} ({item_sales_lbp:,.0f} LBP)")
            y -= 15
        y -= 15

    pdf.setFont("Helvetica-Oblique", 8)
    pdf.setFillColorRGB(0.4, 0.4, 0.4)
    pdf.drawCentredString(300, 30, "Developed by Alain Koukou")

    pdf.save()
    buffer.seek(0)

    return send_file(
        buffer,
        as_attachment=True,
        download_name="daily_report.pdf",
        mimetype="application/pdf",
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)