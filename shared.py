"""
Instancia compartida de Jinja2Templates con globals comunes.
Todos los routers deben importar 'templates' desde aquí.
"""
from fastapi.templating import Jinja2Templates
import config_cache

templates = Jinja2Templates(directory="templates")
templates.env.cache = None  # workaround Python 3.14+
templates.env.globals["get_lab_nombre"] = lambda: config_cache.get("nombre_laboratorio", "")
templates.env.filters["fmt_unidad"] = lambda u: {"KG": "Kg", "G": "g", "ML": "mL", "UN": "UN", "L": "L"}.get(str(u), str(u))
