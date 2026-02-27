from flask import Flask, render_template, request, redirect, url_for, flash, send_file
from models import db, User, Expense, Budget, Event
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from collections import defaultdict
import os, io
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from forms import LoginForm
from sqlalchemy import event
from sqlalchemy.engine import Engine
import sqlite3

@event.listens_for(Engine, "connect")
def enable_sqlite_foreign_key(dbapi_connection, connection_record):
    if isinstance(dbapi_connection, sqlite3.Connection):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON;")
        cursor.close()

app = Flask(__name__)

app.config["SECRET_KEY"] = "super-secret-key-change-this"
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///database.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config["UPLOAD_FOLDER"] = "static/uploads"

db.init_app(app)
with app.app_context():
    db.create_all()

login_manager = LoginManager()
login_manager.login_view = "login"
login_manager.init_app(app)


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


# ================= AUTO CATEGORY =================
def detect_category(description):
    if not description:
        return "Other"

    description = description.lower()

    keywords = {
        "Food": ["swiggy", "zomato", "restaurant", "cafe", "food"],
        "Transport": ["uber", "ola", "bus", "train", "petrol"],
        "Shopping": ["amazon", "flipkart", "mall"],
        "Entertainment": ["netflix", "movie", "spotify"],
        "Bills": ["electricity", "water", "rent"],
        "Study": ["book", "course"]
    }

    for category, words in keywords.items():
        if any(word in description for word in words):
            return category

    return "Other"


# ================= HOME =================
@app.route("/")
def home():
    return redirect(url_for("login"))


# ================= REGISTER =================
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        user = User(
            username=request.form.get("username"),
            email=request.form.get("email"),
            password=generate_password_hash(request.form.get("password"))
        )
        db.session.add(user)
        db.session.commit()
        return redirect(url_for("login"))

    return render_template("register.html")


# ================= LOGIN =================
@app.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "POST":

        email = request.form.get("email")
        password = request.form.get("password")

        # Find user
        user = User.query.filter_by(email=email).first()

        if user and check_password_hash(user.password, password):
            login_user(user)
            return redirect(url_for("dashboard"))

        else:
            flash("Invalid email or password", "login_error")

    return render_template("login.html")


# ================= EXPORT PDF =================
@app.route("/export_dashboard_pdf")
@login_required
def export_dashboard_pdf():

    expenses = Expense.query.filter_by(user_id=current_user.id).all()

    total_expense = sum(e.amount for e in expenses if e.transaction_type == "expense")
    total_income = sum(e.amount for e in expenses if e.transaction_type == "income")
    net_balance = total_income - total_expense

    buffer = io.BytesIO()
    p = canvas.Canvas(buffer, pagesize=letter)

    p.drawString(200, 750, "Smart Expense Tracker Report")
    p.drawString(100, 700, f"Total Expense: ₹ {total_expense}")
    p.drawString(100, 680, f"Total Income: ₹ {total_income}")
    p.drawString(100, 660, f"Net Balance: ₹ {net_balance}")

    y = 620
    for exp in expenses[:10]:
        y -= 20
        p.drawString(100, y, f"{exp.date} — {exp.description} — ₹ {exp.amount}")

    p.save()
    buffer.seek(0)

    return send_file(buffer, as_attachment=True,
                     download_name="dashboard_report.pdf",
                     mimetype="application/pdf")


# ================= CREATE EVENT =================
@app.route("/create_event", methods=["GET", "POST"])
@login_required
def create_event():
    if request.method == "POST":

        event = Event(
            name=request.form.get("name"),
            description=request.form.get("description"),
            date=request.form.get("date"),
            budget_limit=float(request.form.get("budget_limit") or 0),
            created_by=current_user.id
        )

        db.session.add(event)
        db.session.commit()

        flash("Event created successfully")
        return redirect(url_for("events"))

    return render_template("create_event.html")

# ================= DELETE EVENT =================
@app.route("/delete_event/<int:event_id>")
@login_required
def delete_event(event_id):

    event = Event.query.get(event_id)

    if event and event.created_by == current_user.id:
        db.session.delete(event)
        db.session.commit()

    return redirect(url_for("events"))    


