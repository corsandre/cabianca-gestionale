"""Generatore automatico di transazioni da template ricorrenti."""
import calendar
from datetime import date, timedelta
from app import db
from app.models import RecurringExpense, Transaction


def _next_date(current, frequency, custom_days=None):
    """Calcola la prossima data in base alla frequenza."""
    if frequency == "custom" and custom_days:
        return current + timedelta(days=custom_days)

    months_map = {
        "mensile": 1,
        "bimestrale": 2,
        "trimestrale": 3,
        "semestrale": 6,
        "annuale": 12,
    }
    months = months_map.get(frequency, 1)

    year = current.year
    month = current.month + months
    while month > 12:
        month -= 12
        year += 1
    day = min(current.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def generate_for_template(template):
    """Genera transazioni per un singolo template fino alla finestra configurata.
    Ritorna il numero di transazioni create."""
    if not template.active:
        return 0

    today = date.today()
    horizon = today + timedelta(days=template.generation_months * 30)

    # Se c'e' una data fine, non generare oltre
    if template.end_date and horizon > template.end_date:
        horizon = template.end_date

    # Punto di partenza: ultima generazione o data inizio
    if template.last_generated_date:
        current = _next_date(template.last_generated_date, template.frequency, template.custom_days)
    else:
        current = template.start_date

    count = 0
    while current <= horizon:
        # Rispetta data fine
        if template.end_date and current > template.end_date:
            break

        # Deduplicazione: controlla se esiste gia'
        existing = Transaction.query.filter_by(
            recurring_expense_id=template.id,
            date=current,
        ).first()

        if not existing:
            # Calcolo IVA
            amount = template.amount
            iva_rate = template.iva_rate or 0
            if iva_rate > 0 and amount > 0:
                net_amount = round(amount / (1 + iva_rate / 100), 2)
                iva_amount = round(amount - net_amount, 2)
            else:
                net_amount = amount
                iva_amount = 0

            # Calcolo scadenza
            due_date = None
            if template.due_days_offset is not None and template.due_days_offset >= 0:
                due_date = current + timedelta(days=template.due_days_offset)

            t = Transaction(
                type=template.type,
                source="ricorrente",
                official=template.official,
                amount=amount,
                iva_rate=iva_rate,
                net_amount=net_amount,
                iva_amount=iva_amount,
                date=current,
                description=template.description or template.name,
                contact_id=template.contact_id,
                category_id=template.category_id,
                revenue_stream_id=template.revenue_stream_id,
                payment_method=template.payment_method,
                payment_status=template.payment_status or "da_pagare",
                due_date=due_date,
                notes=template.notes,
                recurring_expense_id=template.id,
                created_by=template.created_by,
            )
            db.session.add(t)
            count += 1

        template.last_generated_date = current
        current = _next_date(current, template.frequency, template.custom_days)

    if count > 0:
        db.session.commit()

    return count


def generate_all():
    """Processa tutti i template attivi. Ritorna il totale di transazioni create."""
    templates = RecurringExpense.query.filter_by(active=True).all()
    total = 0
    for tpl in templates:
        total += generate_for_template(tpl)
    return total
