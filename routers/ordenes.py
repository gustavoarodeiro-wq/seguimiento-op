from fastapi import APIRouter, Request, Form, Depends, Query, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import func, or_, case
from datetime import datetime, date
from typing import Optional

from database import (
    get_db, Orden, HistorialEstado, Faltante, Entrega,
    ProductoTerminado, TipoFaltante, Usuario,
    EtapaOrden, EtapaProduccion, FormaFarmaceutica,
)
from routers.auth import require_auth, get_current_user

router = APIRouter()
templates = Jinja2Templates(directory="templates")
templates.env.cache = None  # workaround Python 3.14+
templates.env.filters["fmt_unidad"] = lambda u: {"KG": "Kg", "G": "g", "ML": "mL", "UN": "UN", "L": "L"}.get(str(u), str(u))

# Helpers de permiso — leen user["permisos"] calculado al login
def _puede(user: dict, permiso: str) -> bool:
    return bool(user.get("permisos", {}).get(permiso, False))

def _exigir(user: dict, permiso: str):
    if not _puede(user, permiso):
        raise HTTPException(status_code=403, detail="Sin permisos.")

ESTADOS_VALIDOS = [
    "revisar", "faltante", "para_emitir", "emitido", "en_proceso",
    "terminada", "entregada", "cancelada"
]

TRANSICIONES = {
    "revisar":     ["para_emitir", "cancelada"],
    "faltante":    ["para_emitir", "revisar", "cancelada"],
    "para_emitir": ["emitido", "revisar", "cancelada"],
    "emitido":     ["en_proceso", "cancelada"],
    "en_proceso":  ["terminada", "cancelada"],
    "terminada":   ["entregada"],
    "entregada":   [],
    "cancelada":   [],
}


# ── API: stats para dashboard ──────────────────────────────────────────────────

@router.get("/api/stats")
async def api_stats(
    request: Request,
    db: Session = Depends(get_db),
    user: dict = Depends(require_auth),
):
    from datetime import date
    from sqlalchemy import extract
    conteos = dict(
        db.query(Orden.estado, func.count(Orden.id))
        .group_by(Orden.estado)
        .all()
    )
    hoy = date.today()
    q_mes = (
        db.query(func.count(Entrega.id), func.sum(Entrega.cantidad_entregada))
        .filter(
            extract('month', Entrega.fecha_entrega) == hoy.month,
            extract('year',  Entrega.fecha_entrega) == hoy.year,
        )
        .one()
    )
    entregas_mes  = q_mes[0] or 0
    unidades_mes  = int(q_mes[1] or 0)
    return {
        "revisar":      conteos.get("revisar",     0),
        "faltante":     conteos.get("faltante",    0),
        "para_emitir":  conteos.get("para_emitir", 0),
        "en_proceso":   conteos.get("en_proceso",  0),
        "terminada":    conteos.get("terminada",   0),
        "entregada":    conteos.get("entregada",   0),
        "cancelada":    conteos.get("cancelada",   0),
        "entregas_mes": entregas_mes,
        "unidades_mes": unidades_mes,
    }


# ── API: listado global de entregas ───────────────────────────────────────────

