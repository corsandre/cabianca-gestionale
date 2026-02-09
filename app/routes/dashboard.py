from datetime import date, timedelta
from flask import Blueprint, render_template
from flask_login import login_required
from sqlalchemy import func, extract
from app import db
from app.models import Transaction, CashRegisterDaily

bp = Blueprint("dashboard", __name__)


@bp.route("/")
@login_required
def index():
    today = date.today()
    first_of_month = today.replace(day=1)
    first_of_year = today.replace(month=1, day=1)

    # Monthly totals
    month_income = db.session.query(func.coalesce(func.sum(Transaction.amount), 0)).filter(
        Transaction.type == "entrata", Transaction.date >= first_of_month
    ).scalar()
    month_expense = db.session.query(func.coalesce(func.sum(Transaction.amount), 0)).filter(
        Transaction.type == "uscita", Transaction.date >= first_of_month
    ).scalar()

    # Yearly totals
    year_income = db.session.query(func.coalesce(func.sum(Transaction.amount), 0)).filter(
        Transaction.type == "entrata", Transaction.date >= first_of_year
    ).scalar()
    year_expense = db.session.query(func.coalesce(func.sum(Transaction.amount), 0)).filter(
        Transaction.type == "uscita", Transaction.date >= first_of_year
    ).scalar()

    # Overdue payments
    overdue = Transaction.query.filter(
        Transaction.due_date < today,
        Transaction.payment_status.in_(["da_pagare", "parziale"]),
    ).count()

    # Upcoming deadlines (next 7 days)
    week_ahead = today + timedelta(days=7)
    upcoming = Transaction.query.filter(
        Transaction.due_date.between(today, week_ahead),
        Transaction.payment_status.in_(["da_pagare", "parziale"]),
    ).order_by(Transaction.due_date).limit(10).all()

    # Monthly trend (last 6 months)
    monthly_data = []
    for i in range(5, -1, -1):
        m = today.month - i
        y = today.year
        while m <= 0:
            m += 12
            y -= 1
        m_income = db.session.query(func.coalesce(func.sum(Transaction.amount), 0)).filter(
            Transaction.type == "entrata",
            extract("month", Transaction.date) == m,
            extract("year", Transaction.date) == y,
        ).scalar()
        m_expense = db.session.query(func.coalesce(func.sum(Transaction.amount), 0)).filter(
            Transaction.type == "uscita",
            extract("month", Transaction.date) == m,
            extract("year", Transaction.date) == y,
        ).scalar()
        months_it = ["Gen", "Feb", "Mar", "Apr", "Mag", "Giu", "Lug", "Ago", "Set", "Ott", "Nov", "Dic"]
        monthly_data.append({"label": f"{months_it[m-1]} {y}", "income": float(m_income), "expense": float(m_expense)})

    # Recent transactions
    recent = Transaction.query.order_by(Transaction.date.desc(), Transaction.id.desc()).limit(10).all()

    return render_template("dashboard/index.html",
        month_income=month_income, month_expense=month_expense,
        year_income=year_income, year_expense=year_expense,
        overdue=overdue, upcoming=upcoming,
        monthly_data=monthly_data, recent=recent,
    )
