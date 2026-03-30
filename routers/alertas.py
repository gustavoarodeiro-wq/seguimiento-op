from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from datetime import datetime, timedelta

from config_cache import now_local as now_ar

from database import get_db, AlertaConfig, Orden, Entrega, HistorialEstado
from routers.auth import require_auth

router = APIRouter()

def _puede(user: dict, permiso: str) -> bool:
    return bool(user.get("permisos", {}).get(permiso, False))

# Configuraciones por defecto que se insertan si no existen
_DEFAULTS = [
    {
        "nombre": "Faltantes sin resolver",
        "descripcion": "Órdenes con más de N días en estado Faltante sin avanzar",
        "dias_limite": 7,
        "estado_aplica": "faltante",
        "activo": True,
    },
    {
        "nombre": "Emitida sin avanzar",
        "descripcion": "Órdenes con más de N días en estado Emitido sin pasar a En Proceso",
        "dias_limite": 5,
        "estado_aplica": "emitido",
        "activo": True,
    },
    {
        "nombre": "Terminada sin entrega",
        "descripcion": "Órdenes en estado Terminada hace más de N días sin entrega final registrada",
        "dias_limite": 10,
        "estado_aplica": "terminada_sin_entrega",
        "activo": True,
    },
]


def _seed_defaults(db: Session):
    for d in _DEFAULTS:
        existe = db.query(AlertaConfig).filter(
            AlertaConfig.estado_aplica == d["estado_aplica"]
        ).first()
        if not existe:
            db.add(AlertaConfig(
                nombre=d["nombre"],
                dias_limite=d["dias_limite"],
                estado_aplica=d["estado_aplica"],
                activo=d["activo"],
            ))
    db.commit()


def _config_dict(c: AlertaConfig) -> dict:
    desc_map = {d["estado_aplica"]: d["descripcion"] for d in _DEFAULTS}
    return {
        "id":           c.id,
        "nombre":       c.nombre,
        "descripcion":  desc_map.get(c.estado_aplica, ""),
        "dias_limite":  c.dias_limite,
        "estado_aplica": c.estado_aplica,
        "activo":       c.activo,
    }


# ── GET /api/alertas/config ────────────────────────────────────────────────────

@router.get("/api/alertas/config")
async def get_alertas_config(
    db: Session = Depends(get_db),
    user: dict = Depends(require_auth),
):
    if not _puede(user, "ver_alertas"):
        raise HTTPException(status_code=403, detail="Sin permisos.")
    _seed_defaults(db)
    items = db.query(AlertaConfig).order_by(AlertaConfig.id).all()
    return [_config_dict(c) for c in items]


# ── PUT /api/alertas/config/{id} ──────────────────────────────────────────────

@router.put("/api/alertas/config/{config_id}")
async def update_alerta_config(
    config_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: dict = Depends(require_auth),
):
    if not _puede(user, "configurar_alertas"):
        raise HTTPException(status_code=403, detail="Sin permisos.")
    config = db.query(AlertaConfig).filter(AlertaConfig.id == config_id).first()
    if not config:
        raise HTTPException(status_code=404, detail="Configuración no encontrada.")
    body = await request.json()
    if "dias_limite" in body:
        dias = int(body["dias_limite"])
        if dias < 1:
            raise HTTPException(status_code=422, detail="Los días deben ser al menos 1.")
        config.dias_limite = dias
    if "activo" in body:
        config.activo = bool(body["activo"])
    if "nombre" in body and body["nombre"].strip():
        config.nombre = body["nombre"].strip()
    db.commit()
    return _config_dict(config)


# ── GET /api/alertas ──────────────────────────────────────────────────────────

@router.get("/api/alertas")
async def get_alertas(
    db: Session = Depends(get_db),
    user: dict = Depends(require_auth),
):
    if not _puede(user, "ver_alertas"):
        return {"total": 0, "alertas": []}
    _seed_defaults(db)
    configs = (
        db.query(AlertaConfig)
        .filter(AlertaConfig.activo == True)
        .order_by(AlertaConfig.id)
        .all()
    )
    ahora = now_ar()
    alertas = []

    for c in configs:
        limite_fecha = ahora - timedelta(days=c.dias_limite)

        if c.estado_aplica == "terminada_sin_entrega":
            # Órdenes en estado terminada cuya última modificación fue hace más de N días
            # y que NO tienen entrega final registrada
            ordenes = (
                db.query(Orden)
                .filter(
                    Orden.estado == "terminada",
                    Orden.ultima_modificacion_fecha != None,
                    Orden.ultima_modificacion_fecha <= limite_fecha,
                )
                .order_by(Orden.ultima_modificacion_fecha.asc())
                .all()
            )
            for o in ordenes:
                tiene_final = db.query(Entrega).filter(
                    Entrega.orden_id == o.id,
                    Entrega.es_entrega_final == True,
                ).first()
                if not tiene_final:
                    dias_en_estado = (ahora - o.ultima_modificacion_fecha).days
                    alertas.append({
                        "config_id":            c.id,
                        "tipo":                 c.estado_aplica,
                        "nombre_alerta":        c.nombre,
                        "dias_limite":          c.dias_limite,
                        "dias_en_estado":       dias_en_estado,
                        "orden_id":             o.id,
                        "op":                   o.op,
                        "descripcion_producto": o.descripcion_producto,
                        "estado_orden":         o.estado,
                    })
        else:
            ordenes = (
                db.query(Orden)
                .filter(
                    Orden.estado == c.estado_aplica,
                    Orden.ultima_modificacion_fecha != None,
                    Orden.ultima_modificacion_fecha <= limite_fecha,
                )
                .order_by(Orden.ultima_modificacion_fecha.asc())
                .all()
            )
            for o in ordenes:
                dias_en_estado = (ahora - o.ultima_modificacion_fecha).days
                alertas.append({
                    "config_id":            c.id,
                    "tipo":                 c.estado_aplica,
                    "nombre_alerta":        c.nombre,
                    "dias_limite":          c.dias_limite,
                    "dias_en_estado":       dias_en_estado,
                    "orden_id":             o.id,
                    "op":                   o.op,
                    "descripcion_producto": o.descripcion_producto,
                    "estado_orden":         o.estado,
                })

    return {"total": len(alertas), "alertas": alertas}