# ================= EVENT ANALYTICS =================
@app.route("/event/<int:event_id>")
@login_required
def event_analytics(event_id):

    event = Event.query.get_or_404(event_id)

    expenses = Expense.query.filter_by(user_id=current_user.id, event_id=event_id).all()

    total_spent = sum(e.amount for e in expenses if e.transaction_type == "expense")
    total_income = sum(e.amount for e in expenses if e.transaction_type == "income")
    net_balance = total_income - total_spent

    budget = event.budget_limit or 0

    remaining_budget = budget - total_spent
    budget_percentage = round((total_spent / budget) * 100, 2) if budget > 0 else 0
    overspent = total_spent > budget if budget > 0 else False

    # CATEGORY TOTALS
    category_totals = defaultdict(float)
    trend_data = defaultdict(float)

    for e in expenses:
        if e.transaction_type == "expense":
            category_totals[e.category] += e.amount
            if e.date:
                trend_data[e.date] += e.amount

    highest_category = max(category_totals, key=category_totals.get) if category_totals else None
    highest_category_amount = category_totals.get(highest_category, 0)

    highest_day = max(trend_data, key=trend_data.get) if trend_data else None
    highest_day_amount = trend_data.get(highest_day, 0)

    total_transactions = len(expenses)
    avg_expense = total_spent / total_transactions if total_transactions else 0

    health_score = max(0, 100 - budget_percentage)

    event_summary = "This event is within budget."
    if overspent:
        event_summary = "This event exceeded its budget."
    elif budget_percentage > 80:
        event_summary = "This event is close to its budget limit."

    if highest_category:
        event_summary += f" Most spending was on {highest_category}."

    # ===== EVENT PERFORMANCE SCORE =====

    performance_score = 100

    if budget_percentage > 100:
       performance_score -= 40
    elif budget_percentage > 90:
         performance_score -= 25
    elif budget_percentage > 75:
         performance_score -= 15

    if highest_category_amount > (total_spent * 0.5):
       performance_score -= 10

    if total_transactions < 3:
       performance_score -= 5

    performance_score = max(0, performance_score)
    

    # ===== EVENT HEALTH SCORE =====
    health_score = 100

    if budget > 0:
       if budget_percentage > 100:
          health_score -= 30
       elif budget_percentage > 80:
             health_score -= 15

    avg_expense = total_spent / total_transactions if total_transactions else 0

    if avg_expense > 5000:
       health_score -= 10

    health_score = max(0, round(health_score, 2))

    recommendations = []

    if overspent:
       recommendations.append("Event exceeded budget. Reduce future spending.")

    elif budget_percentage > 80:
         recommendations.append("Event is close to budget limit.")

    if highest_category and highest_category_amount > total_spent * 0.4:
       recommendations.append(f"Most spending is on {highest_category}.")

    if not recommendations:
       recommendations.append("Event spending is well managed.")

    return render_template(
        "event_analytics.html",
        event=event,
        expenses=expenses,
        total_spent=total_spent,
        remaining_budget=remaining_budget,
        budget_percentage=budget_percentage,
        overspent=overspent,
        chart_labels=list(category_totals.keys()),
        chart_values=list(category_totals.values()),
        trend_labels=list(trend_data.keys()),
        trend_values=list(trend_data.values()),
        highest_category=highest_category,
        highest_category_amount=highest_category_amount,
        highest_day=highest_day,
        highest_day_amount=highest_day_amount,
        total_transactions=total_transactions,
        avg_expense=avg_expense,
        health_score=round(health_score, 2),
        event_summary=event_summary,
        total_income=total_income,
        net_balance=net_balance,
        performance_score=performance_score,
        recommendations=recommendations,


    )


# ================= EVENTS LIST =================
@app.route("/events")
@login_required
def events():

    search_query = request.args.get("search")

    query = Event.query.filter_by(created_by=current_user.id)

    if search_query:
        query = query.filter(Event.name.ilike(f"%{search_query}%"))

    events = query.order_by(Event.id.desc()).all()

    # ===== KPIs =====
    total_allocated = sum(e.budget_limit or 0 for e in events)
    active_events = len(events)

    from datetime import datetime, timedelta
    recent_count = Event.query.filter(
        Event.created_at >= datetime.now() - timedelta(days=30),
        Event.created_by == current_user.id
    ).count()

    return render_template(
        "events.html",
        events=events,
        total_allocated=total_allocated,
        active_events=active_events,
        recent_count=recent_count,
        search_query=search_query
    )


