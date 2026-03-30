"""
Caché en memoria para la configuración del sistema.
Se carga al arrancar y se actualiza cuando se guarda desde /configuracion.
"""
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# Valores por defecto
_cache: dict = {
    "nombre_laboratorio": "",
    "zona_horaria":       "local",   # "local" = usar reloj del SO
    "venc_minimo_meses":  "0",
    "formato_hora":       "24h",
}

def get(key: str, default: str = "") -> str:
    return _cache.get(key, default)

def set_all(values: dict) -> None:
    _cache.update(values)

def now_local() -> datetime:
    """
    Hora actual según la configuración:
    - Si zona_horaria == 'local' o está vacía: usa el reloj del SO (datetime.now())
    - Si es una zona IANA válida: usa esa zona horaria
    """
    tz_cfg = _cache.get("zona_horaria", "local")
    if not tz_cfg or tz_cfg == "local":
        return datetime.now()
    try:
        return datetime.now(ZoneInfo(tz_cfg)).replace(tzinfo=None)
    except ZoneInfoNotFoundError:
        return datetime.now()


def load_from_db(db) -> None:
    """Carga la configuración desde la base de datos al iniciar."""
    from database import ConfigSistema
    rows = db.query(ConfigSistema).all()
    for row in rows:
        _cache[row.clave] = row.valor or ""
