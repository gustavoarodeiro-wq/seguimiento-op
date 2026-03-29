from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from database import get_db, EtapaMaestro, AreaProduccion, EquipoProduccion, EtapaProduccion, EtapaProducto, ProductoTerminado
from routers.auth import require_auth

router = APIRouter()


def _solo_admin(user):
    if user["rol"] != "admin":
        raise HTTPException(status_code=403, detail="Solo administradores.")


# ── Etapas ─────────────────────────────────────────────────────────────────────

@router.get("/api/etapas-maestro")
async def list_etapas(db: Session = Depends(get_db), user: dict = Depends(require_auth)):
    items = db.query(EtapaMaestro).order_by(EtapaMaestro.nombre).all()
    return [
        {
            "id": e.id,
            "nombre": e.nombre,
            "activo": e.activo,
            "n_areas": len(e.areas),
        }
        for e in items
    ]


@router.post("/api/etapas-maestro")
async def create_etapa(request: Request, db: Session = Depends(get_db), user: dict = Depends(require_auth)):
    _solo_admin(user)
    body = await request.json()
    nombre = body.get("nombre", "").strip()
    if not nombre:
        raise HTTPException(status_code=422, detail="El nombre es obligatorio.")
    if db.query(EtapaMaestro).filter(EtapaMaestro.nombre == nombre).first():
        raise HTTPException(status_code=409, detail=f"Ya existe una etapa con el nombre '{nombre}'.")
    item = EtapaMaestro(nombre=nombre, activo=True)
    db.add(item)
    db.commit()
    db.refresh(item)
    return {"id": item.id, "nombre": item.nombre, "activo": item.activo, "n_areas": 0}