# ================= EDIT EVENT =================
@app.route("/edit_event/<int:event_id>", methods=["GET", "POST"])
@login_required
def edit_event(event_id):

    event = Event.query.get_or_404(event_id)

    # security check
    if event.created_by != current_user.id:
        flash("Unauthorized", "danger")
        return redirect(url_for("events"))

    if request.method == "POST":
        event.name = request.form.get("name")
        event.description = request.form.get("description")
        event.date = request.form.get("date")
        event.budget_limit = float(request.form.get("budget_limit") or 0)

        db.session.commit()
        flash("Event updated successfully", "success")
        return redirect(url_for("events"))

    return render_template("edit_event.html", event=event)

# ================= DASHBOARD =================
@app.route("/dashboard")
@login_required
def dashboard():

    search_query = request.args.get("search")

    expenses_query = Expense.query.filter_by(user_id=current_user.id)

    if search_query:
       expenses_query = expenses_query.filter(
          (Expense.description.ilike(f"%{search_query}%")) |
          (Expense.category.ilike(f"%{search_query}%"))
    )

    expenses = expenses_query.all()
    recent_expenses = expenses[-5:]

    total_expense = sum(e.amount for e in expenses if e.transaction_type == "expense")
    total_income = sum(e.amount for e in expenses if e.transaction_type == "income")
    budget = Budget.query.filter_by(user_id=current_user.id).first()
    monthly_limit = budget.monthly_limit if budget else 0

    net_balance = monthly_limit - total_expense
    total_transactions = len(expenses)

    # ===== GET PERSONAL BUDGET =====
    budget = Budget.query.filter_by(
    user_id=current_user.id,
    event_id=None
   ).first()

    monthly_limit = float(budget.monthly_limit) if budget else 0

    remaining_budget = monthly_limit - total_expense
    budget_percentage = (total_expense / monthly_limit) * 100 if monthly_limit > 0 else 0
    overspent = total_expense > monthly_limit if monthly_limit > 0 else False

    category_totals = defaultdict(float)
    trend_data = defaultdict(float)

    for e in expenses:
        if e.transaction_type == "expense":
            category_totals[e.category] += e.amount
            if e.date:
                trend_data[e.date] += e.amount

    # ===== HIGHEST CATEGORY =====
    highest_category = max(category_totals, key=category_totals.get) if category_totals else None
    highest_category_amount = category_totals.get(highest_category, 0)

    # ===== HIGHEST DAY =====
    highest_day = max(trend_data, key=trend_data.get) if trend_data else None
    highest_day_amount = trend_data.get(highest_day, 0)

    # ===== TOTAL CATEGORIES =====
    total_categories = len(category_totals)

    # ===== INCOME EXPENSE RATIO =====
    income_expense_ratio = round(total_income / total_expense, 2) if total_expense > 0 else 0

    # ===== PREDICTION =====
    predicted_expense = round(sum(trend_data.values()) / len(trend_data), 2) if trend_data else 0

    # ===== SMART INSIGHT =====
    insight_message = "Your finances are stable."

    if monthly_limit > 0:
        if budget_percentage > 100:
            insight_message = "⚠️ You exceeded your monthly budget."
        elif budget_percentage > 80:
            insight_message = "⚠️ You are close to your budget limit."
        elif budget_percentage < 50:
            insight_message = "✅ Spending is well under control."

        if total_income > total_expense:
            insight_message += " You are saving money."
    else:
        if total_expense > total_income:
            insight_message = "Expenses are higher than income."

    # ===== ALERTS =====
    large_expense_alert = any(e.amount > 5000 for e in expenses if e.transaction_type == "expense")

    spending_spike_alert = False
    if len(trend_data) >= 2:
        values = list(trend_data.values())
        if values[-1] > (sum(values[:-1]) / max(len(values[:-1]), 1)) * 1.5:
            spending_spike_alert = True

    near_budget_alert = budget_percentage >= 80 and budget_percentage < 100
    overspent_alert = budget_percentage >= 100

    # ===== HEALTH SCORE =====
    health_score = 100

    if budget_percentage > 100:
        health_score -= 30
    elif budget_percentage > 80:
        health_score -= 15

    if total_income > 0:
        ratio = total_expense / total_income
        if ratio > 1:
            health_score -= 25
        elif ratio > 0.8:
            health_score -= 10

    if spending_spike_alert:
        health_score -= 10

    health_score = max(0, round(health_score, 2))

    # ===== HEALTH LABEL =====
    health_label = "Excellent"

    if health_score < 40:
        health_label = "Risky"
    elif health_score < 70:
        health_label = "Moderate"
    elif health_score < 90:
        health_label = "Good"

    # ===== RECOMMENDATIONS =====
    recommendations = []

    if budget_percentage > 100:
        recommendations.append("You exceeded your monthly budget. Reduce non-essential spending.")
    elif budget_percentage > 80:
        recommendations.append("You are close to your budget limit. Be cautious with new expenses.")

    if highest_category and highest_category_amount > (total_expense * 0.4):
        recommendations.append(f"Your highest spending is on {highest_category}. Consider reducing it.")

    if total_income > 0 and total_expense > total_income:
        recommendations.append("Your expenses exceed your income. This is financially risky.")

    if large_expense_alert:
        recommendations.append("Large transactions detected recently. Review them.")

    if not recommendations:
        recommendations.append("Your finances look healthy. Keep it up.")


        

    return render_template(
        "dashboard.html",
        total_expense=total_expense,
        total_income=total_income,
        net_balance=net_balance,
        total_transactions=total_transactions,
        monthly_limit=monthly_limit,
        remaining_budget=remaining_budget,
        overspent=overspent,
        chart_labels=list(category_totals.keys()),
        chart_values=list(category_totals.values()),
        trend_labels=list(trend_data.keys()),
        trend_values=list(trend_data.values()),
        budget_percentage=budget_percentage,
        predicted_expense=predicted_expense,
        insight_message=insight_message,
        large_expense_alert=large_expense_alert,
        spending_spike_alert=spending_spike_alert,
        near_budget_alert=near_budget_alert,
        overspent_alert=overspent_alert,
        health_score=health_score,
        health_label=health_label,
        recommendations=recommendations,
        highest_category=highest_category,
        highest_category_amount=highest_category_amount,
        highest_day=highest_day,
        highest_day_amount=highest_day_amount,
        total_categories=total_categories,
        income_expense_ratio=income_expense_ratio,
        recent_expenses=recent_expenses
    )
    