@router.get("/api/entregas")
async def api_listar_entregas(
    request: Request,
    q: str = None,
    fecha_desde: str = None,
    fecha_hasta: str = None,
    tipo: str = None,          # 'final' | 'parcial'
    forma: str = None,         # nombre forma farmacéutica
    mes: int = None,
    anio: int = None,
    limit: int = 500,
    db: Session = Depends(get_db),
    user: dict = Depends(require_auth),
):
    from datetime import date, datetime as dt
    from sqlalchemy import extract, or_

    query = (
        db.query(Entrega, Orden)
        .join(Orden, Entrega.orden_id == Orden.id)
    )

    # Filtro mes/año (para el modal del dashboard)
    if mes and anio:
        query = query.filter(
            extract('month', Entrega.fecha_entrega) == mes,
            extract('year',  Entrega.fecha_entrega) == anio,
        )

    # Búsqueda general
    if q:
        q_like = f"%{q}%"
        query = query.filter(or_(
            Orden.op.ilike(q_like),
            Orden.descripcion_producto.ilike(q_like),
            Orden.lote_pt.ilike(q_like),
            Entrega.remito.ilike(q_like),
        ))

    if fecha_desde:
        query = query.filter(Entrega.fecha_entrega >= dt.fromisoformat(fecha_desde))
    if fecha_hasta:
        query = query.filter(Entrega.fecha_entrega <= dt.fromisoformat(fecha_hasta + "T23:59:59"))
    if tipo == 'final':
        query = query.filter(Entrega.es_entrega_final == True)
    elif tipo == 'parcial':
        query = query.filter(Entrega.es_entrega_final == False)

    # Filtro por forma farmacéutica (subconsulta para evitar conflicto con joins existentes)
    if forma:
        orden_ids_forma = (
            db.query(Orden.id)
            .join(ProductoTerminado, ProductoTerminado.codigo == Orden.codigo_producto)
            .join(FormaFarmaceutica, FormaFarmaceutica.id == ProductoTerminado.forma_farmaceutica_id)
            .filter(FormaFarmaceutica.nombre == forma)
            .subquery()
        )
        query = query.filter(Entrega.orden_id.in_(orden_ids_forma))

    rows = query.order_by(Entrega.fecha_entrega.desc()).limit(limit).all()

    # Desglose por forma farmacéutica (sobre la misma query base con mes/anio si aplica)
    ff_query = (
        db.query(
            FormaFarmaceutica.nombre.label('forma'),
            func.sum(Entrega.cantidad_entregada).label('unidades'),
            func.count(Entrega.id).label('entregas'),
        )
        .join(Orden, Entrega.orden_id == Orden.id)
        .join(ProductoTerminado, ProductoTerminado.codigo == Orden.codigo_producto)
        .join(FormaFarmaceutica, FormaFarmaceutica.id == ProductoTerminado.forma_farmaceutica_id)
    )
    if mes and anio:
        ff_query = ff_query.filter(
            extract('month', Entrega.fecha_entrega) == mes,
            extract('year',  Entrega.fecha_entrega) == anio,
        )
    ff_raw = (
        ff_query
        .group_by(FormaFarmaceutica.nombre)
        .order_by(func.sum(Entrega.cantidad_entregada).desc())
        .all()
    )

    entregas_lista = [
        {
            "id":                  e.id,
            "fecha_entrega":       _fmt(e.fecha_entrega),
            "orden_id":            e.orden_id,
            "op":                  o.op,
            "descripcion_producto":o.descripcion_producto,
            "lote_pt":             o.lote_pt,
            "cantidad_entregada":  e.cantidad_entregada,
            "muestras_control":    e.muestras_control,
            "remito":              e.remito,
            "es_entrega_final":    e.es_entrega_final,
        }
        for e, o in rows
    ]

    return {
        "total": len(entregas_lista),
        "entregas": entregas_lista,
        "por_forma": [
            {"forma": r.forma, "unidades": int(r.unidades or 0), "entregas": r.entregas}
            for r in ff_raw
        ],
        "resumen": {
            "total_entregas": len(entregas_lista),
            "total_unidades": sum(e["cantidad_entregada"] or 0 for e in entregas_lista),
        },
    }


# ── API: listado de órdenes (JSON) ─────────────────────────────────────────────

@router.get("/api/ordenes")
async def api_ordenes(
    request: Request,
    db: Session = Depends(get_db),
    user: dict = Depends(require_auth),
    estado: Optional[str] = Query(None),
    q: Optional[str] = Query(None),
    op: Optional[str] = Query(None),
    codigo: Optional[str] = Query(None),
    fecha_desde: Optional[str] = Query(None),
    fecha_hasta: Optional[str] = Query(None),
    limit: int = Query(2000, le=5000),
    offset: int = Query(0),
):
    query = db.query(Orden)

    if estado and estado in ESTADOS_VALIDOS:
        query = query.filter(Orden.estado == estado)

    if q:
        term = f"%{q}%"
        query = query.filter(or_(
            Orden.op.ilike(term),
            Orden.descripcion_producto.ilike(term),
            Orden.codigo_producto.ilike(term),
            Orden.lote_pt.ilike(term),
            Orden.lote_granel.ilike(term),
        ))

    if op:
        query = query.filter(Orden.op.ilike(f"%{op}%"))

    if codigo:
        query = query.filter(Orden.codigo_producto.ilike(f"%{codigo}%"))

    if fecha_desde:
        try:
            query = query.filter(Orden.fecha_carga >= datetime.fromisoformat(fecha_desde))
        except ValueError:
            pass

    if fecha_hasta:
        try:
            hasta = datetime.fromisoformat(fecha_hasta).replace(hour=23, minute=59, second=59)
            query = query.filter(Orden.fecha_carga <= hasta)
        except ValueError:
            pass

    total = query.count()
    ordenes = (query
               .order_by(
                   case((Orden.op == None, 1), else_=0),
                   Orden.op.asc(),
                   Orden.fecha_carga.desc(),
               )
               .offset(offset).limit(limit).all())

    # Nombres de usuarios creadores
    user_ids = {o.creado_por for o in ordenes if o.creado_por}
    nombres = {}
    if user_ids:
        nombres = {u.id: u.nombre for u in
                   db.query(Usuario).filter(Usuario.id.in_(user_ids)).all()}

    return {
        "total": total,
        "items": [_orden_dict(o, nombres.get(o.creado_por)) for o in ordenes],
    }


