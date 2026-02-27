from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin

db = SQLAlchemy()

# ================= USER =================
class User(UserMixin, db.Model):
    __tablename__ = "user"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)

    expenses = db.relationship("Expense", backref="user", lazy=True)
    budgets = db.relationship("Budget", backref="user", lazy=True)


# ================= EVENT =================
class Event(db.Model):
    __tablename__ = "event"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    description = db.Column(db.String(300))
    date = db.Column(db.String(50))
    budget_limit = db.Column(db.Float, default=0)
    created_by = db.Column(db.Integer, db.ForeignKey("user.id"))
    created_at = db.Column(db.DateTime, default=db.func.current_timestamp())
    
    expenses = db.relationship(
    "Expense",
    backref="event",
    cascade="all, delete-orphan",
    passive_deletes=True
)


# ================= EXPENSE =================
class Expense(db.Model):
    __tablename__ = "expense"

    id = db.Column(db.Integer, primary_key=True)

    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    event_id = db.Column(
    db.Integer,
    db.ForeignKey("event.id", ondelete="CASCADE"),
    nullable=True
)

    amount = db.Column(db.Float, nullable=False)
    category = db.Column(db.String(100))
    description = db.Column(db.String(200))
    date = db.Column(db.String(50))

    transaction_type = db.Column(db.String(20), default="expense")

    account = db.Column(db.String(50), default="Cash")

    notes = db.Column(db.Text)
    tags = db.Column(db.String(200))

    receipt = db.Column(db.String(300))


# ================= BUDGET =================
class Budget(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)

    monthly_limit = db.Column(db.Float, nullable=False)

    budget_type = db.Column(db.String(20), default="personal")  # personal OR event
    event_id = db.Column(db.Integer, db.ForeignKey("event.id"), nullable=True)


    Transaction = Expense  # This creates a "nickname" so both names work