# ================= SET BUDGET =================
@app.route("/set_budget", methods=["GET", "POST"])
@login_required
def set_budget():

    # ===== MODE SWITCH (NEW) =====
    mode = request.args.get("mode", "personal")
    selected_event_id = request.args.get("event_id")

    # ===== GET EVENTS FOR DROPDOWN =====
    events = Event.query.filter_by(created_by=current_user.id).all()

    # ===== SAVE BUDGET =====
    if request.method == "POST":

        limit = float(request.form.get("limit") or 0)
        budget_type = request.form.get("budget_type", "personal")
        event_id = request.form.get("event_id")

        if budget_type == "personal":
            event_id = None
        else:
            event_id = int(event_id) if event_id else None

        # IMPORTANT: check by user_id + event_id
        existing = Budget.query.filter_by(
            user_id=current_user.id,
            event_id=event_id
        ).first()

        if existing:
            existing.monthly_limit = limit
            existing.budget_type = budget_type
        else:
            new_budget = Budget(
                user_id=current_user.id,
                monthly_limit=limit,
                budget_type=budget_type,
                event_id=event_id
            )
            db.session.add(new_budget)

        db.session.commit()

    # ===== GET BUDGET BASED ON MODE =====
    if mode == "event" and selected_event_id:

        selected_event_id = int(selected_event_id)

        budget = Budget.query.filter_by(
            user_id=current_user.id,
            event_id=selected_event_id
        ).first()

        monthly_limit = budget.monthly_limit if budget else 0

        expenses = Expense.query.filter_by(
            user_id=current_user.id,
            event_id=selected_event_id,
            transaction_type="expense"
        ).all()

    else:
        # PERSONAL MODE
        budget = Budget.query.filter_by(
            user_id=current_user.id,
            event_id=None
        ).first()

        monthly_limit = budget.monthly_limit if budget else 0

        expenses = Expense.query.filter_by(
            user_id=current_user.id,
            event_id=None,
            transaction_type="expense"
        ).all()

    # ===== CALCULATIONS =====
    total_spent = sum(e.amount for e in expenses)

    remaining_budget = monthly_limit - total_spent

    usage_percent = (total_spent / monthly_limit * 100) if monthly_limit > 0 else 0

    # ===== CATEGORY BREAKDOWN =====
    from collections import defaultdict
    category_totals = defaultdict(float)

    for e in expenses:
        category_totals[e.category] += e.amount

    breakdown_labels = list(category_totals.keys())
    breakdown_values = list(category_totals.values())

    # ===== TREND MOCK (kept same logic) =====
    months = ["July", "Aug", "Sept", "Oct"]
    trend_budget = [monthly_limit] * 4
    trend_spent = [
        total_spent * 0.5,
        total_spent * 0.7,
        total_spent * 0.9,
        total_spent
    ]

    # ===== INSIGHT =====
    insight = "Budget healthy"

    if usage_percent > 90:
        insight = "⚠️ You are about to exceed your budget"
    elif usage_percent > 75:
        insight = "⚠️ You are close to your budget limit"

    alert = usage_percent > 75

    # ===== HISTORY =====
    history = [
        {
            "month": "September 2023",
            "budget": monthly_limit,
            "spent": total_spent,
            "status": "Healthy" if usage_percent < 80 else "Near Limit"
        },
        {
            "month": "August 2023",
            "budget": monthly_limit * 0.9,
            "spent": total_spent * 0.8,
            "status": "Near Limit"
        },
        {
            "month": "July 2023",
            "budget": monthly_limit * 0.8,
            "spent": total_spent * 0.9,
            "status": "Exceeded"
        }
    ]

    return render_template(
        "budget.html",
        monthly_limit=monthly_limit,
        total_spent=total_spent,
        remaining_budget=remaining_budget,
        usage_percent=round(usage_percent, 2),
        insight=insight,
        alert=alert,
        breakdown_labels=breakdown_labels,
        breakdown_values=breakdown_values,
        months=months,
        trend_budget=trend_budget,
        trend_spent=trend_spent,
        history=history,
        events=events,
        mode=mode,
        event_id=selected_event_id,
        expenses=expenses
    )
