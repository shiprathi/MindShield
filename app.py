from flask import Flask, render_template, request, redirect, url_for, session
import sqlite3
from datetime import datetime, timedelta
import calendar

app = Flask(__name__)
app.secret_key = "mindshield_secret_key"


# =========================
# DATABASE
# =========================
def get_db():
    conn = sqlite3.connect("database.db")
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        role TEXT NOT NULL,
        nickname TEXT,
        full_name TEXT,
        email TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        organization TEXT
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS assessments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        score INTEGER NOT NULL,
        risk_level TEXT NOT NULL,
        suggestion TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS moods (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        mood_label TEXT NOT NULL,
        mood_emoji TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS journals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        content TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS wellness_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        sleep_hours REAL,
        study_hours REAL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS habits (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        habit_name TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS habit_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        habit_id INTEGER NOT NULL,
        day INTEGER NOT NULL,
        month INTEGER NOT NULL,
        year INTEGER NOT NULL,
        UNIQUE(habit_id, day, month, year)
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sender_id INTEGER NOT NULL,
        receiver_id INTEGER NOT NULL,
        message TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS student_counselor_map (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id INTEGER UNIQUE,
        counselor_id INTEGER
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS counselor_notes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        counselor_id INTEGER NOT NULL,
        student_id INTEGER NOT NULL,
        note TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    conn.commit()
    conn.close()


init_db()


# =========================
# HELPERS
# =========================
def require_login():
    return "user_id" in session


def get_latest_user_data(user_id):
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT score, risk_level
        FROM assessments
        WHERE user_id = ?
        ORDER BY id DESC
        LIMIT 1
    """, (user_id,))
    latest_assessment = cursor.fetchone()

    cursor.execute("""
        SELECT mood_label, mood_emoji
        FROM moods
        WHERE user_id = ?
        ORDER BY id DESC
        LIMIT 1
    """, (user_id,))
    latest_mood = cursor.fetchone()

    cursor.execute("""
        SELECT content
        FROM journals
        WHERE user_id = ?
        ORDER BY id DESC
        LIMIT 1
    """, (user_id,))
    latest_journal = cursor.fetchone()

    cursor.execute("""
        SELECT sleep_hours, study_hours
        FROM wellness_logs
        WHERE user_id = ?
        ORDER BY id DESC
        LIMIT 1
    """, (user_id,))
    latest_wellness = cursor.fetchone()

    conn.close()
    return latest_assessment, latest_mood, latest_journal, latest_wellness


def get_habit_data(user_id):
    conn = get_db()
    cursor = conn.cursor()

    now = datetime.now()
    current_month = now.month
    current_year = now.year
    days_in_month = calendar.monthrange(current_year, current_month)[1]

    cursor.execute("""
        SELECT id, habit_name
        FROM habits
        WHERE user_id = ?
        ORDER BY id DESC
    """, (user_id,))
    habits = cursor.fetchall()

    habit_data = []
    for habit in habits:
        cursor.execute("""
            SELECT day
            FROM habit_logs
            WHERE habit_id = ? AND month = ? AND year = ?
        """, (habit["id"], current_month, current_year))
        completed_days = {row["day"] for row in cursor.fetchall()}

        habit_data.append({
            "id": habit["id"],
            "name": habit["habit_name"],
            "completed_days": completed_days,
            "completed_count": len(completed_days)
        })

    conn.close()
    return habit_data, list(range(1, days_in_month + 1)), current_month, current_year


def get_wellness_history(user_id):
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT DATE(created_at) as log_date, sleep_hours, study_hours
        FROM wellness_logs
        WHERE user_id = ?
        ORDER BY created_at DESC
        LIMIT 7
    """, (user_id,))
    rows = cursor.fetchall()
    conn.close()

    data_map = {}
    for row in rows:
        data_map[row["log_date"]] = {
            "sleep": row["sleep_hours"] if row["sleep_hours"] is not None else 0,
            "study": row["study_hours"] if row["study_hours"] is not None else 0
        }

    history = []
    for i in range(6, -1, -1):
        d = datetime.now().date() - timedelta(days=i)
        key = str(d)
        sleep = data_map[key]["sleep"] if key in data_map else 0
        study = data_map[key]["study"] if key in data_map else 0

        history.append({
            "label": d.strftime("%a"),
            "sleep": sleep,
            "study": study,
            "sleep_height": min(int(sleep * 12), 140),
            "study_height": min(int(study * 12), 140)
        })

    return history


def assign_counselor(student_id):
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT organization FROM users WHERE id = ?", (student_id,))
    org_row = cursor.fetchone()
    if not org_row:
        conn.close()
        return

    org = org_row["organization"]

    cursor.execute("""
        SELECT id
        FROM users
        WHERE role = 'counselor' AND organization = ?
    """, (org,))
    counselors = cursor.fetchall()

    if not counselors:
        conn.close()
        return

    min_count = float("inf")
    selected_counselor = None

    for counselor in counselors:
        cursor.execute("""
            SELECT COUNT(*) AS cnt
            FROM student_counselor_map
            WHERE counselor_id = ?
        """, (counselor["id"],))
        count = cursor.fetchone()["cnt"]

        if count < min_count:
            min_count = count
            selected_counselor = counselor["id"]

    cursor.execute("""
        INSERT OR REPLACE INTO student_counselor_map (student_id, counselor_id)
        VALUES (?, ?)
    """, (student_id, selected_counselor))

    conn.commit()
    conn.close()


def assign_unmapped_students_for_org(organization):
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id
        FROM users
        WHERE role = 'student'
          AND organization = ?
          AND id NOT IN (
              SELECT student_id FROM student_counselor_map
          )
    """, (organization,))
    students = cursor.fetchall()
    conn.close()

    for student in students:
        assign_counselor(student["id"])


# =========================
# BASIC ROUTES
# =========================
@app.route("/")
def home():
    return render_template("login.html", error=None)


@app.route("/signup")
def signup():
    return render_template("signup_choice.html")


@app.route("/organization")
def organization():
    return render_template("organization_name.html")


@app.route("/role-selection")
def role_selection():
    org_name = request.args.get("org_name", "").strip()
    return render_template("role_selection.html", org_name=org_name)


# =========================
# LOGIN / LOGOUT
# =========================
@app.route("/login", methods=["GET", "POST"])
def login():
    error = None

    if request.method == "POST":
        email = request.form["email"].strip()
        password = request.form["password"].strip()

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, role, nickname, full_name
            FROM users
            WHERE email = ? AND password = ?
        """, (email, password))
        user = cursor.fetchone()
        conn.close()

        if user:
            session["user_id"] = user["id"]
            session["role"] = user["role"]
            session["name"] = user["nickname"] if user["nickname"] else user["full_name"]

            if user["role"] == "self":
                return redirect(url_for("self_dashboard"))
            elif user["role"] == "student":
                return redirect(url_for("student_dashboard"))
            elif user["role"] == "counselor":
                return redirect(url_for("counselor_dashboard"))
        else:
            error = "Invalid email or password"

    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))


