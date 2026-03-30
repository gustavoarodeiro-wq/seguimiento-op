"""
Sistema de permisos por usuario.

Cada permiso tiene un valor por defecto según el rol.
Los overrides individuales se guardan en usuario.permisos_json y
tienen prioridad sobre el default del rol.
"""
import json

# ── Definición de todos los permisos del sistema ──────────────────────────────

TODOS_LOS_PERMISOS = {
    "crear_orden":        "Crear nuevas órdenes de producción",
    "cambiar_estado":     "Cambiar el estado de una orden",
    "editar_datos_orden": "Editar datos de la orden (OP, lotes, vencimiento)",
    "registrar_entrega":  "Registrar y editar entregas",
    "manejar_etapas":     "Iniciar, completar y revertir etapas de producción",
    "agregar_faltante":   "Agregar y resolver faltantes",
    "eliminar_orden":     "Eliminar órdenes (estados revisar/faltante)",
    "ver_alertas":        "Ver el panel de alertas activas",
    "configurar_alertas": "Configurar los días límite de alertas",
    "editar_maestros":    "Crear y editar maestros (productos, MPs, formas, fórmulas)",
    "gestionar_usuarios": "Gestionar usuarios del sistema",
    "accion_admin":       "Acciones de administrador: revertir etapas, eliminar entregas, eliminar órdenes en cualquier estado",
}

# Grupos para mostrar en la UI
GRUPOS_PERMISOS = [
    ("Órdenes", [
        "crear_orden",
        "cambiar_estado",
        "editar_datos_orden",
        "eliminar_orden",
    ]),
    ("Producción", [
        "manejar_etapas",
        "agregar_faltante",
        "registrar_entrega",
    ]),
    ("Alertas", [
        "ver_alertas",
        "configurar_alertas",
    ]),
    ("Administración", [
        "editar_maestros",
        "gestionar_usuarios",
        "accion_admin",
    ]),
]

# ── Defaults por rol ──────────────────────────────────────────────────────────

_DEFAULTS: dict[str, dict[str, bool]] = {
    "admin": {p: True for p in TODOS_LOS_PERMISOS},  # incluye accion_admin
    "supervisor": {
        "crear_orden":        True,
        "cambiar_estado":     True,
        "editar_datos_orden": True,
        "registrar_entrega":  True,
        "manejar_etapas":     True,
        "agregar_faltante":   True,
        "eliminar_orden":     False,
        "ver_alertas":        True,
        "configurar_alertas": False,
        "editar_maestros":    False,
        "gestionar_usuarios": False,
    },
    "operador": {
        "crear_orden":        False,
        "cambiar_estado":     False,
        "editar_datos_orden": False,
        "registrar_entrega":  False,
        "manejar_etapas":     True,
        "agregar_faltante":   True,
        "eliminar_orden":     False,
        "ver_alertas":        False,
        "configurar_alertas": False,
        "editar_maestros":    False,
        "gestionar_usuarios": False,
    },
    "observador": {p: False for p in TODOS_LOS_PERMISOS},
}


def compute_permisos(rol: str, permisos_json: str | None) -> dict[str, bool]:
    """
    Devuelve el dict de permisos efectivos para un usuario.
    Aplica los defaults del rol y luego los overrides individuales.
    """
    base = _DEFAULTS.get(rol, {p: False for p in TODOS_LOS_PERMISOS}).copy()
    if permisos_json:
        try:
            overrides = json.loads(permisos_json)
            for k, v in overrides.items():
                if k in base:
                    base[k] = bool(v)
        except (json.JSONDecodeError, TypeError):
            pass
    return base


def default_permisos(rol: str) -> dict[str, bool]:
    """Devuelve los permisos por defecto para un rol (sin overrides)."""
    return _DEFAULTS.get(rol, {p: False for p in TODOS_LOS_PERMISOS}).copy()