# ================= ADD EXPENSE =================
@app.route("/add_expense", methods=["GET", "POST"])
@login_required
def add_expense():

    events = Event.query.filter_by(created_by=current_user.id).all()

    if request.method == "POST":

        receipt_file = request.files.get("receipt")
        filename = None

        if receipt_file and receipt_file.filename:
            filename = secure_filename(receipt_file.filename)
            os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
            receipt_file.save(os.path.join(app.config["UPLOAD_FOLDER"], filename))

        expense = Expense(
            user_id=current_user.id,
            event_id=request.form.get("event_id") or None,
            amount=float(request.form.get("amount") or 0),
            category=detect_category(request.form.get("description")),
            description=request.form.get("description"),
            date=request.form.get("date"),
            transaction_type=request.form.get("transaction_type"),
            notes=request.form.get("notes"),
            tags=request.form.get("tags"),
            account=request.form.get("account"),
            receipt=filename
        )

        db.session.add(expense)
        db.session.commit()

        return redirect(url_for("dashboard"))

    return render_template("add_expense.html", events=events)


# ================= IMPORT CSV =================
# ================= IMPORT CSV =================
@app.route("/import_csv", methods=["GET", "POST"])
@login_required
def import_csv():

    if request.method == "POST":

        file = request.files.get("file")

        if not file or file.filename == "":
            flash("No file uploaded", "danger")
            return redirect(url_for("import_csv"))

        import pandas as pd
        from datetime import datetime

        try:
            # ===== READ CSV =====
            df = pd.read_csv(file)

            # ===== NORMALIZE COLUMN NAMES =====
            df.columns = (
                df.columns
                .str.strip()
                .str.lower()
                .str.replace(" ", "_")
            )

            # ===== REQUIRED COLUMNS =====
            required_columns = {"amount", "category", "description", "date"}

            if not required_columns.issubset(df.columns):
                flash("CSV missing required columns", "danger")
                print("CSV columns found:", df.columns.tolist())
                return redirect(url_for("import_csv"))

            count = 0

            # ===== LOOP ROWS =====
            for _, row in df.iterrows():

                try:
                    # Handle date safely
                    try:
                        parsed_date = datetime.strptime(
                            str(row.get("date")), "%Y-%m-%d"
                        )
                    except Exception:
                        # Try alternate format
                        parsed_date = datetime.strptime(
                            str(row.get("date")), "%d-%m-%Y"
                        )

                    expense = Expense(
                        user_id=current_user.id,
                        amount=float(row.get("amount", 0)),
                        category=row.get("category", "Other"),
                        description=row.get("description", ""),
                        date=parsed_date,
                        transaction_type=row.get("transaction_type") or "expense",
                        account=row.get("account", "Bank")
                    )

                    db.session.add(expense)
                    count += 1

                except Exception as err:
                    print("ROW ERROR:", err)
                    continue

            db.session.commit()

            flash(f"CSV imported successfully ✅ ({count} rows)", "success")
            return redirect(url_for("dashboard"))

        except Exception as e:
            print("IMPORT ERROR:", e)
            flash("Import failed — check CSV format", "danger")
            return redirect(url_for("import_csv"))

    return render_template("import_csv.html")

