"""I 14 allergeni da evidenziare in etichetta (Reg. UE 1169/2011, allegato II). Senza Flask.

Il codice (chiave) è quello salvato nel database (colonne `allergeni`, lista JSON).
"""

ALLERGENI = {
    "glutine": "Cereali contenenti glutine (grano, segale, orzo, avena, farro, kamut…)",
    "crostacei": "Crostacei",
    "uova": "Uova",
    "pesce": "Pesce",
    "arachidi": "Arachidi",
    "soia": "Soia",
    "latte": "Latte (compreso il lattosio)",
    "frutta_guscio": "Frutta a guscio (mandorle, nocciole, noci, pistacchi…)",
    "sedano": "Sedano",
    "senape": "Senape",
    "sesamo": "Semi di sesamo",
    "solfiti": "Anidride solforosa e solfiti (oltre 10 mg/kg o 10 mg/l)",
    "lupini": "Lupini",
    "molluschi": "Molluschi",
}

# Nome breve per i riepiloghi (libro lotti, schede)
NOMI_BREVI = {
    "glutine": "glutine", "crostacei": "crostacei", "uova": "uova", "pesce": "pesce", "arachidi": "arachidi",
    "soia": "soia", "latte": "latte", "frutta_guscio": "frutta a guscio", "sedano": "sedano", "senape": "senape",
    "sesamo": "sesamo", "solfiti": "solfiti", "lupini": "lupini", "molluschi": "molluschi",
}


def pulisci(codici):
    """Tiene solo codici validi, senza doppioni, nell'ordine ufficiale."""
    scelti = set(codici or [])
    return [c for c in ALLERGENI if c in scelti]


def descrivi(codici):
    """'glutine, uova, latte' (vuoto se nessuno)."""
    return ", ".join(NOMI_BREVI[c] for c in pulisci(codici))