# =========================
# SIGNUP
# =========================
@app.route("/self-signup", methods=["GET", "POST"])
def self_signup():
    if request.method == "POST":
        nickname = request.form["nickname"].strip()
        email = request.form["email"].strip()
        password = request.form["password"].strip()

        conn = get_db()
        cursor = conn.cursor()
        try:
            cursor.execute("""
                INSERT INTO users (role, nickname, email, password, organization)
                VALUES (?, ?, ?, ?, ?)
            """, ("self", nickname, email, password, None))
            conn.commit()
        except sqlite3.IntegrityError:
            conn.close()
            return render_template("self_signup.html", error="Email already exists")
        conn.close()
        return redirect(url_for("login"))

    return render_template("self_signup.html", error=None)


@app.route("/student-signup", methods=["GET", "POST"])
def student_signup():
    org_name = request.args.get("org_name", "").strip()

    if request.method == "POST":
        nickname = request.form["nickname"].strip()
        email = request.form["email"].strip()
        password = request.form["password"].strip()
        organization = request.form["organization"].strip()

        conn = get_db()
        cursor = conn.cursor()
        try:
            cursor.execute("""
                INSERT INTO users (role, nickname, email, password, organization)
                VALUES (?, ?, ?, ?, ?)
            """, ("student", nickname, email, password, organization))
            new_student_id = cursor.lastrowid
            conn.commit()
            conn.close()

            assign_counselor(new_student_id)
        except sqlite3.IntegrityError:
            conn.close()
            return render_template("student_signup.html", org_name=org_name, error="Email already exists")

        return redirect(url_for("login"))

    return render_template("student_signup.html", org_name=org_name, error=None)