# ── API: detalle de una orden ──────────────────────────────────────────────────

@router.get("/api/ordenes/{orden_id}")
async def api_orden_detalle(
    orden_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: dict = Depends(require_auth),
):
    orden = _get_or_404(db, orden_id)
    historial = (
        db.query(HistorialEstado)
        .filter(HistorialEstado.orden_id == orden_id)
        .order_by(HistorialEstado.fecha.desc())
        .all()
    )
    faltantes = (
        db.query(Faltante)
        .filter(Faltante.orden_id == orden_id)
        .order_by(Faltante.fecha_registro.desc())
        .all()
    )
    entregas = (
        db.query(Entrega)
        .filter(Entrega.orden_id == orden_id)
        .order_by(Entrega.fecha_entrega.asc())
        .all()
    )
    etapas_orden = (
        db.query(EtapaOrden)
        .filter(EtapaOrden.orden_id == orden_id)
        .join(EtapaOrden.etapa)
        .order_by(EtapaProduccion.orden, EtapaOrden.id)
        .all()
    )
    etapa_user_ids = {e.usuario_inicio_id for e in etapas_orden if e.usuario_inicio_id}
    user_ids = {h.usuario_id for h in historial if h.usuario_id} | etapa_user_ids
    usuarios = {u.id: u.nombre for u in db.query(Usuario).filter(Usuario.id.in_(user_ids)).all()}

    from collections import defaultdict
    iter_count = defaultdict(int)
    etapas_lista = []
    for e in etapas_orden:
        iter_count[e.etapa_produccion_id] += 1
        etapas_lista.append({
            "id":           e.id,
            "nombre":       e.etapa.nombre,
            "iteracion":    iter_count[e.etapa_produccion_id],
            "fecha_inicio": _fmt(e.fecha_inicio),
            "fecha_fin":    _fmt(e.fecha_fin),
            "usuario":      usuarios.get(e.usuario_inicio_id),
        })

    return {
        **_orden_dict(orden),
        "historial":  [_historial_dict(h, usuarios) for h in historial],
        "faltantes":  [_faltante_dict(f) for f in faltantes],
        "entregas":   [_entrega_dict(e) for e in entregas],
        "etapas":     etapas_lista,
        "transiciones_posibles": TRANSICIONES.get(orden.estado, []),
    }


# ── API: cambio de estado ──────────────────────────────────────────────────────

@router.patch("/api/ordenes/{orden_id}/datos")
async def api_actualizar_datos(
    orden_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: dict = Depends(require_auth),
):
    """Actualiza lote granel, lote PT y vencimiento (MM/AAAA) de una orden."""
    _exigir(user, "editar_datos_orden")

    orden = _get_or_404(db, orden_id)
    body  = await request.json()

    if "op" in body:
        orden.op = body["op"].strip() or None
    if "lote_granel" in body:
        orden.lote_granel = body["lote_granel"].strip() or None
    if "lote_pt" in body:
        orden.lote_pt = body["lote_pt"].strip() or None
    if "fecha_vencimiento" in body:
        raw = body["fecha_vencimiento"].strip()
        if raw:
            parsed = _parse_mes_anio(raw)
            if parsed is None:
                raise HTTPException(status_code=422, detail="Vencimiento inválido. Usá el formato MM/AAAA (ej: 06/2026).")
            orden.fecha_vencimiento = parsed
        else:
            orden.fecha_vencimiento = None

    orden.ultima_modificacion_por   = user["id"]
    orden.ultima_modificacion_fecha = datetime.utcnow()
    db.commit()
    return _orden_dict(orden)


def _parse_mes_anio(valor: str):
    """Convierte 'MM/AAAA' a date(AAAA, MM, 1). Devuelve None si es inválido."""
    if not valor:
        return None
    try:
        partes = valor.split("/")
        if len(partes) == 2:
            mes, anio = int(partes[0]), int(partes[1])
            if 1 <= mes <= 12 and 1900 <= anio <= 2100:
                return date(anio, mes, 1)
    except (ValueError, TypeError):
        pass
    return None


