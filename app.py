from datetime import datetime
import io
import os
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib import colors
from io import BytesIO
from flask import Flask, render_template, request, redirect, session, jsonify, send_file
import psycopg2
from psycopg2.extras import RealDictCursor
import sqlite3
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = "your_secret_key_here"
app.jinja_env.filters['ord'] = ord

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
    cursor.execute("SELECT name, category_name, price FROM items ORDER BY category_name ASC, name ASC")
    items = cursor.fetchall()
    
    cursor.execute("SELECT name, logo FROM categories")
    categories = cursor.fetchall()
    conn.close()

    return render_template(
        "index.html", 
        username=session["username"], 
        role=session["role"], 
        items=items,
        categories=categories
    )


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
    new_price_lbp = request.form.get("new_price_lbp")

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        if new_price and new_price.strip() != "":
            cursor.execute(
                "UPDATE items SET price = %s WHERE name = %s",
                (float(new_price), item_name)
            )
        elif new_price_lbp and new_price_lbp.strip() != "":
            converted_price = round(float(new_price_lbp) / 90000.0, 4)
            cursor.execute(
                "UPDATE items SET price = %s WHERE name = %s",
                    (converted_price, item_name)
            )
    except ValueError:
        pass

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
            raw_lbp = float(price_lbp_str)
            price = round(raw_lbp / 90000.0, 4)
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
        RETURNING sale_id, sale_datetime
    """,
        (cashier, total),
    )
    
    sale_row = cursor.fetchone()
    sale_id = sale_row["sale_id"] if sale_row else None
    sale_datetime = str(sale_row["sale_datetime"]) if sale_row else datetime.now().strftime("%Y-%m-%d %H:%M:%S")

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

    return jsonify({
        "message": "Checkout successful!",
        "sale_id": sale_id,
        "sale_datetime": sale_datetime,
        "cashier": cashier,
        "cart": cart,
        "total": total
    })


@app.route("/daily_report")
def daily_report():
    if "role" not in session or session["role"] != "admin":
        return redirect("/login")

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT si.sale_id, si.sale_item_id, si.item_name, si.quantity, si.line_total, s.sale_datetime, s.cashier_name
        FROM sale_items si
        JOIN sales s ON si.sale_id = s.sale_id
        WHERE DATE(s.sale_datetime) = CURRENT_DATE
        AND si.sale_item_id NOT IN (
            SELECT sale_item_id FROM void_items WHERE sale_item_id IS NOT NULL
        )
    """)
    report_items = cursor.fetchall()
    
    grand_total = sum(float(item["line_total"]) for item in report_items) if report_items else 0.0

    cursor.execute("""
        SELECT 
            COALESCE(i.category_name, 'Uncategorized') as category_name,
            COALESCE(c.is_church_report, TRUE) as is_church_report,
            si.item_name, 
            SUM(si.line_total) as total_sales, 
            SUM(si.quantity) as total_qty
        FROM sale_items si
        JOIN sales s ON si.sale_id = s.sale_id
        LEFT JOIN items i ON si.item_name = i.name
        LEFT JOIN categories c ON i.category_name = c.name
        WHERE DATE(s.sale_datetime) = CURRENT_DATE
        AND si.sale_item_id NOT IN (
            SELECT sale_item_id FROM void_items WHERE sale_item_id IS NOT NULL
        )
        GROUP BY COALESCE(i.category_name, 'Uncategorized'), COALESCE(c.is_church_report, TRUE), si.item_name
    """)
    aggregated_items = cursor.fetchall()

    item_summary_by_category = {}
    church_total = 0.0
    kbar_total = 0.0

    for item in aggregated_items:
        category = item["category_name"]
        if category not in item_summary_by_category:
            item_summary_by_category[category] = []
        item_summary_by_category[category].append(item)

        if item["is_church_report"]:
            church_total += float(item["total_sales"])
        else:
            kbar_total += float(item["total_sales"])

    cashier_summary_dict = {}
    total_cashier_qty = 0
    for item in report_items:
        cashier = item["cashier_name"]
        if cashier not in cashier_summary_dict:
            cashier_summary_dict[cashier] = {"qty": 0, "sales": 0.0}
        cashier_summary_dict[cashier]["qty"] += int(item["quantity"])
        cashier_summary_dict[cashier]["sales"] += float(item["line_total"])
        total_cashier_qty += int(item["quantity"])

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
        church_total=church_total,
        kbar_total=kbar_total,
        cashier_summary=cashier_summary,
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

    search_query = request.args.get("search", "").strip()
    selected_category = request.args.get("category", "").strip()

    cursor.execute("SELECT name FROM categories ORDER BY name ASC")
    categories = cursor.fetchall()

    query = """
        SELECT si.sale_item_id, s.sale_id, s.cashier_name, si.item_name, si.quantity, si.line_total, s.sale_datetime, i.category_name
        FROM sale_items si
        JOIN sales s ON si.sale_id = s.sale_id
        LEFT JOIN items i ON si.item_name = i.name
        WHERE si.sale_item_id NOT IN (
            SELECT sale_item_id FROM void_items WHERE sale_item_id IS NOT NULL
        )
    """
    params = []

    if search_query:
        query += """ AND (
            CAST(s.sale_id AS TEXT) ILIKE %s
        )"""
        params.append(f"%{search_query}%")
    if selected_category:
        query += " AND i.category_name = %s"
        params.append(selected_category)

    query += " ORDER BY s.sale_datetime DESC LIMIT 100"

    cursor.execute(query, params)
    sale_items = cursor.fetchall()
    conn.close()

    return render_template(
        "void_page.html",
        sale_items=sale_items,
        categories=categories,
        search_query=search_query,
        selected_category=selected_category,
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

    is_church_report = True if request.form.get("is_church_report") == "true" else False

    logo_filename = None
    file = request.files.get("logo")

    if file and file.filename != "":
        logo_filename = secure_filename(file.filename)
        upload_folder = app.config["UPLOAD_FOLDER"]
        os.makedirs(upload_folder, exist_ok=True)
        file.save(os.path.join(upload_folder, logo_filename))

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO categories (name, logo, is_church_report) VALUES (%s, %s, %s)
            ON CONFLICT (name) DO UPDATE 
            SET logo = COALESCE(EXCLUDED.logo, categories.logo), 
                is_church_report = EXCLUDED.is_church_report
            """,
            (category_name, logo_filename, is_church_report)
        )
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"CRITICAL ERROR adding category: {e}")
        raise e

    return redirect("/admin")


@app.route("/download_report")
def download_report():
    if "role" not in session or session["role"] != "admin":
        return redirect("/login")

    conn = get_db_connection()
    cursor = conn.cursor()


    cursor.execute("""
        SELECT 
            COALESCE(i.category_name, 'Uncategorized') as category_name,
            COALESCE(c.is_church_report, TRUE) as is_church_report,
            si.item_name, 
            SUM(si.line_total) as total_sales, 
            SUM(si.quantity) as total_qty
        FROM sale_items si
        JOIN sales s ON si.sale_id = s.sale_id
        LEFT JOIN items i ON si.item_name = i.name
        LEFT JOIN categories c ON i.category_name = c.name
        WHERE DATE(s.sale_datetime) = CURRENT_DATE
        AND si.sale_item_id NOT IN (
            SELECT sale_item_id FROM void_items WHERE sale_item_id IS NOT NULL
        )
        GROUP BY COALESCE(i.category_name, 'Uncategorized'), COALESCE(c.is_church_report, TRUE), si.item_name
    """)
    aggregated_items = cursor.fetchall()
    cursor.execute("""
        SELECT si.sale_id, si.sale_item_id, si.item_name, si.quantity, si.line_total, s.sale_datetime, s.cashier_name
        FROM sale_items si
        JOIN sales s ON si.sale_id = s.sale_id
        WHERE DATE(s.sale_datetime) = CURRENT_DATE
        AND si.sale_item_id NOT IN (
            SELECT sale_item_id FROM void_items WHERE sale_item_id IS NOT NULL
        )
    """)
    report_items = cursor.fetchall()
    
    cursor.close()
    conn.close()

    church_items = []
    kbar_items = []
    church_total = 0.0
    kbar_total = 0.0

    for item in aggregated_items:
        sale_val = float(item["total_sales"])
        if item["is_church_report"]:
            church_items.append(item)
            church_total += sale_val
        else:
            kbar_items.append(item)
            kbar_total += sale_val

    grand_total = church_total + kbar_total

    cashier_summary_dict = {}
    total_cashier_qty = 0
    for item in report_items:
        cashier = item["cashier_name"]
        if cashier not in cashier_summary_dict:
            cashier_summary_dict[cashier] = {"qty": 0, "sales": 0.0}
        cashier_summary_dict[cashier]["qty"] += int(item["quantity"])
        cashier_summary_dict[cashier]["sales"] += float(item["line_total"])
        total_cashier_qty += int(item["quantity"])


    # Generate PDF using ReportLab
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=36, leftMargin=36, topMargin=36, bottomMargin=36)
    elements = []
    styles = getSampleStyleSheet()

    primary_color = colors.HexColor('#1f6feb')
    dark_neutral = colors.HexColor('#111827')
    light_bg = colors.HexColor('#f3f4f6')
    border_color = colors.HexColor('#dcdcdc')

    title_style = ParagraphStyle(
        'ReportTitle',
        parent=styles['Title'],
        textColor=dark_neutral,
        fontSize=24,
        alignment=0,
        spaceAfter=4
    )   
    
    elements.append(Paragraph("Daily Sales Report", styles['Title']))
    elements.append(Paragraph(f"Report Date: {datetime.now().strftime('%d-%m-%Y')}", styles['Normal']))
    elements.append(Spacer(1, 15))
    
    grand_lbp = grand_total * 90000
    elements.append(Paragraph(f"<b>Grand Total: ${grand_total:.2f} ({grand_lbp:,.0f} LBP)</b>", styles['Heading2']))
    elements.append(Spacer(1, 15))

    # --- Per-Cashier Summary Section ---
    elements.append(Paragraph("<b>Per-Cashier Summary</b>", styles['Heading3']))
    cashier_table_data = [["Cashier Name", "Total Items Sold", "Total Sales"]]
    if cashier_summary_dict:
        for cashier, data in cashier_summary_dict.items():
            c_lbp = data['sales'] * 90000
            cashier_table_data.append([
                cashier,
                str(data['qty']),
                f"${data['sales']:.2f} ({c_lbp:,.0f} LBP)"
            ])
        cashier_table_data.append([
            "Total",
            str(total_cashier_qty),
            f"${grand_total:.2f} ({grand_lbp:,.0f} LBP)"
        ])
    else:
        cashier_table_data.append(["No sales recorded today.", "", ""])

    t_cashier = Table(cashier_table_data, colWidths=[200, 100, 240])
    t_cashier.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), primary_color),
        ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),
        ('ALIGN', (0,0), (-1,-1), 'LEFT'),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,0), 10),
        ('BOTTOMPADDING', (0,0), (-1,0), 8),
        ('TOPPADDING', (0,0), (-1,0), 8),
        ('ROWBACKGROUNDS', (0,1), (-1,-2 if len(cashier_summary_dict) > 0 else -1), [colors.white, light_bg]),
        ('BACKGROUND', (0,-1), (-1,-1), colors.HexColor('#e5e7eb')),
        ('FONTNAME', (0,-1), (-1,-1), 'Helvetica-Bold'),
        ('GRID', (0,0), (-1,-1), 0.5, border_color),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
    ]))
    elements.append(t_cashier)
    elements.append(Spacer(1, 20))

    # --- Church Sales Section (Combined without internal categories) ---
    church_lbp = church_total * 90000
    elements.append(Paragraph(f"<b>Church Sales — Subtotal: ${church_total:.2f} ({church_lbp:,.0f} LBP)</b>", styles['Heading3']))
    
    church_table_data = [["Item Name", "Qty", "Sales Total"]]
    if church_items:
        for ci in church_items:
            ci_lbp = float(ci['total_sales']) * 90000
            church_table_data.append([
                ci['item_name'], 
                str(ci['total_qty']), 
                f"${float(ci['total_sales']):.2f} ({ci_lbp:,.0f} LBP)"
            ])
    else:
        church_table_data.append(["No church sales today.", "", ""])

    t_church = Table(church_table_data, colWidths=[250, 80, 210])
    t_church.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.lightgrey),
        ('TEXTCOLOR', (0,0), (-1,0), colors.black),
        ('ALIGN', (0,0), (-1,-1), 'LEFT'),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,0), 10),
        ('BOTTOMPADDING', (0,0), (-1,0), 8),
        ('TOPPADDING', (0,0), (-1,0), 8),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, light_bg]),
        ('GRID', (0,0), (-1,-1), 0.5, border_color),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
    ]))
    elements.append(t_church)
    elements.append(Spacer(1, 15))

    # --- Kbar Sales Section ---
    kbar_lbp = kbar_total * 90000
    elements.append(Paragraph(f"<b>Kbar Sales — Subtotal: ${kbar_total:.2f} ({kbar_lbp:,.0f} LBP)</b>", styles['Heading3']))
    
    kbar_table_data = [["Item Name", "Qty", "Sales Total"]]
    if kbar_items:
        for ki in kbar_items:
            ki_lbp = float(ki['total_sales']) * 90000
            kbar_table_data.append([
                ki['item_name'], 
                str(ki['total_qty']), 
                f"${float(ki['total_sales']):.2f} ({ki_lbp:,.0f} LBP)"
            ])
    else:
        kbar_table_data.append(["No Kbar sales today.", "", ""])

    t_kbar = Table(kbar_table_data, colWidths=[250, 80, 210])
    t_kbar.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.lightgrey),
        ('TEXTCOLOR', (0,0), (-1,0), colors.black),
        ('ALIGN', (0,0), (-1,-1), 'LEFT'),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,0), 10),
        ('BOTTOMPADDING', (0,0), (-1,0), 8),
        ('TOPPADDING', (0,0), (-1,0), 8),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, light_bg]),
        ('GRID', (0,0), (-1,-1), 0.5, border_color),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
    ]))
    elements.append(t_kbar)

    
    sig_style = ParagraphStyle(
        'DeveloperSignature',
        parent=styles['Normal'],
        textColor=colors.HexColor('#6c757d'),
        fontSize=9,
        alignment=2  # Right-aligned
    )

    elements.append(Spacer(1, 20))
    elements.append(Paragraph("Developed by Alain Koukou", sig_style))
    
    doc.build(elements)
    buffer.seek(0)
    return send_file(buffer, as_attachment=True, download_name=f"daily_report_{datetime.now().strftime('%Y-%m-%d')}.pdf", mimetype='application/pdf')

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)