@app.route("/counselor-signup", methods=["GET", "POST"])
def counselor_signup():
    org_name = request.args.get("org_name", "").strip()

    if request.method == "POST":
        full_name = request.form["full_name"].strip()
        email = request.form["email"].strip()
        password = request.form["password"].strip()
        organization = request.form["organization"].strip()

        conn = get_db()
        cursor = conn.cursor()
        try:
            cursor.execute("""
                INSERT INTO users (role, full_name, email, password, organization)
                VALUES (?, ?, ?, ?, ?)
            """, ("counselor", full_name, email, password, organization))
            conn.commit()
            conn.close()

            assign_unmapped_students_for_org(organization)
        except sqlite3.IntegrityError:
            conn.close()
            return render_template("counselor_signup.html", org_name=org_name, error="Email already exists")
        return redirect(url_for("login"))

    return render_template("counselor_signup.html", org_name=org_name, error=None)


# =========================
# DASHBOARDS
# =========================
@app.route("/self-dashboard")
def self_dashboard():
    if not require_login() or session.get("role") != "self":
        return redirect(url_for("login"))

    latest_assessment, latest_mood, latest_journal, latest_wellness = get_latest_user_data(session["user_id"])
    habit_data, month_days, current_month, current_year = get_habit_data(session["user_id"])
    wellness_history = get_wellness_history(session["user_id"])
    now_day = datetime.now().day

    return render_template(
        "self_dashboard.html",
        name=session.get("name", "User"),
        latest_assessment=latest_assessment,
        latest_mood=latest_mood,
        latest_journal=latest_journal,
        latest_wellness=latest_wellness,
        habit_data=habit_data,
        month_days=month_days,
        current_month=current_month,
        current_year=current_year,
        now_day=now_day,
        wellness_history=wellness_history
    )


@app.route("/student-dashboard")
def student_dashboard():
    if not require_login() or session.get("role") != "student":
        return redirect(url_for("login"))

    latest_assessment, latest_mood, latest_journal, latest_wellness = get_latest_user_data(session["user_id"])
    habit_data, month_days, current_month, current_year = get_habit_data(session["user_id"])
    wellness_history = get_wellness_history(session["user_id"])
    now_day = datetime.now().day

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT counselor_id
        FROM student_counselor_map
        WHERE student_id = ?
    """, (session["user_id"],))
    row = cursor.fetchone()

    if not row:
        conn.close()
        assign_counselor(session["user_id"])
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT counselor_id
            FROM student_counselor_map
            WHERE student_id = ?
        """, (session["user_id"],))
        row = cursor.fetchone()

    conn.close()
    counselor_id = row["counselor_id"] if row else None

    wellness_history = get_wellness_history(session["user_id"])

    return render_template(
    "student_dashboard.html",
    name=session.get("name", "Student"),
    latest_assessment=latest_assessment,
    latest_mood=latest_mood,
    latest_journal=latest_journal,
    latest_wellness=latest_wellness,
    habit_data=habit_data,
    month_days=month_days,
    current_month=current_month,
    current_year=current_year,
    now_day=now_day,
    counselor_id=counselor_id,
    wellness_history=wellness_history
)


