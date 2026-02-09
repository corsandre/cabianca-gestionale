"""4CloudOffice integration for cash register data sync.

Scrapes Z-reports from the 4CloudOffice portal (v2) and creates separate
Transaction records for each reparto/aliquota IVA combination.

Portal structure (discovered via exploration):
- Login via AJAX event system: POST /v2/_modules/Main_Login_1
- Site selection: POST /v2/_modules/Main_SiteSelector_22 with siteId=19940
- Z-Report data: POST /controllers/ZReport with {start, stop, searchCase}
- Date format: dd/mm/yyyy
- Table id="zreport-summary" with CSS-class-based columns:
    zreport-date, zreport-zrepnum, zreport-documents_amount,
    zreport-[2]-tax-10, zreport-[2]-taxable-10,    (reparto 2 = IVA 10%)
    zreport-[11]-tax-0, zreport-[11]-taxable-0,    (reparto 11 = IVA 0%)
    zreport-[3]-tax-4, zreport-[3]-taxable-4,      (reparto 3 = IVA 4%)
    zreport-no_tax,                                  (esentasse)
    zreport-cash, zreport-bancomat_*, zreport-carta_*
"""

import json
import logging
from collections import defaultdict
from datetime import date, datetime, timedelta

import requests
from bs4 import BeautifulSoup
from flask import current_app

logger = logging.getLogger(__name__)

# Site ID for Azienda Agricola Ca' Bianca
SITE_ID = "19940"

# Mappatura dei 5 reparti cassa.
# Nel portale 4CloudOffice le colonne IVA seguono il pattern:
#   zreport-[REPARTO]-taxable-ALIQUOTA / zreport-[REPARTO]-tax-ALIQUOTA
# Attualmente presenti: [3]=4%, [2]=10%, [11]=0%.
# Il 22% non e' ancora stato usato ma verra' rilevato automaticamente.
# Il 10% nel portale e' unificato (reparto [2]) - va tutto a "Ristorazione agriturismo"
# perche' e' la voce principale; "Prodotti trasformati propri" restera' a 0 finche'
# il portale non splittera' il 10% in reparti separati.
REPARTI = [
    {
        "key": "iva_4",
        "name": "Prodotti freschi azienda agricola",
        "iva_rate": 4,
        "category_name": "Vendita prodotti",
        "revenue_stream_name": "Vendita diretta",
    },
    {
        "key": "iva_10_trasformati",
        "name": "Prodotti trasformati propri",
        "iva_rate": 10,
        "category_name": "Vendita prodotti",
        "revenue_stream_name": "Vendita diretta",
    },
    {
        "key": "iva_10_ristorazione",
        "name": "Ristorazione agriturismo",
        "iva_rate": 10,
        "category_name": "Ristorazione",
        "revenue_stream_name": "Agriturismo",
    },
    {
        "key": "iva_0",
        "name": "Fattoria didattica",
        "iva_rate": 0,
        "category_name": "Servizi",
        "revenue_stream_name": "Attivita didattiche",
    },
    {
        "key": "iva_22",
        "name": "Prodotti trasformati di terzi",
        "iva_rate": 22,
        "category_name": "Vendita prodotti",
        "revenue_stream_name": "Vendita diretta",
    },
]


