from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
import sqlite3
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta

# ================= APP CONFIG =================
app = Flask(__name__)
app.secret_key = "secret123"

# ================= DATABASE =================
def get_db():
    conn = sqlite3.connect("database.db")
    conn.row_factory = sqlite3.Row
    return conn

# สำหรับ delete transaction
def get_db_connection():
    return get_db()

# ================= INIT DB =================
def init_db():
    db = get_db()
    # สร้างตาราง
    db.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT,
            email TEXT UNIQUE,
            password TEXT,
            security_question TEXT,
            security_answer TEXT
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            name TEXT,
            type TEXT CHECK(type IN ('รายรับ','รายจ่าย')),
            UNIQUE(user_id,name)
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            category_id INTEGER,
            amount REAL,
            note TEXT,
            date TIMESTAMP
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS user_settings (
            user_id INTEGER PRIMARY KEY,
            default_saving REAL DEFAULT 0,
            saving_percent REAL DEFAULT 0,
            income_min_alert REAL DEFAULT 0,
            income_max_alert REAL DEFAULT 0
        )
    """)
    db.commit()

    # migration columns
    cur = db.cursor()
    cur.execute("PRAGMA table_info(user_settings)")
    cols = [c[1] for c in cur.fetchall()]
    if "income_min_alert" not in cols:
        cur.execute("ALTER TABLE user_settings ADD COLUMN income_min_alert REAL DEFAULT 0")
    if "income_max_alert" not in cols:
        cur.execute("ALTER TABLE user_settings ADD COLUMN income_max_alert REAL DEFAULT 0")
    db.commit()
    db.close()

init_db()

# ================= USER SETTINGS =================
def get_user_settings(user_id):
    db = get_db()
    s = db.execute("SELECT * FROM user_settings WHERE user_id=?", (user_id,)).fetchone()
    if not s:
        db.execute("INSERT INTO user_settings VALUES (?,?,?,?,?)", (user_id, 0, 0, 0, 0))
        db.commit()
        s = db.execute("SELECT * FROM user_settings WHERE user_id=?", (user_id,)).fetchone()
    db.close()
    return s

# ================= AUTH =================
@app.route("/")
def index():
    return redirect(url_for("login"))

@app.route("/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]
        db = get_db()
        user = db.execute("SELECT * FROM users WHERE email=? OR username=?", (email,email)).fetchone()
        db.close()
        if not user or not check_password_hash(user["password"], password):
            flash("❌ เข้าสู่ระบบไม่สำเร็จ","error")
            return redirect(url_for("login"))
        session["user_id"] = user["id"]
        session["username"] = user["username"]
        return redirect(url_for("dashboard"))
    return render_template("login.html")

@app.route("/register", methods=["GET","POST"])
def register():
    if request.method == "POST":
        username = request.form["username"]
        email = request.form["email"]
        password = request.form["password"]
        security_question = request.form.get("security_question","")
        security_answer = request.form["security_answer"]

        db = get_db()
        if db.execute("SELECT id FROM users WHERE email=?",(email,)).fetchone():
            flash("❌ อีเมลนี้ถูกใช้แล้ว","error")
            db.close()
            return redirect(url_for("register"))

        db.execute("""INSERT INTO users (username,email,password,security_question,security_answer)
                      VALUES (?,?,?,?,?)""",
                   (username, email, generate_password_hash(password), security_question, security_answer))
        db.commit()
        db.close()
        flash("✅ สมัครสมาชิกสำเร็จ","success")
        return redirect(url_for("login"))
    return render_template("register.html")

@app.route("/forgot_password", methods=["GET","POST"])
def forgot_password():
    if request.method == "POST":
        email = request.form["email"]
        answer = request.form["answer"]
        new_password = request.form["new_password"]

        db = get_db()
        user = db.execute("SELECT * FROM users WHERE email=?",(email,)).fetchone()
        if not user or user["security_answer"] != answer:
            flash("❌ ข้อมูลไม่ถูกต้อง","error")
            db.close()
            return redirect(url_for("forgot_password"))

        db.execute("UPDATE users SET password=? WHERE id=?",
                   (generate_password_hash(new_password), user["id"]))
        db.commit()
        db.close()
        flash("✅ เปลี่ยนรหัสผ่านเรียบร้อย","success")
        return redirect(url_for("login"))
    return render_template("forgot_password.html")

@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("login"))

# ================= DASHBOARD =================
@app.route("/dashboard")
def dashboard():
    if "user_id" not in session:
        return redirect(url_for("login"))
    uid = session["user_id"]
    db = get_db()

    income = db.execute("""
        SELECT SUM(t.amount) FROM transactions t
        JOIN categories c ON t.category_id = c.id
        WHERE t.user_id = ? AND c.type = 'รายรับ'
    """, (uid,)).fetchone()[0] or 0

    expense = db.execute("""
        SELECT SUM(t.amount) FROM transactions t
        JOIN categories c ON t.category_id = c.id
        WHERE t.user_id = ? AND c.type = 'รายจ่าย'
    """, (uid,)).fetchone()[0] or 0

    salary = db.execute("""
        SELECT SUM(t.amount) FROM transactions t
        JOIN categories c ON t.category_id = c.id
        WHERE t.user_id = ? AND c.name = 'เงินเดือน'
    """, (uid,)).fetchone()[0] or 0

    settings = get_user_settings(uid)
    default_saving = settings["default_saving"]
    saving_percent = settings["saving_percent"]
    alert_limit = settings["income_min_alert"]

    saving = default_saving + (salary * saving_percent / 100)
    balance = income - expense - saving
    low_balance_warning = balance < alert_limit

    db.close()
    return render_template("dashboard.html",
                           income=income,
                           expense=expense,
                           saving=saving,
                           balance=balance,
                           low_balance_warning=low_balance_warning,
                           alert_limit=alert_limit)

# ================= ADD TRANSACTION =================
@app.route("/add", methods=["GET","POST"])
def add_transaction():
    if "user_id" not in session:
        return redirect(url_for("login"))
    uid = session["user_id"]
    db = get_db()
    categories = db.execute("SELECT * FROM categories WHERE user_id=?",(uid,)).fetchall()

    if request.method == "POST":
        date = datetime.utcnow() + timedelta(hours=7)
        db.execute("""
            INSERT INTO transactions (user_id,category_id,amount,note,date)
            VALUES (?,?,?,?,?)
        """, (uid, request.form["category_id"], float(request.form["amount"]), request.form["note"], date))
        db.commit()
        db.close()
        flash("✅ เพิ่มรายการสำเร็จ","success")
        return redirect(url_for("dashboard"))

    db.close()
    return render_template("add_transaction.html", categories=categories)

# ================= HISTORY =================
@app.route("/history")
def history():
    if "user_id" not in session:
        return redirect(url_for("login"))
    uid = session["user_id"]
    db = get_db()

    rows = db.execute("""
        SELECT t.id, t.amount, t.note, t.date, c.name AS category, c.type
        FROM transactions t
        JOIN categories c ON t.category_id = c.id
        WHERE t.user_id = ?
        ORDER BY t.date DESC
    """, (uid,)).fetchall()

    transactions = []
    for r in rows:
        dt = datetime.fromisoformat(r["date"])
        transactions.append({
            "id": r["id"],
            "amount": r["amount"],
            "note": r["note"],
            "category": r["category"],
            "type": r["type"],
            "date": dt.strftime("%Y-%m-%d %H:%M")
        })

    db.close()
    return render_template("history.html", transactions=transactions)

# ================= SETTINGS =================
@app.route("/settings", methods=["GET", "POST"])
def settings():
    if "user_id" not in session:
        return redirect(url_for("login"))
    uid = session["user_id"]
    conn = get_db()
    cur = conn.cursor()

    if request.method == "POST":
        start_saving = float(request.form.get("start_saving", 0))
        saving_percent = float(request.form.get("saving_percent", 0))
        low_balance_alert = float(request.form.get("low_balance_alert", 0))
        new_password = request.form.get("new_password")

        cur.execute("""
            UPDATE user_settings
            SET default_saving = ?, saving_percent = ?, income_min_alert = ?
            WHERE user_id = ?
        """, (start_saving, saving_percent, low_balance_alert, uid))

        if new_password:
            cur.execute("UPDATE users SET password=? WHERE id=?",
                        (generate_password_hash(new_password), uid))

        conn.commit()
        flash("บันทึกการตั้งค่าเรียบร้อย", "success")

    cur.execute("SELECT * FROM user_settings WHERE user_id=?", (uid,))
    settings_data = cur.fetchone()
    conn.close()
    return render_template("settings.html", settings=settings_data)

# ================= YEAR SUMMARY =================
@app.route("/year_summary")
def year_summary():
    if "user_id" not in session:
        return redirect(url_for("login"))
    uid = session["user_id"]
    db = get_db()
    rows = db.execute("""
        SELECT strftime('%Y', t.date) AS year,
               SUM(CASE WHEN c.type='รายรับ' THEN t.amount ELSE 0 END) AS income,
               SUM(CASE WHEN c.type='รายจ่าย' THEN t.amount ELSE 0 END) AS expense
        FROM transactions t
        JOIN categories c ON t.category_id=c.id
        WHERE t.user_id=?
        GROUP BY year
        ORDER BY year
    """,(uid,)).fetchall()
    db.close()

    return render_template("year_summary.html",
                           labels=[r["year"] for r in rows],
                           income_data=[r["income"] or 0 for r in rows],
                           expense_data=[r["expense"] or 0 for r in rows])

# ================= SAVE SETTINGS (AJAX) =================
@app.route("/save_settings", methods=["POST"])
def save_settings_ajax():
    if "user_id" not in session:
        return jsonify({"success": False}), 401
    data = request.get_json()
    min_balance = float(data.get("min_balance", 0))
    db = get_db()
    db.execute("UPDATE user_settings SET income_min_alert=? WHERE user_id=?",
               (min_balance, session["user_id"]))
    db.commit()
    db.close()
    return jsonify({"success": True})

# ================= DELETE TRANSACTION =================
@app.route("/delete_transaction/<int:id>")
def delete_transaction(id):
    conn = get_db_connection()
    conn.execute("DELETE FROM transactions WHERE id = ?", (id,))
    conn.commit()
    conn.close()
    return redirect(url_for("history"))

# ================= RUN =================
if __name__ == "__main__":
    app.run(debug=True)