@app.route("/counselor-dashboard")
def counselor_dashboard():
    if not require_login() or session.get("role") != "counselor":
        return redirect(url_for("login"))

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT 
            u.id,
            u.nickname,
            a.score,
            a.risk_level
        FROM users u
        JOIN student_counselor_map m
            ON u.id = m.student_id
        LEFT JOIN (
            SELECT a1.user_id, a1.score, a1.risk_level
            FROM assessments a1
            JOIN (
                SELECT user_id, MAX(id) AS max_id
                FROM assessments
                GROUP BY user_id
            ) latest
            ON a1.user_id = latest.user_id AND a1.id = latest.max_id
        ) a
            ON u.id = a.user_id
        WHERE m.counselor_id = ?
        ORDER BY u.nickname
    """, (session["user_id"],))
    students = cursor.fetchall()

    total_students = len(students)
    high_risk = sum(1 for s in students if s["risk_level"] == "High")
    moderate_risk = sum(1 for s in students if s["risk_level"] == "Moderate")
    low_risk = sum(1 for s in students if s["risk_level"] == "Low")
    pending_assessments = sum(1 for s in students if s["risk_level"] is None)

    habit_data, month_days, current_month, current_year = get_habit_data(session["user_id"])
    now_day = datetime.now().day

    conn.close()

    return render_template(
        "counselor_dashboard.html",
        name=session.get("name", "Counselor"),
        students=students,
        total_students=total_students,
        high_risk=high_risk,
        moderate_risk=moderate_risk,
        low_risk=low_risk,
        pending_assessments=pending_assessments,
        habit_data=habit_data,
        month_days=month_days,
        current_month=current_month,
        current_year=current_year,
        now_day=now_day
    )


# =========================
# ASSESSMENT
# =========================
@app.route("/assessment")
def assessment():
    if not require_login():
        return redirect(url_for("login"))
    return render_template("assessment.html")


@app.route("/submit-assessment", methods=["POST"])
def submit_assessment():
    if not require_login():
        return redirect(url_for("login"))

    q1 = int(request.form["q1"])
    q2 = int(request.form["q2"])
    q3 = int(request.form["q3"])
    q4 = int(request.form["q4"])
    q5 = int(request.form["q5"])

    total_score = q1 + q2 + q3 + q4 + q5

    if total_score <= 7:
        risk_level = "Low"
        suggestion = "Your current mental wellness indicators look stable. Continue self-care and healthy routines."
    elif total_score <= 13:
        risk_level = "Moderate"
        suggestion = "You may be experiencing rising stress. Focus on rest, calming exercises, and regular check-ins."
    else:
        risk_level = "High"
        suggestion = "Your responses suggest significant emotional strain. Consider reaching out for support and completing regular check-ins."

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO assessments (user_id, score, risk_level, suggestion)
        VALUES (?, ?, ?, ?)
    """, (session["user_id"], total_score, risk_level, suggestion))
    conn.commit()
    conn.close()

    return render_template(
    "assessment_result.html",
    score=total_score,
    risk_level=risk_level,
    role=session["role"]
)

# =========================
# MOOD
# =========================
@app.route("/save-mood", methods=["POST"])
def save_mood():
    if not require_login():
        return redirect(url_for("login"))

    mood_map = {
        "loving": "loving.jpeg",
        "disappointed": "disappointed.jpeg",
        "surprised": "surprised.jpeg",
        "anxious": "anxious.jpeg",
        "sad": "sad.jpeg",
        "excited": "excited.jpeg",
        "neutral": "neutral.jpeg",
        "happy": "happy.jpeg",
        "angry": "angry.jpeg"
    }

    selected_mood = request.form["mood"]

    if selected_mood not in mood_map:
        return redirect(request.referrer or url_for("home"))

    mood_file = mood_map[selected_mood]

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        DELETE FROM moods
        WHERE user_id = ? AND DATE(created_at) = DATE('now')
    """, (session["user_id"],))

    cursor.execute("""
        INSERT INTO moods (user_id, mood_label, mood_emoji)
        VALUES (?, ?, ?)
    """, (session["user_id"], selected_mood, mood_file))

    conn.commit()
    conn.close()

    return redirect(request.referrer or url_for("home"))


# =========================
# JOURNAL
# =========================
@app.route("/save-journal", methods=["POST"])
def save_journal():
    if not require_login():
        return redirect(url_for("login"))

    content = request.form["content"].strip()
    if not content:
        return redirect(request.referrer or url_for("home"))

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO journals (user_id, content)
        VALUES (?, ?)
    """, (session["user_id"], content))
    conn.commit()
    conn.close()

    return redirect(request.referrer or url_for("home"))