def _login(session, base_url, username, password):
    """Login to 4CloudOffice via the AJAX event system."""
    # Step 1: GET login page to establish session cookie
    session.get(f"{base_url}/", timeout=30)

    # Step 2: POST login via event module
    resp = session.post(
        f"{base_url}/_modules/Main_Login_1",
        data=(
            "eventName=Application.Events.Main.LoginEvent"
            "&isForwardableEvent=0"
            "&destination=0"
            "&type=POST"
            "&eventModuleSender=Main_Login_1"
            "&eventModuleListener=Main.Login"
            f"&username={requests.utils.quote(username)}"
            f"&password={requests.utils.quote(password)}"
            "&remember=Remember%20Me"
        ),
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "X-Requested-With": "XMLHttpRequest",
        },
        timeout=30,
    )

    if resp.status_code != 200 or "site-choice" not in resp.text:
        raise ConnectionError("Login 4CloudOffice fallito: credenziali non valide.")

    # Step 3: Visit site-choice page
    session.get(f"{base_url}/site-choice", timeout=30)

    # Step 4: Select the site
    resp = session.post(
        f"{base_url}/_modules/Main_SiteSelector_22",
        data=(
            "eventName=Application.Events.Main.SiteSelectorChoosedSiteEvent"
            "&isForwardableEvent=0"
            "&destination=0"
            "&type=POST"
            "&eventModuleSender=Main_SiteSelector_22"
            "&eventModuleListener=Main.SiteSelector"
            f"&siteId={SITE_ID}"
        ),
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "X-Requested-With": "XMLHttpRequest",
        },
        timeout=30,
    )

    if resp.status_code != 200 or "site-home" not in resp.text:
        raise ConnectionError("Selezione site 4CloudOffice fallita.")

    # Step 5: Visit site-home to activate the session
    session.get(f"{base_url}/site-home", timeout=30)

    # Step 6: Visit zreport page to set up the context
    session.get(f"{base_url}/reports/zreport", timeout=30)


def _fetch_zreport_data(session, start_date, end_date):
    """Fetch Z-report table data for the given date range.

    Calls POST /controllers/ZReport with dd/mm/yyyy dates.
    Returns list of dicts, one per Z-report row with non-zero amounts.
    """
    resp = session.post(
        "https://www.4cloudoffice.com/controllers/ZReport",
        data={
            "start": start_date.strftime("%d/%m/%Y"),
            "stop": end_date.strftime("%d/%m/%Y"),
            "zreport": "",
            "searchCase": "custom",
        },
        headers={"X-Requested-With": "XMLHttpRequest"},
        timeout=60,
    )

    if resp.status_code != 200:
        raise ConnectionError(f"Errore caricamento Z-Report: status {resp.status_code}")

    soup = BeautifulSoup(resp.text, "html.parser")
    table = soup.find("table", id="zreport-summary")
    if not table:
        logger.info("Nessuna tabella Z-Report trovata nella risposta")
        return []

    rows = []
    tbody = table.find("tbody")
    tr_list = tbody.find_all("tr") if tbody else table.find_all("tr")[1:]

    for tr in tr_list:
        row = _parse_zreport_row(tr)
        if row and row["documents_amount"] > 0:
            rows.append(row)

    return rows


def _parse_zreport_row(tr):
    """Parse a single <tr> from the zreport-summary table.

    Extracts values by CSS class on <td> elements.
    Column classes follow the pattern: zreport-[REPARTO]-taxable-ALIQUOTA
    This parser collects all IVA rates dynamically.
    """
    import re

    cells_by_class = {}
    for td in tr.find_all("td"):
        classes = td.get("class", [])
        text = td.get_text(strip=True)
        for cls in classes:
            cells_by_class[cls] = text

    # Extract date
    date_str = cells_by_class.get("zreport-date", "")
    if not date_str:
        return None

    rec_date = _parse_datetime_to_date(date_str)
    if not rec_date:
        return None

    # Dynamically extract all IVA rates from CSS classes
    # Pattern: zreport-[X]-taxable-RATE or zreport-[X]-tax-RATE
    iva_data = {}  # {rate: {"taxable": float, "tax": float}}
    for cls, text in cells_by_class.items():
        m = re.match(r"zreport-\[\d+\]-(taxable|tax)-(\d+)", cls)
        if m:
            field = m.group(1)  # "taxable" or "tax"
            rate = int(m.group(2))
            if rate not in iva_data:
                iva_data[rate] = {"taxable": 0.0, "tax": 0.0}
            iva_data[rate][field] += _parse_amount(text)

    return {
        "date": rec_date,
        "zreport_num": cells_by_class.get("zreport-zrepnum", ""),
        "documents_amount": _parse_amount(cells_by_class.get("zreport-documents_amount", "0")),
        "iva_data": iva_data,
        "no_tax": _parse_amount(cells_by_class.get("zreport-no_tax", "0")),
        "cash": _parse_amount(cells_by_class.get("zreport-cash", "0")),
        "bancomat": _parse_amount(_get_by_prefix(cells_by_class, "zreport-bancomat")),
        "carta": _parse_amount(_get_by_prefix(cells_by_class, "zreport-carta")),
    }