@router.put("/api/etapas-maestro/{etapa_id}")
async def update_etapa(etapa_id: int, request: Request, db: Session = Depends(get_db), user: dict = Depends(require_auth)):
    _solo_admin(user)
    item = db.query(EtapaMaestro).filter(EtapaMaestro.id == etapa_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Etapa no encontrada.")
    body = await request.json()
    nombre = body.get("nombre", "").strip()
    if not nombre:
        raise HTTPException(status_code=422, detail="El nombre es obligatorio.")
    existe = db.query(EtapaMaestro).filter(EtapaMaestro.nombre == nombre, EtapaMaestro.id != etapa_id).first()
    if existe:
        raise HTTPException(status_code=409, detail=f"Ya existe una etapa con el nombre '{nombre}'.")
    item.nombre = nombre
    db.commit()
    return {"id": item.id, "nombre": item.nombre, "activo": item.activo, "n_areas": len(item.areas)}


@router.patch("/api/etapas-maestro/{etapa_id}/toggle")
async def toggle_etapa(etapa_id: int, db: Session = Depends(get_db), user: dict = Depends(require_auth)):
    _solo_admin(user)
    item = db.query(EtapaMaestro).filter(EtapaMaestro.id == etapa_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Etapa no encontrada.")
    item.activo = not item.activo
    db.commit()
    return {"id": item.id, "activo": item.activo}


@router.delete("/api/etapas-maestro/{etapa_id}")
async def delete_etapa(etapa_id: int, db: Session = Depends(get_db), user: dict = Depends(require_auth)):
    _solo_admin(user)
    item = db.query(EtapaMaestro).filter(EtapaMaestro.id == etapa_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Etapa no encontrada.")
    if item.areas:
        raise HTTPException(status_code=409, detail="No se puede eliminar: tiene áreas asociadas.")
    db.delete(item)
    db.commit()
    return {"ok": True}


# ── Áreas ──────────────────────────────────────────────────────────────────────

@router.get("/api/etapas-maestro/{etapa_id}/areas")
async def list_areas(etapa_id: int, db: Session = Depends(get_db), user: dict = Depends(require_auth)):
    items = db.query(AreaProduccion).filter(AreaProduccion.etapa_id == etapa_id).order_by(AreaProduccion.nombre).all()
    return [
        {
            "id": a.id,
            "nombre": a.nombre,
            "activo": a.activo,
            "n_equipos": len(a.equipos),
        }
        for a in items
    ]


@router.post("/api/etapas-maestro/{etapa_id}/areas")
async def create_area(etapa_id: int, request: Request, db: Session = Depends(get_db), user: dict = Depends(require_auth)):
    _solo_admin(user)
    if not db.query(EtapaMaestro).filter(EtapaMaestro.id == etapa_id).first():
        raise HTTPException(status_code=404, detail="Etapa no encontrada.")
    body = await request.json()
    nombre = body.get("nombre", "").strip()
    if not nombre:
        raise HTTPException(status_code=422, detail="El nombre es obligatorio.")
    item = AreaProduccion(etapa_id=etapa_id, nombre=nombre, activo=True)
    db.add(item)
    db.commit()
    db.refresh(item)
    return {"id": item.id, "nombre": item.nombre, "activo": item.activo, "n_equipos": 0}


@router.put("/api/areas-produccion/{area_id}")
async def update_area(area_id: int, request: Request, db: Session = Depends(get_db), user: dict = Depends(require_auth)):
    _solo_admin(user)
    item = db.query(AreaProduccion).filter(AreaProduccion.id == area_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Área no encontrada.")
    body = await request.json()
    nombre = body.get("nombre", "").strip()
    if not nombre:
        raise HTTPException(status_code=422, detail="El nombre es obligatorio.")
    item.nombre = nombre
    db.commit()
    return {"id": item.id, "nombre": item.nombre, "activo": item.activo, "n_equipos": len(item.equipos)}


@router.patch("/api/areas-produccion/{area_id}/toggle")
async def toggle_area(area_id: int, db: Session = Depends(get_db), user: dict = Depends(require_auth)):
    _solo_admin(user)
    item = db.query(AreaProduccion).filter(AreaProduccion.id == area_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Área no encontrada.")
    item.activo = not item.activo
    db.commit()
    return {"id": item.id, "activo": item.activo}


@router.delete("/api/areas-produccion/{area_id}")
async def delete_area(area_id: int, db: Session = Depends(get_db), user: dict = Depends(require_auth)):
    _solo_admin(user)
    item = db.query(AreaProduccion).filter(AreaProduccion.id == area_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Área no encontrada.")
    if item.equipos:
        raise HTTPException(status_code=409, detail="No se puede eliminar: tiene equipos asociados.")
    db.delete(item)
    db.commit()
    return {"ok": True}


# ── Equipos ────────────────────────────────────────────────────────────────────

@router.get("/api/areas-produccion/{area_id}/equipos")
async def list_equipos(area_id: int, db: Session = Depends(get_db), user: dict = Depends(require_auth)):
    items = db.query(EquipoProduccion).filter(EquipoProduccion.area_id == area_id).order_by(EquipoProduccion.nombre).all()
    return [{"id": e.id, "nombre": e.nombre, "activo": e.activo} for e in items]


@router.post("/api/areas-produccion/{area_id}/equipos")
async def create_equipo(area_id: int, request: Request, db: Session = Depends(get_db), user: dict = Depends(require_auth)):
    _solo_admin(user)
    if not db.query(AreaProduccion).filter(AreaProduccion.id == area_id).first():
        raise HTTPException(status_code=404, detail="Área no encontrada.")
    body = await request.json()
    nombre = body.get("nombre", "").strip()
    if not nombre:
        raise HTTPException(status_code=422, detail="El nombre es obligatorio.")
    item = EquipoProduccion(area_id=area_id, nombre=nombre, activo=True)
    db.add(item)
    db.commit()
    db.refresh(item)
    return {"id": item.id, "nombre": item.nombre, "activo": item.activo}


@router.put("/api/equipos-produccion/{equipo_id}")
async def update_equipo(equipo_id: int, request: Request, db: Session = Depends(get_db), user: dict = Depends(require_auth)):
    _solo_admin(user)
    item = db.query(EquipoProduccion).filter(EquipoProduccion.id == equipo_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Equipo no encontrado.")
    body = await request.json()
    nombre = body.get("nombre", "").strip()
    if not nombre:
        raise HTTPException(status_code=422, detail="El nombre es obligatorio.")
    item.nombre = nombre
    db.commit()
    return {"id": item.id, "nombre": item.nombre, "activo": item.activo}


@router.patch("/api/equipos-produccion/{equipo_id}/toggle")
async def toggle_equipo(equipo_id: int, db: Session = Depends(get_db), user: dict = Depends(require_auth)):
    _solo_admin(user)
    item = db.query(EquipoProduccion).filter(EquipoProduccion.id == equipo_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Equipo no encontrado.")
    item.activo = not item.activo
    db.commit()
    return {"id": item.id, "activo": item.activo}


@router.delete("/api/equipos-produccion/{equipo_id}")
async def delete_equipo(equipo_id: int, db: Session = Depends(get_db), user: dict = Depends(require_auth)):
    _solo_admin(user)
    item = db.query(EquipoProduccion).filter(EquipoProduccion.id == equipo_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Equipo no encontrado.")
    db.delete(item)
    db.commit()
    return {"ok": True}


# ── Áreas asignadas a una EtapaProduccion ──────────────────────────────────────

@router.get("/api/etapas-produccion/{etapa_id}/areas")
async def get_areas_etapa(etapa_id: int, db: Session = Depends(get_db), user: dict = Depends(require_auth)):
    """Devuelve áreas asignadas y disponibles para una etapa de forma farmacéutica."""
    etapa = db.query(EtapaProduccion).filter(EtapaProduccion.id == etapa_id).first()
    if not etapa:
        raise HTTPException(status_code=404, detail="Etapa no encontrada.")
    maestro = db.query(EtapaMaestro).filter(EtapaMaestro.nombre == etapa.nombre).first()
    disponibles = []
    if maestro:
        disponibles = [
            {"id": a.id, "nombre": a.nombre, "activo": a.activo}
            for a in sorted(maestro.areas, key=lambda x: x.nombre)
        ]
    asignadas = [a.id for a in etapa.areas]
    return {"disponibles": disponibles, "asignadas": asignadas}


@router.put("/api/etapas-produccion/{etapa_id}/areas")
async def set_areas_etapa(etapa_id: int, request: Request, db: Session = Depends(get_db), user: dict = Depends(require_auth)):
    """Guarda las áreas seleccionadas para una etapa de forma farmacéutica."""
    _solo_admin(user)
    etapa = db.query(EtapaProduccion).filter(EtapaProduccion.id == etapa_id).first()
    if not etapa:
        raise HTTPException(status_code=404, detail="Etapa no encontrada.")
    body = await request.json()
    area_ids = body.get("area_ids", [])
    areas = db.query(AreaProduccion).filter(AreaProduccion.id.in_(area_ids)).all()
    etapa.areas = areas
    db.commit()
    return {"etapa_id": etapa_id, "asignadas": [a.id for a in etapa.areas]}


# ── EtapaProducto ──────────────────────────────────────────────────────────────

def _etapa_producto_dict(e: EtapaProducto):
    return {
        "id": e.id, "orden": e.orden, "nombre": e.nombre, "activo": e.activo,
        "areas": [{"id": a.id, "nombre": a.nombre, "activo": a.activo} for a in e.areas],
    }


@router.get("/api/productos/{producto_id}/etapas")
async def list_etapas_producto(producto_id: int, db: Session = Depends(get_db), user: dict = Depends(require_auth)):
    etapas = (db.query(EtapaProducto)
              .filter(EtapaProducto.producto_id == producto_id)
              .order_by(EtapaProducto.orden)
              .all())
    return [_etapa_producto_dict(e) for e in etapas]


@router.post("/api/productos/{producto_id}/etapas")
async def create_etapa_producto(producto_id: int, request: Request, db: Session = Depends(get_db), user: dict = Depends(require_auth)):
    _solo_admin(user)
    body = await request.json()
    nombre = body.get("nombre", "").strip()
    if not nombre:
        raise HTTPException(status_code=422, detail="El nombre es obligatorio.")
    ultimo = (db.query(EtapaProducto)
              .filter(EtapaProducto.producto_id == producto_id)
              .order_by(EtapaProducto.orden.desc()).first())
    orden = (ultimo.orden + 1) if ultimo else 1
    e = EtapaProducto(producto_id=producto_id, orden=orden, nombre=nombre, activo=True)
    db.add(e)
    db.commit()
    db.refresh(e)
    return _etapa_producto_dict(e)


@router.put("/api/etapas-producto/{etapa_id}")
async def update_etapa_producto(etapa_id: int, request: Request, db: Session = Depends(get_db), user: dict = Depends(require_auth)):
    _solo_admin(user)
    e = db.query(EtapaProducto).filter(EtapaProducto.id == etapa_id).first()
    if not e:
        raise HTTPException(status_code=404, detail="Etapa no encontrada.")
    body = await request.json()
    nombre = body.get("nombre", "").strip()
    if not nombre:
        raise HTTPException(status_code=422, detail="El nombre es obligatorio.")
    e.nombre = nombre
    db.commit()
    return _etapa_producto_dict(e)


@router.patch("/api/etapas-producto/{etapa_id}/toggle")
async def toggle_etapa_producto(etapa_id: int, db: Session = Depends(get_db), user: dict = Depends(require_auth)):
    _solo_admin(user)
    e = db.query(EtapaProducto).filter(EtapaProducto.id == etapa_id).first()
    if not e:
        raise HTTPException(status_code=404, detail="Etapa no encontrada.")
    e.activo = not e.activo
    db.commit()
    return {"id": e.id, "activo": e.activo}


@router.delete("/api/etapas-producto/{etapa_id}")
async def delete_etapa_producto(etapa_id: int, db: Session = Depends(get_db), user: dict = Depends(require_auth)):
    _solo_admin(user)
    e = db.query(EtapaProducto).filter(EtapaProducto.id == etapa_id).first()
    if not e:
        raise HTTPException(status_code=404, detail="Etapa no encontrada.")
    db.delete(e)
    db.commit()
    return {"ok": True}


@router.get("/api/etapas-producto/{etapa_id}/areas-disponibles")
async def areas_disponibles_etapa_producto(etapa_id: int, db: Session = Depends(get_db), user: dict = Depends(require_auth)):
    """Áreas del maestro que corresponden al nombre de esta etapa."""
    e = db.query(EtapaProducto).filter(EtapaProducto.id == etapa_id).first()
    if not e:
        raise HTTPException(status_code=404, detail="Etapa no encontrada.")
    maestro = db.query(EtapaMaestro).filter(EtapaMaestro.nombre == e.nombre).first()
    disponibles = []
    if maestro:
        disponibles = [{"id": a.id, "nombre": a.nombre, "activo": a.activo}
                       for a in sorted(maestro.areas, key=lambda x: x.nombre)]
    asignadas = [a.id for a in e.areas]
    return {"disponibles": disponibles, "asignadas": asignadas}


@router.put("/api/etapas-producto/{etapa_id}/areas")
async def set_areas_etapa_producto(etapa_id: int, request: Request, db: Session = Depends(get_db), user: dict = Depends(require_auth)):
    _solo_admin(user)
    e = db.query(EtapaProducto).filter(EtapaProducto.id == etapa_id).first()
    if not e:
        raise HTTPException(status_code=404, detail="Etapa no encontrada.")
    body = await request.json()
    area_ids = body.get("area_ids", [])
    e.areas = db.query(AreaProduccion).filter(AreaProduccion.id.in_(area_ids)).all()
    db.commit()
    return {"etapa_id": etapa_id, "asignadas": [a.id for a in e.areas]}