# =========================
# WELLNESS
# =========================
@app.route("/save-wellness", methods=["POST"])
def save_wellness():
    if not require_login():
        return redirect(url_for("login"))

    sleep_hours = request.form.get("sleep_hours", "").strip()
    study_hours = request.form.get("study_hours", "").strip()

    sleep_value = None
    study_value = None

    try:
        if sleep_hours:
            sleep_value = float(sleep_hours)
        if study_hours:
            study_value = float(study_hours)
    except ValueError:
        return redirect(request.referrer or url_for("home"))

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO wellness_logs (user_id, sleep_hours, study_hours)
        VALUES (?, ?, ?)
    """, (session["user_id"], sleep_value, study_value))
    conn.commit()
    conn.close()

    return redirect(request.referrer or url_for("home"))


# =========================
# HABITS
# =========================
@app.route("/add-habit", methods=["POST"])
def add_habit():
    if not require_login():
        return redirect(url_for("login"))

    habit_name = request.form["habit_name"].strip()
    if not habit_name:
        return redirect(request.referrer or url_for("home"))

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO habits (user_id, habit_name)
        VALUES (?, ?)
    """, (session["user_id"], habit_name))
    conn.commit()
    conn.close()

    return redirect(request.referrer or url_for("home"))


@app.route("/toggle-habit", methods=["POST"])
def toggle_habit():
    if not require_login():
        return redirect(url_for("login"))

    habit_id = int(request.form["habit_id"])
    day = int(request.form["day"])
    month = int(request.form["month"])
    year = int(request.form["year"])

    now = datetime.now()
    if day != now.day or month != now.month or year != now.year:
        return redirect(request.referrer or url_for("home"))

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id
        FROM habits
        WHERE id = ? AND user_id = ?
    """, (habit_id, session["user_id"]))
    owned_habit = cursor.fetchone()

    if not owned_habit:
        conn.close()
        return redirect(url_for("home"))

    cursor.execute("""
        SELECT id
        FROM habit_logs
        WHERE habit_id = ? AND day = ? AND month = ? AND year = ?
    """, (habit_id, day, month, year))
    existing = cursor.fetchone()

    if existing:
        cursor.execute("DELETE FROM habit_logs WHERE id = ?", (existing["id"],))
    else:
        cursor.execute("""
            INSERT INTO habit_logs (habit_id, day, month, year)
            VALUES (?, ?, ?, ?)
        """, (habit_id, day, month, year))

    conn.commit()
    conn.close()

    return redirect(request.referrer or url_for("home"))


# =========================
# CHAT / NOTES
# =========================
@app.route("/chat/<int:receiver_id>")
def chat(receiver_id):
    if not require_login():
        return redirect(url_for("login"))

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT sender_id, message
        FROM messages
        WHERE (sender_id = ? AND receiver_id = ?)
           OR (sender_id = ? AND receiver_id = ?)
        ORDER BY id
    """, (session["user_id"], receiver_id, receiver_id, session["user_id"]))
    messages = cursor.fetchall()

    cursor.execute("""
        SELECT nickname, full_name
        FROM users
        WHERE id = ?
    """, (receiver_id,))
    user = cursor.fetchone()

    notes = []
    if session.get("role") == "counselor":
        cursor.execute("""
            SELECT note, created_at
            FROM counselor_notes
            WHERE counselor_id = ? AND student_id = ?
            ORDER BY id DESC
        """, (session["user_id"], receiver_id))
        notes = cursor.fetchall()

    conn.close()

    if not user:
        return redirect(url_for("home"))

    name = user["nickname"] if user["nickname"] else user["full_name"]

    return render_template(
        "chat.html",
        messages=messages,
        receiver_id=receiver_id,
        name=name,
        notes=notes
    )


@app.route("/send-message", methods=["POST"])
def send_message():
    if not require_login():
        return redirect(url_for("login"))

    receiver_id = request.form["receiver_id"]
    message = request.form["message"].strip()

    if not message:
        return redirect(url_for("chat", receiver_id=receiver_id))

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO messages (sender_id, receiver_id, message)
        VALUES (?, ?, ?)
    """, (session["user_id"], receiver_id, message))
    conn.commit()
    conn.close()

    return redirect(url_for("chat", receiver_id=receiver_id))


@app.route("/save-note", methods=["POST"])
def save_note():
    if not require_login() or session.get("role") != "counselor":
        return redirect(url_for("login"))

    student_id = request.form["student_id"]
    note = request.form["note"].strip()

    if not note:
        return redirect(request.referrer or url_for("counselor_dashboard"))

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO counselor_notes (counselor_id, student_id, note)
        VALUES (?, ?, ?)
    """, (session["user_id"], student_id, note))
    conn.commit()
    conn.close()

    return redirect(request.referrer or url_for("counselor_dashboard"))


if __name__ == "__main__":
    app.run(debug=True)