@router.post("/api/ordenes/{orden_id}/estado")
async def api_cambiar_estado(
    orden_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: dict = Depends(require_auth),
):
    _exigir(user, "cambiar_estado")
    body = await request.json()
    nuevo_estado   = body.get("estado", "")
    subestado      = body.get("subestado") or None
    observaciones  = body.get("observaciones") or None
    cantidad_obt   = body.get("cantidad_obtenida")

    orden = _get_or_404(db, orden_id)

    if nuevo_estado not in TRANSICIONES.get(orden.estado, []):
        raise HTTPException(
            status_code=422,
            detail=f"No se puede pasar de '{orden.estado}' a '{nuevo_estado}'.",
        )

    # Registrar historial
    hist = HistorialEstado(
        orden_id=orden_id,
        estado_anterior=orden.estado,
        estado_nuevo=nuevo_estado,
        subestado_anterior=orden.subestado,
        subestado_nuevo=subestado,
        usuario_id=user["id"],
        fecha=datetime.utcnow(),
        observaciones=observaciones,
    )
    db.add(hist)

    # Actualizar orden
    orden.estado = nuevo_estado
    orden.subestado = subestado
    orden.ultima_modificacion_por = user["id"]
    orden.ultima_modificacion_fecha = datetime.utcnow()

    if nuevo_estado == "en_proceso" and not orden.fecha_inicio_produccion:
        orden.fecha_inicio_produccion = datetime.utcnow()
        # Auto-crear etapas de la orden desde la forma farmacéutica del producto
        ya_creadas = db.query(EtapaOrden).filter(EtapaOrden.orden_id == orden_id).count()
        if ya_creadas == 0:
            pt = db.query(ProductoTerminado).filter(
                ProductoTerminado.codigo == orden.codigo_producto
            ).first()
            if pt and pt.forma_farmaceutica_id:
                etapas = db.query(EtapaProduccion).filter(
                    EtapaProduccion.forma_farmaceutica_id == pt.forma_farmaceutica_id,
                    EtapaProduccion.activo == True,
                ).order_by(EtapaProduccion.orden).all()
                for e in etapas:
                    db.add(EtapaOrden(orden_id=orden_id, etapa_produccion_id=e.id))

    if nuevo_estado == "terminada":
        orden.fecha_terminado = datetime.utcnow()
        if cantidad_obt is not None:
            orden.cantidad_obtenida = float(cantidad_obt)
            if orden.cantidad and orden.cantidad > 0:
                orden.rendimiento = round(orden.cantidad_obtenida / orden.cantidad * 100, 2)

    db.commit()
    return {"ok": True, "estado": nuevo_estado}


# ── API: listado global de faltantes activos ──────────────────────────────────

@router.get("/api/faltantes")
async def api_faltantes_activos(
    request: Request,
    db: Session = Depends(get_db),
    user: dict = Depends(require_auth),
    q: str = "",
    tipo: str = "",
):
    query = (
        db.query(Faltante, Orden)
        .join(Orden, Orden.id == Faltante.orden_id)
        .filter(Faltante.resuelto == False)
    )
    if tipo in ("MP", "ME"):
        query = query.filter(Faltante.tipo == TipoFaltante(tipo))
    if q:
        q_like = f"%{q}%"
        query = query.filter(
            (Faltante.codigo.ilike(q_like)) |
            (Faltante.descripcion.ilike(q_like)) |
            (Orden.op.ilike(q_like)) |
            (Orden.descripcion_producto.ilike(q_like))
        )
    rows = query.order_by(Faltante.fecha_registro.asc()).all()
    resultado = []
    for f, o in rows:
        resultado.append({
            "id":                f.id,
            "tipo":              f.tipo.value,
            "codigo":            f.codigo,
            "descripcion":       f.descripcion,
            "observacion":       f.observacion,
            "fecha_registro":    _fmt(f.fecha_registro),
            "orden_id":          o.id,
            "op":                o.op,
            "descripcion_producto": o.descripcion_producto,
            "estado_orden":      o.estado,
        })
    return {"total": len(resultado), "faltantes": resultado}


# ── API: agregar faltante ──────────────────────────────────────────────────────

@router.post("/api/ordenes/{orden_id}/faltantes")
async def api_agregar_faltante(
    orden_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: dict = Depends(require_auth),
):
    _exigir(user, "agregar_faltante")
    orden = _get_or_404(db, orden_id)
    body = await request.json()

    tipo = body.get("tipo", "MP")
    if tipo not in ("MP", "ME"):
        raise HTTPException(status_code=422, detail="tipo debe ser MP o ME.")

    faltante = Faltante(
        orden_id=orden_id,
        tipo=TipoFaltante(tipo),
        item_id=body.get("item_id"),
        codigo=body.get("codigo", ""),
        descripcion=body.get("descripcion", ""),
        observacion=body.get("observacion"),
        resuelto=False,
        fecha_registro=datetime.utcnow(),
    )
    db.add(faltante)

    # Auto-transición REVISAR → FALTANTE al registrar el primer faltante
    if orden.estado == "revisar":
        db.add(HistorialEstado(
            orden_id=orden_id,
            estado_anterior="revisar",
            estado_nuevo="faltante",
            usuario_id=user["id"],
            fecha=datetime.utcnow(),
            observaciones="Faltante registrado durante revisión.",
        ))
        orden.estado = "faltante"
        orden.ultima_modificacion_por = user["id"]
        orden.ultima_modificacion_fecha = datetime.utcnow()

    db.commit()
    db.refresh(faltante)

    pendientes = db.query(func.count(Faltante.id)).filter(
        Faltante.orden_id == orden_id, Faltante.resuelto == False
    ).scalar()
    return {**_faltante_dict(faltante), "estado_orden": orden.estado, "faltantes_pendientes": pendientes}


