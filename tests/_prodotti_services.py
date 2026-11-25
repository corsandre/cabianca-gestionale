"""Carica app/moduli/prodotti/services come pacchetto a sé ("prodotti_services"), senza importare Flask
né il gestionale: così i test della logica pura girano anche con il python di sistema.

Uso nei test:  from _prodotti_services import servizi;  servizi("ingredienti").testo_ingredienti(...)
"""
import importlib
import importlib.util
import os
import sys

_CARTELLA = os.path.join(os.path.dirname(__file__), "..", "app", "moduli", "prodotti", "services")
_NOME = "prodotti_services"


def servizi(modulo):
    if _NOME not in sys.modules:
        spec = importlib.util.spec_from_file_location(
            _NOME, os.path.join(_CARTELLA, "__init__.py"), submodule_search_locations=[_CARTELLA])
        pacchetto = importlib.util.module_from_spec(spec)
        sys.modules[_NOME] = pacchetto
        spec.loader.exec_module(pacchetto)
    return importlib.import_module(f"{_NOME}.{modulo}")