def _get_by_prefix(cells_by_class, prefix):
    """Get the first value from cells_by_class where the key starts with prefix."""
    for cls, val in cells_by_class.items():
        if cls.startswith(prefix):
            return val
    return "0"


def _aggregate_by_date(rows):
    """Aggregate multiple Z-reports for the same date.

    Multiple closures per day are summed together.
    Returns dict {date: {"iva_data": {rate: {"taxable", "tax"}}, "no_tax", ...}}
    """
    by_date = {}

    for row in rows:
        d = row["date"]
        if d not in by_date:
            by_date[d] = {
                "iva_data": {},
                "no_tax": 0, "documents_amount": 0,
                "cash": 0, "bancomat": 0, "carta": 0,
            }
        day = by_date[d]
        day["no_tax"] += row.get("no_tax", 0)
        day["documents_amount"] += row.get("documents_amount", 0)
        day["cash"] += row.get("cash", 0)
        day["bancomat"] += row.get("bancomat", 0)
        day["carta"] += row.get("carta", 0)

        for rate, amounts in row.get("iva_data", {}).items():
            if rate not in day["iva_data"]:
                day["iva_data"][rate] = {"taxable": 0.0, "tax": 0.0}
            day["iva_data"][rate]["taxable"] += amounts["taxable"]
            day["iva_data"][rate]["tax"] += amounts["tax"]

    return by_date


def _resolve_reparto_ids():
    """Look up category_id and revenue_stream_id for each reparto from the DB."""
    from app.models import Category, RevenueStream

    ids = {}
    for reparto in REPARTI:
        cat = Category.query.filter_by(name=reparto["category_name"], active=True).first()
        rs = RevenueStream.query.filter_by(name=reparto["revenue_stream_name"], active=True).first()
        ids[reparto["key"]] = {
            "category_id": cat.id if cat else None,
            "revenue_stream_id": rs.id if rs else None,
        }
    return ids


def _build_reparti_data(day_data):
    """Map aggregated day data to reparto entries.

    Uses the dynamic iva_data dict {rate: {"taxable", "tax"}} from the portal.
    The 10% IVA goes entirely to iva_10_ristorazione (the portal doesn't split it).
    iva_10_trasformati stays at 0 until the portal provides a split.
    The 22% is looked up dynamically (currently unused in the portal).

    Returns list of dicts with reparto data (only entries with total > 0).
    """
    iva_data = day_data.get("iva_data", {})
    reparti_data = []

    for reparto in REPARTI:
        key = reparto["key"]
        rate = reparto["iva_rate"]

        if key == "iva_10_trasformati":
            # Not split in the portal yet - stays at 0
            net = 0.0
            iva = 0.0
        elif key == "iva_10_ristorazione":
            # All 10% goes here
            amounts = iva_data.get(10, {"taxable": 0.0, "tax": 0.0})
            net = amounts["taxable"]
            iva = amounts["tax"]
        else:
            # Direct mapping by IVA rate (4%, 0%, 22%)
            amounts = iva_data.get(rate, {"taxable": 0.0, "tax": 0.0})
            net = amounts["taxable"]
            iva = amounts["tax"]

        total = round(net + iva, 2)
        if total == 0:
            continue

        reparti_data.append({
            "key": key,
            "name": reparto["name"],
            "iva_rate": rate,
            "net": round(net, 2),
            "iva": round(iva, 2),
            "total": total,
        })

    return reparti_data