# ================= VIEW EXPENSES =================
@app.route("/expenses")
@login_required
def view_expenses():

    search_query = request.args.get("search")
    category_filter = request.args.get("category")
    date_filter = request.args.get("date")

    # BASE QUERY
    expenses_query = Expense.query.filter_by(user_id=current_user.id)

    # FILTERS
    if search_query:
        expenses_query = expenses_query.filter(
            Expense.description.ilike(f"%{search_query}%")
        )

    if category_filter:
        expenses_query = expenses_query.filter_by(category=category_filter)

    if date_filter:
        expenses_query = expenses_query.filter_by(date=date_filter)

    # ORDER
    expenses = expenses_query.order_by(Expense.date.desc()).all()

    # ================= TOTALS =================

    total_expense = sum(e.amount for e in expenses if e.transaction_type == "expense")
    total_income = sum(e.amount for e in expenses if e.transaction_type == "income")

    # ================= CATEGORY LIST =================

    categories = db.session.query(Expense.category)\
        .filter_by(user_id=current_user.id)\
        .distinct().all()

    categories = [c[0] for c in categories]

    # ================= TREND DATA =================

    trend_data = defaultdict(float)

    for e in expenses:
        if e.transaction_type == "expense" and e.date:
            trend_data[e.date] += e.amount

    trend_labels = list(trend_data.keys())
    trend_values = list(trend_data.values())

    # ================= RETURN =================

    return render_template(
        "expenses.html",
        expenses=expenses,
        categories=categories,
        total_expense=total_expense,
        total_income=total_income,
        trend_labels=trend_labels,
        trend_values=trend_values
    )


#================EDIT EXPENSES ===========================
@app.route("/edit_expense/<int:expense_id>", methods=["GET","POST"])
@login_required
def edit_expense(expense_id):
    expense = Expense.query.get_or_404(expense_id)
    if request.method == "POST":
        expense.amount = request.form.get("amount")
        expense.description = request.form.get("description")
        expense.category = request.form.get("category")
        db.session.commit()
        return redirect(url_for("view_expenses"))
    return render_template("edit_expense.html", expense=expense)  

# ================= DELETE EXPENSE =================
# ================= DELETE EXPENSE =================
@app.route("/delete_expense/<int:expense_id>")
@login_required
def delete_expense(expense_id):

    expense = Expense.query.get_or_404(expense_id)

    # security check
    if expense.user_id != current_user.id:
        flash("Unauthorized action", "danger")
        return redirect(url_for("view_expenses"))

    db.session.delete(expense)
    db.session.commit()

    flash("Expense deleted successfully", "success")
    return redirect(url_for("view_expenses"))


# ================= LOGOUT =================
@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("login"))


if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(debug=True)