@router.patch("/api/faltantes/{faltante_id}/observacion")
async def api_obs_faltante(
    faltante_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: dict = Depends(require_auth),
):
    _exigir(user, "agregar_faltante")
    faltante = db.query(Faltante).filter(Faltante.id == faltante_id).first()
    if not faltante:
        raise HTTPException(status_code=404, detail="Faltante no encontrado.")
    body = await request.json()
    faltante.observacion = body.get("observacion") or None
    db.commit()
    return {"ok": True, "observacion": faltante.observacion}


@router.patch("/api/faltantes/{faltante_id}/resolver")
async def api_resolver_faltante(
    faltante_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: dict = Depends(require_auth),
):
    _exigir(user, "agregar_faltante")
    faltante = db.query(Faltante).filter(Faltante.id == faltante_id).first()
    if not faltante:
        raise HTTPException(status_code=404, detail="Faltante no encontrado.")
    faltante.resuelto = True
    faltante.fecha_resolucion = datetime.utcnow()
    db.commit()

    pendientes = db.query(func.count(Faltante.id)).filter(
        Faltante.orden_id == faltante.orden_id, Faltante.resuelto == False
    ).scalar()
    return {"ok": True, "faltantes_pendientes": pendientes}


# ── API: registrar entrega ─────────────────────────────────────────────────────

@router.post("/api/ordenes/{orden_id}/entregas")
async def api_registrar_entrega(
    orden_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: dict = Depends(require_auth),
):
    _exigir(user, "registrar_entrega")
    orden = _get_or_404(db, orden_id)
    body = await request.json()

    muestras = float(body["muestras_control"]) if body.get("muestras_control") else None

    entrega = Entrega(
        orden_id=orden_id,
        fecha_entrega=datetime.utcnow(),
        cantidad_entregada=round(float(body.get("cantidad_entregada", 0))),
        muestras_control=muestras,
        remito=body.get("remito"),
        es_entrega_final=bool(body.get("es_entrega_final", False)),
        usuario_id=user["id"],
    )
    db.add(entrega)
    db.flush()  # para incluir esta entrega en el cálculo

    # cantidad_obtenida = sum(entregas) + sum(muestras por entrega)
    from sqlalchemy import func as sqlfunc
    total_entregado = db.query(sqlfunc.sum(Entrega.cantidad_entregada)).filter(
        Entrega.orden_id == orden_id
    ).scalar() or 0
    total_muestras = db.query(sqlfunc.sum(Entrega.muestras_control)).filter(
        Entrega.orden_id == orden_id
    ).scalar() or 0
    cantidad_obtenida = total_entregado + total_muestras
    orden.cantidad_obtenida = round(cantidad_obtenida)
    orden.muestras_control = round(total_muestras) if total_muestras else None
    if orden.cantidad and orden.cantidad > 0:
        orden.rendimiento = round(cantidad_obtenida / orden.cantidad * 100, 2)

    if entrega.es_entrega_final and orden.estado in ("terminada", "en_proceso"):
        db.add(HistorialEstado(
            orden_id=orden_id,
            estado_anterior=orden.estado,
            estado_nuevo="entregada",
            usuario_id=user["id"],
            fecha=datetime.utcnow(),
            observaciones=f"Entrega final. Remito: {entrega.remito or '—'}",
        ))
        orden.estado = "entregada"
        orden.ultima_modificacion_por = user["id"]
        orden.ultima_modificacion_fecha = datetime.utcnow()

    db.commit()
    db.refresh(entrega)
    return _entrega_dict(entrega)


# ── API: editar entrega ───────────────────────────────────────────────────────