def _save_day(rec_date, reparti_data, reparto_ids):
    """Save/update transactions and CashRegisterDaily for one day.

    Deletes existing source='cassa' transactions for the date,
    then creates new ones (one per reparto with total > 0).
    """
    from app import db
    from app.models import CashRegisterDaily, Transaction

    # Delete existing cassa transactions for this date
    Transaction.query.filter_by(source="cassa", date=rec_date).delete()

    day_total = 0.0
    details = []

    for rd in reparti_data:
        ids = reparto_ids.get(rd["key"], {})
        tx = Transaction(
            type="entrata",
            source="cassa",
            official=True,
            amount=rd["total"],
            net_amount=rd["net"],
            iva_amount=rd["iva"],
            iva_rate=rd["iva_rate"],
            date=rec_date,
            description=f"Cassa {rec_date.strftime('%d/%m/%Y')} - {rd['name']}",
            category_id=ids.get("category_id"),
            revenue_stream_id=ids.get("revenue_stream_id"),
            payment_status="pagato",
            payment_method="contanti",
            payment_date=rec_date,
        )
        db.session.add(tx)
        day_total += rd["total"]

        details.append({
            "reparto": rd["name"],
            "iva_rate": rd["iva_rate"],
            "net": rd["net"],
            "iva": rd["iva"],
            "total": rd["total"],
        })

    # Update or create CashRegisterDaily
    daily = CashRegisterDaily.query.filter_by(date=rec_date).first()
    if daily:
        daily.total_amount = round(day_total, 2)
        daily.details = json.dumps(details)
        daily.synced_at = datetime.utcnow()
    else:
        daily = CashRegisterDaily(
            date=rec_date,
            total_amount=round(day_total, 2),
            details=json.dumps(details),
            synced_at=datetime.utcnow(),
        )
        db.session.add(daily)

    return day_total


def sync_cash_register():
    """Sync daily cash register data from 4CloudOffice Z-reports.

    Returns the number of days updated.
    """
    from app import db
    from app.models import CashRegisterDaily

    base_url = current_app.config.get("CLOUD_OFFICE_URL", "https://www.4cloudoffice.com/v2").rstrip("/")
    username = current_app.config.get("CLOUD_OFFICE_USER", "")
    password = current_app.config.get("CLOUD_OFFICE_PASSWORD", "")

    if not username or not password:
        raise ValueError("4CloudOffice non configurato. Controlla le impostazioni.")

    session = requests.Session()
    session.headers.update({"User-Agent": "CaBiancaGestionale/1.0"})

    # Step 1: Login and select site
    _login(session, base_url, username, password)
    logger.info("4CloudOffice login e selezione site riusciti")

    # Step 2: Determine date range
    last_record = CashRegisterDaily.query.order_by(CashRegisterDaily.date.desc()).first()
    if last_record and last_record.date:
        start_date = last_record.date
    else:
        start_date = date(2025, 1, 1)
    end_date = date.today()

    # Step 3: Fetch Z-report data
    rows = _fetch_zreport_data(session, start_date, end_date)
    logger.info(f"Trovati {len(rows)} Z-report con dati da {start_date} a {end_date}")

    if not rows:
        return 0

    # Step 4: Aggregate by date (multiple closures per day)
    by_date = _aggregate_by_date(rows)

    # Step 5: Resolve reparto IDs from DB
    reparto_ids = _resolve_reparto_ids()

    # Step 6: Save each day
    count = 0
    for rec_date in sorted(by_date.keys()):
        reparti_data = _build_reparti_data(by_date[rec_date])
        if reparti_data:
            _save_day(rec_date, reparti_data, reparto_ids)
            count += 1

    db.session.commit()

    # Send Telegram notification
    try:
        from app.services.telegram_bot import send_telegram_message
        if count:
            send_telegram_message(f"Cassa sincronizzata: {count} giorni aggiornati.")
    except Exception:
        pass

    return count


def _parse_datetime_to_date(s):
    """Parse a datetime string like '2025-03-09 11:43:56' to a date object."""
    if not s:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d/%m/%Y %H:%M:%S", "%d/%m/%Y"):
        try:
            return datetime.strptime(s.strip(), fmt).date()
        except (ValueError, TypeError):
            continue
    return None


def _parse_amount(text):
    """Parse an Italian-format currency amount (e.g. '1.234,56') to float."""
    if not text:
        return 0.0
    cleaned = text.replace("€", "").replace("\xa0", "").strip()
    # Italian format: 1.234,56 -> remove dots, replace comma with period
    if "," in cleaned and "." in cleaned:
        cleaned = cleaned.replace(".", "").replace(",", ".")
    elif "," in cleaned:
        cleaned = cleaned.replace(",", ".")
    try:
        return abs(float(cleaned))
    except (ValueError, TypeError):
        return 0.0