@router.patch("/api/entregas/{entrega_id}")
async def api_editar_entrega(
    entrega_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: dict = Depends(require_auth),
):
    _exigir(user, "registrar_entrega")
    entrega = db.query(Entrega).filter(Entrega.id == entrega_id).first()
    if not entrega:
        raise HTTPException(status_code=404, detail="Entrega no encontrada.")

    body = await request.json()
    orden = _get_or_404(db, entrega.orden_id)
    cambios = []

    if "cantidad_entregada" in body:
        nueva = round(float(body["cantidad_entregada"]))
        if nueva != entrega.cantidad_entregada:
            cambios.append(f"Cantidad: {int(entrega.cantidad_entregada)} → {nueva}")
            entrega.cantidad_entregada = nueva
    if "muestras_control" in body:
        nueva_m = float(body["muestras_control"]) if body["muestras_control"] else None
        ant_m = entrega.muestras_control
        if nueva_m != ant_m:
            cambios.append(f"Muestras CC: {int(ant_m or 0)} → {int(nueva_m or 0)}")
            entrega.muestras_control = nueva_m
    if "remito" in body:
        nuevo_r = body["remito"] or None
        if nuevo_r != entrega.remito:
            cambios.append(f"Remito: {entrega.remito or '—'} → {nuevo_r or '—'}")
            entrega.remito = nuevo_r

    if cambios:
        db.flush()
        from sqlalchemy import func as sqlfunc
        total_entregado = db.query(sqlfunc.sum(Entrega.cantidad_entregada)).filter(
            Entrega.orden_id == entrega.orden_id).scalar() or 0
        total_muestras = db.query(sqlfunc.sum(Entrega.muestras_control)).filter(
            Entrega.orden_id == entrega.orden_id).scalar() or 0
        cantidad_obtenida = total_entregado + total_muestras
        orden.cantidad_obtenida = round(cantidad_obtenida)
        orden.muestras_control = round(total_muestras) if total_muestras else None
        if orden.cantidad and orden.cantidad > 0:
            orden.rendimiento = round(cantidad_obtenida / orden.cantidad * 100, 2)
        db.add(HistorialEstado(
            orden_id=entrega.orden_id,
            estado_anterior=orden.estado,
            estado_nuevo=orden.estado,
            usuario_id=user["id"],
            fecha=datetime.utcnow(),
            observaciones="Corrección de entrega: " + "; ".join(cambios),
        ))

    db.commit()
    return _entrega_dict(entrega)


# ── API: etapas de proceso de una orden ───────────────────────────────────────

@router.get("/api/ordenes/{orden_id}/etapas-proceso")
async def api_etapas_proceso(
    orden_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: dict = Depends(require_auth),
):
    orden = _get_or_404(db, orden_id)

    # Creación lazy: si no hay registros aún, crearlos ahora desde la FF del producto
    ya_creadas = db.query(EtapaOrden).filter(EtapaOrden.orden_id == orden_id).count()
    if ya_creadas == 0:
        pt = db.query(ProductoTerminado).filter(
            ProductoTerminado.codigo == orden.codigo_producto
        ).first()
        if pt and pt.forma_farmaceutica_id:
            etapas = db.query(EtapaProduccion).filter(
                EtapaProduccion.forma_farmaceutica_id == pt.forma_farmaceutica_id,
                EtapaProduccion.activo == True,
            ).order_by(EtapaProduccion.orden).all()
            for e in etapas:
                db.add(EtapaOrden(orden_id=orden_id, etapa_produccion_id=e.id))
            db.commit()

    rows = (
        db.query(EtapaOrden)
        .filter(EtapaOrden.orden_id == orden_id)
        .join(EtapaOrden.etapa)
        .order_by(EtapaProduccion.orden, EtapaOrden.id)
        .all()
    )
    user_ids = {r.usuario_inicio_id for r in rows if r.usuario_inicio_id}
    usuarios = {u.id: u.nombre for u in db.query(Usuario).filter(Usuario.id.in_(user_ids)).all()}

    from collections import defaultdict
    total_por_etapa = defaultdict(int)
    for r in rows:
        total_por_etapa[r.etapa_produccion_id] += 1

    iter_count = defaultdict(int)
    result = []
    for r in rows:
        iter_count[r.etapa_produccion_id] += 1
        iteracion = iter_count[r.etapa_produccion_id]
        total = total_por_etapa[r.etapa_produccion_id]
        es_parcial = bool(r.fecha_fin) and (iteracion < total)
        result.append({
            "id":                  r.id,
            "etapa_produccion_id": r.etapa_produccion_id,
            "iteracion":           iteracion,
            "total_iteraciones":   total,
            "es_parcial":          es_parcial,
            "orden":               r.etapa.orden,
            "nombre":              r.etapa.nombre,
            "fecha_inicio":        _fmt(r.fecha_inicio),
            "fecha_fin":           _fmt(r.fecha_fin),
            "usuario_inicio":      usuarios.get(r.usuario_inicio_id, None),
        })
    return result


@router.patch("/api/etapas-proceso/{etapa_orden_id}/iniciar")
async def api_iniciar_etapa(
    etapa_orden_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: dict = Depends(require_auth),
):
    _exigir(user, "manejar_etapas")
    row = db.query(EtapaOrden).filter(EtapaOrden.id == etapa_orden_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Etapa no encontrada.")
    row.fecha_inicio = datetime.utcnow()
    row.usuario_inicio_id = user["id"]
    db.commit()
    return {"ok": True}


@router.patch("/api/etapas-proceso/{etapa_orden_id}/completar")
async def api_completar_etapa(
    etapa_orden_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: dict = Depends(require_auth),
):
    _exigir(user, "manejar_etapas")
    row = db.query(EtapaOrden).filter(EtapaOrden.id == etapa_orden_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Etapa no encontrada.")

    try:
        body = await request.json()
    except Exception:
        body = {}
    parcial = bool(body.get("parcial", False))

    row.fecha_fin = datetime.utcnow()

    if parcial:
        # Crear nueva EtapaOrden pendiente para el próximo estuchado
        nuevo = EtapaOrden(
            orden_id=row.orden_id,
            etapa_produccion_id=row.etapa_produccion_id,
        )
        db.add(nuevo)
        db.commit()
        db.refresh(nuevo)
        return {"ok": True, "todas_completadas": False, "nuevo_id": nuevo.id}

    db.commit()
    pendientes = db.query(EtapaOrden).filter(
        EtapaOrden.orden_id == row.orden_id,
        EtapaOrden.fecha_fin == None,
    ).count()
    return {"ok": True, "todas_completadas": pendientes == 0}


# ── API: revertir etapa ───────────────────────────────────────────────────────

@router.patch("/api/etapas-proceso/{etapa_orden_id}/revertir")
async def api_revertir_etapa(
    etapa_orden_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: dict = Depends(require_auth),
):
    _exigir(user, "manejar_etapas")
    row = db.query(EtapaOrden).filter(EtapaOrden.id == etapa_orden_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Etapa no encontrada.")

    try:
        body = await request.json()
    except Exception:
        body = {}
    tipo = body.get("tipo", "fin")  # 'inicio' | 'fin'

    if tipo == "inicio":
        row.fecha_inicio = None
        row.fecha_fin = None
        row.usuario_inicio_id = None
    else:
        # Si era un estuchado parcial, eliminar la siguiente EtapaOrden no iniciada
        siguiente = db.query(EtapaOrden).filter(
            EtapaOrden.orden_id == row.orden_id,
            EtapaOrden.etapa_produccion_id == row.etapa_produccion_id,
            EtapaOrden.id > row.id,
            EtapaOrden.fecha_inicio == None,
        ).first()
        if siguiente:
            db.delete(siguiente)
        row.fecha_fin = None

    db.commit()
    return {"ok": True}


# ── API: eliminar orden ────────────────────────────────────────────────────────

ESTADOS_BORRABLES = {"revisar", "faltante"}

@router.delete("/api/ordenes/{orden_id}")
async def api_eliminar_orden(
    orden_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: dict = Depends(require_auth),
):
    _exigir(user, "eliminar_orden")
    orden = _get_or_404(db, orden_id)
    if orden.estado not in ESTADOS_BORRABLES:
        raise HTTPException(
            status_code=422,
            detail=f"No se puede eliminar una orden en estado '{orden.estado}'."
        )
    db.query(Faltante).filter(Faltante.orden_id == orden_id).delete()
    db.query(HistorialEstado).filter(HistorialEstado.orden_id == orden_id).delete()
    db.delete(orden)
    db.commit()
    return {"ok": True}


# ── Vistas HTML ────────────────────────────────────────────────────────────────

@router.get("/ordenes", response_class=HTMLResponse)
async def page_ordenes(
    request: Request,
    user: dict = Depends(require_auth),
):
    return templates.TemplateResponse(request, "ordenes.html", {"user": user})


@router.get("/ordenes/nueva", response_class=HTMLResponse)
async def page_nueva_orden(
    request: Request,
    db: Session = Depends(get_db),
    user: dict = Depends(require_auth),
):
    if not _puede(user, "crear_orden"):
        return RedirectResponse(url="/ordenes", status_code=302)
    productos = db.query(ProductoTerminado).filter(ProductoTerminado.activo == True).all()
    return templates.TemplateResponse(
        request, "orden_form.html",
        {"user": user, "orden": None, "productos": productos, "error": None}
    )


@router.post("/ordenes/nueva", response_class=HTMLResponse)
async def page_crear_orden(
    request: Request,
    db: Session = Depends(get_db),
    user: dict = Depends(require_auth),
    codigo_producto:      str   = Form(...),
    descripcion_producto: str   = Form(...),
    cantidad:             float = Form(...),
    unidad:               str   = Form(...),
    fecha_carga:          str   = Form(""),
    op:                   str   = Form(""),
    fecha_vencimiento:    str   = Form(""),
    lote_granel:          str   = Form(""),
    lote_pt:              str   = Form(""),
):
    if not _puede(user, "crear_orden"):
        return RedirectResponse(url="/ordenes", status_code=302)

    # Parsear fecha de carga
    fc = datetime.utcnow()
    if fecha_carga:
        try:
            fc = datetime.fromisoformat(fecha_carga)
        except ValueError:
            pass

    # Parsear vencimiento MM/AAAA
    fv = _parse_mes_anio(fecha_vencimiento.strip()) if fecha_vencimiento.strip() else None

    orden = Orden(
        codigo_producto=codigo_producto.strip(),
        descripcion_producto=descripcion_producto.strip(),
        op=op.strip() or None,
        cantidad=cantidad,
        unidad=unidad,
        lote_granel=lote_granel.strip() or None,
        lote_pt=lote_pt.strip() or None,
        fecha_vencimiento=fv,
        estado="revisar",
        creado_por=user["id"],
        fecha_carga=fc,
    )
    db.add(orden)
    db.commit()
    db.refresh(orden)

    hist = HistorialEstado(
        orden_id=orden.id,
        estado_anterior=None,
        estado_nuevo="revisar",
        usuario_id=user["id"],
        fecha=datetime.utcnow(),
        observaciones="Orden creada.",
    )
    db.add(hist)
    db.commit()

    return RedirectResponse(url=f"/ordenes/{orden.id}", status_code=302)


@router.get("/ordenes/{orden_id}", response_class=HTMLResponse)
async def page_detalle_orden(
    orden_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: dict = Depends(require_auth),
):
    orden = _get_or_404(db, orden_id)
    return templates.TemplateResponse(
        request, "orden_detalle.html",
        {"user": user, "orden": orden, "transiciones": TRANSICIONES.get(orden.estado, [])}
    )


# ── Helpers ────────────────────────────────────────────────────────────────────

def _get_or_404(db: Session, orden_id: int) -> Orden:
    orden = db.query(Orden).filter(Orden.id == orden_id).first()
    if not orden:
        raise HTTPException(status_code=404, detail="Orden no encontrada.")
    return orden


def _fmt(dt):
    return dt.isoformat() if dt else None


def _fmt_mes_anio(d):
    """Devuelve 'MM/AAAA' a partir de un date, o None."""
    if not d:
        return None
    return f"{d.month:02d}/{d.year}"


def _orden_dict(o: Orden, creado_por_nombre: str = None) -> dict:
    return {
        "id":                   o.id,
        "fecha_carga":          _fmt(o.fecha_carga),
        "codigo_producto":      o.codigo_producto,
        "descripcion_producto": o.descripcion_producto,
        "lote_granel":          o.lote_granel,
        "lote_pt":              o.lote_pt,
        "op":                   o.op,
        "fecha_vencimiento":    _fmt_mes_anio(o.fecha_vencimiento),
        "cantidad":             o.cantidad,
        "unidad":               o.unidad,
        "estado":               o.estado,
        "subestado":            o.subestado,
        "fecha_inicio_produccion": _fmt(o.fecha_inicio_produccion),
        "fecha_terminado":      _fmt(o.fecha_terminado),
        "cantidad_obtenida":    o.cantidad_obtenida,
        "muestras_control":     o.muestras_control,
        "rendimiento":          o.rendimiento,
        "creado_por":           o.creado_por,
        "creado_por_nombre":    creado_por_nombre,
        "ultima_modificacion_fecha": _fmt(o.ultima_modificacion_fecha),
    }


def _historial_dict(h: HistorialEstado, usuarios: dict = {}) -> dict:
    return {
        "id":               h.id,
        "estado_anterior":  h.estado_anterior,
        "estado_nuevo":     h.estado_nuevo,
        "subestado_nuevo":  h.subestado_nuevo,
        "usuario_id":       h.usuario_id,
        "usuario_nombre":   usuarios.get(h.usuario_id, "—"),
        "fecha":            _fmt(h.fecha),
        "observaciones":    h.observaciones,
    }


def _faltante_dict(f: Faltante) -> dict:
    return {
        "id":              f.id,
        "tipo":            f.tipo.value,
        "codigo":          f.codigo,
        "descripcion":     f.descripcion,
        "observacion":     f.observacion,
        "resuelto":        f.resuelto,
        "fecha_registro":  _fmt(f.fecha_registro),
        "fecha_resolucion":_fmt(f.fecha_resolucion),
    }


def _entrega_dict(e: Entrega) -> dict:
    return {
        "id":                e.id,
        "fecha_entrega":     _fmt(e.fecha_entrega),
        "cantidad_entregada":e.cantidad_entregada,
        "muestras_control":  e.muestras_control,
        "remito":            e.remito,
        "es_entrega_final":  e.es_entrega_final,
        "usuario_id":        e.usuario_id,
    }
