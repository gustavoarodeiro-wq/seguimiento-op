from fastapi import APIRouter, Request, Form, Depends, Query, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from shared import templates as _shared_templates
from sqlalchemy.orm import Session
from sqlalchemy import func, or_, case
from datetime import datetime, date

from config_cache import now_local as now_ar
from typing import Optional

from database import (
    get_db, Orden, HistorialEstado, Faltante, Entrega,
    ProductoTerminado, TipoFaltante, Usuario,
    EtapaOrden, EtapaProduccion, EtapaProducto, AreaProduccion, FormaFarmaceutica,
)
from routers.auth import require_auth, get_current_user

router = APIRouter()
templates = _shared_templates

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
    "en_proceso":  ["entregada", "cancelada"],
    "terminada":   ["entregada"],   # legacy: órdenes existentes en ese estado
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

    # Etapa actual: una query para todas las órdenes en proceso
    etapa_actual:  dict[int, str] = {}
    etapa_estado_map: dict[int, str] = {}
    en_proceso_ids = [o.id for o in ordenes if o.estado == "en_proceso"]
    if en_proceso_ids:
        from sqlalchemy.orm import joinedload as jl
        etapas_filas = (
            db.query(EtapaOrden)
            .options(jl(EtapaOrden.etapa_producto))
            .filter(
                EtapaOrden.orden_id.in_(en_proceso_ids),
                EtapaOrden.estado.in_(["en_curso", "pendiente"]),
            )
            .order_by(EtapaOrden.orden_id, EtapaOrden.id)
            .all()
        )
        # Agrupar por orden (comparación explícita para evitar problemas con espacios)
        por_orden: dict[int, dict] = {}
        for e in etapas_filas:
            ep = e.etapa_producto
            nombre = (e.nombre_display or "").strip() or (ep.nombre if ep else None) or "—"
            est = (e.estado or "").strip()
            if e.orden_id not in por_orden:
                por_orden[e.orden_id] = {"en_curso": [], "pendiente": []}
            if est == "en_curso":
                por_orden[e.orden_id]["en_curso"].append(nombre)
            elif est == "pendiente":
                por_orden[e.orden_id]["pendiente"].append(nombre)
        siguiente_map: dict[int, str] = {}
        for oid, data in por_orden.items():
            if data["en_curso"]:
                etapa_actual[oid] = " / ".join(data["en_curso"])
                etapa_estado_map[oid] = "en_curso"
                if data["pendiente"]:
                    siguiente_map[oid] = data["pendiente"][0]
            elif data["pendiente"]:
                etapa_actual[oid] = data["pendiente"][0]
                etapa_estado_map[oid] = "pendiente"
    else:
        siguiente_map = {}

    return {
        "total": total,
        "items": [_orden_dict(o, nombres.get(o.creado_por), etapa_actual.get(o.id), etapa_estado_map.get(o.id), siguiente_map.get(o.id)) for o in ordenes],
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
        .order_by(EtapaOrden.id)
        .all()
    )
    etapa_user_ids = {e.usuario_inicio_id for e in etapas_orden if e.usuario_inicio_id}
    user_ids = {h.usuario_id for h in historial if h.usuario_id} | etapa_user_ids
    usuarios = {u.id: u.nombre for u in db.query(Usuario).filter(Usuario.id.in_(user_ids)).all()}

    etapas_lista = []
    for e in etapas_orden:
        nombre = e.etapa_producto.nombre if e.etapa_producto else "—"
        area_nombre = e.area.nombre if e.area else None
        etapas_lista.append({
            "id":             e.id,
            "nombre":         nombre,
            "nombre_display": e.nombre_display,
            "iteracion":      e.iteracion,
            "area":           area_nombre,
            "estado":         e.estado,
            "fecha_inicio":   _fmt(e.fecha_inicio),
            "fecha_fin":      _fmt(e.fecha_fin),
            "usuario":        usuarios.get(e.usuario_inicio_id),
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
    """Actualiza OP, lotes, vencimiento y cantidad de una orden."""
    _exigir(user, "editar_datos_orden")

    orden = _get_or_404(db, orden_id)
    body  = await request.json()

    if "op" in body:
        orden.op = body["op"].strip() or None
    if "lote_granel" in body:
        orden.lote_granel = body["lote_granel"].strip() or None
    if "lote_pt" in body:
        orden.lote_pt = body["lote_pt"].strip() or None
    if "cantidad" in body:
        try:
            cant = float(body["cantidad"])
            if cant <= 0:
                raise HTTPException(status_code=422, detail="La cantidad debe ser mayor a 0.")
            orden.cantidad = cant
        except (TypeError, ValueError):
            raise HTTPException(status_code=422, detail="Cantidad inválida.")
    if "fecha_vencimiento" in body:
        raw = body["fecha_vencimiento"].strip()
        if raw:
            parsed = _parse_mes_anio(raw)
            if parsed is None:
                raise HTTPException(status_code=422, detail="Vencimiento inválido. Usá el formato MM/AAAA (ej: 06/2026).")
            hoy = date.today()
            if parsed < date(hoy.year, hoy.month, 1):
                raise HTTPException(status_code=422, detail="El vencimiento no puede ser anterior al mes actual.")
            orden.fecha_vencimiento = parsed
        else:
            orden.fecha_vencimiento = None

    orden.ultima_modificacion_por   = user["id"]
    orden.ultima_modificacion_fecha = now_ar()
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
        fecha=now_ar(),
        observaciones=observaciones,
    )
    db.add(hist)

    # Actualizar orden
    orden.estado = nuevo_estado
    orden.subestado = subestado
    orden.ultima_modificacion_por = user["id"]
    orden.ultima_modificacion_fecha = now_ar()

    if nuevo_estado == "en_proceso" and not orden.fecha_inicio_produccion:
        orden.fecha_inicio_produccion = now_ar()
        # Auto-crear etapas de la orden desde las etapas del producto
        ya_creadas = db.query(EtapaOrden).filter(EtapaOrden.orden_id == orden_id).count()
        if ya_creadas == 0:
            pt = db.query(ProductoTerminado).filter(
                ProductoTerminado.codigo == orden.codigo_producto
            ).first()
            if pt:
                etapas = db.query(EtapaProducto).filter(
                    EtapaProducto.producto_id == pt.id,
                    EtapaProducto.activo == True,
                ).order_by(EtapaProducto.orden).all()
                for e in etapas:
                    db.add(EtapaOrden(orden_id=orden_id, etapa_producto_id=e.id, estado="pendiente"))

    if nuevo_estado in ("terminada", "entregada"):
        if not orden.fecha_terminado:
            orden.fecha_terminado = now_ar()
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
        fecha_registro=now_ar(),
    )
    db.add(faltante)

    # Auto-transición REVISAR → FALTANTE al registrar el primer faltante
    if orden.estado == "revisar":
        db.add(HistorialEstado(
            orden_id=orden_id,
            estado_anterior="revisar",
            estado_nuevo="faltante",
            usuario_id=user["id"],
            fecha=now_ar(),
            observaciones="Faltante registrado durante revisión.",
        ))
        orden.estado = "faltante"
        orden.ultima_modificacion_por = user["id"]
        orden.ultima_modificacion_fecha = now_ar()

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
    faltante.fecha_resolucion = now_ar()
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
        fecha_entrega=now_ar(),
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
            fecha=now_ar(),
            observaciones=f"Entrega final. Remito: {entrega.remito or '—'}",
        ))
        orden.estado = "entregada"
        orden.ultima_modificacion_por = user["id"]
        orden.ultima_modificacion_fecha = now_ar()

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
            fecha=now_ar(),
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

    # Creación lazy: si la orden está en proceso y no tiene etapas, crearlas
    ya_creadas = db.query(EtapaOrden).filter(EtapaOrden.orden_id == orden_id).count()
    if ya_creadas == 0 and orden.estado == "en_proceso":
        pt = db.query(ProductoTerminado).filter(
            ProductoTerminado.codigo == orden.codigo_producto
        ).first()
        if pt:
            etapas = db.query(EtapaProducto).filter(
                EtapaProducto.producto_id == pt.id,
                EtapaProducto.activo == True,
            ).order_by(EtapaProducto.orden).all()
            for e in etapas:
                db.add(EtapaOrden(orden_id=orden_id, etapa_producto_id=e.id, estado="pendiente"))
            db.commit()

    rows = (
        db.query(EtapaOrden)
        .filter(EtapaOrden.orden_id == orden_id)
        .order_by(EtapaOrden.id)
        .all()
    )
    user_ids = {r.usuario_inicio_id for r in rows if r.usuario_inicio_id}
    user_ids |= {r.usuario_fin_id for r in rows if r.usuario_fin_id}
    usuarios = {u.id: u.nombre for u in db.query(Usuario).filter(Usuario.id.in_(user_ids)).all()}

    # Calcular total de iteraciones y max iteracion por etapa_producto_id
    from collections import Counter
    iter_count = Counter(r.etapa_producto_id for r in rows)
    max_iter: dict[int, int] = {}
    for r in rows:
        if r.etapa_producto_id:
            max_iter[r.etapa_producto_id] = max(max_iter.get(r.etapa_producto_id, 0), r.iteracion)

    result = []
    for r in rows:
        ep = r.etapa_producto
        areas = [{"id": a.id, "nombre": a.nombre} for a in ep.areas] if ep else []
        # es_parcial = fue completada pero no es la última iteración de su etapa
        es_parcial = (
            r.estado == "completada"
            and r.etapa_producto_id is not None
            and r.iteracion < max_iter.get(r.etapa_producto_id, r.iteracion)
        )
        result.append({
            "id":               r.id,
            "etapa_producto_id": r.etapa_producto_id,
            "nombre":           ep.nombre if ep else "—",
            "nombre_display":   r.nombre_display,
            "iteracion":        r.iteracion,
            "total_iteraciones": iter_count.get(r.etapa_producto_id, 1),
            "orden":            ep.orden if ep else 0,
            "estado":           r.estado,
            "es_parcial":       es_parcial,
            "areas_posibles":   areas,
            "area_id":          r.area_id,
            "area_nombre":      r.area.nombre if r.area else None,
            "fecha_inicio":     _fmt(r.fecha_inicio),
            "fecha_fin":        _fmt(r.fecha_fin),
            "cantidad_obtenida": r.cantidad_obtenida,
            "unidad_obtenida":  r.unidad_obtenida,
            "usuario_inicio":   usuarios.get(r.usuario_inicio_id),
            "usuario_fin":      usuarios.get(r.usuario_fin_id),
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
    try:
        body = await request.json()
    except Exception:
        body = {}
    # Área: auto si es única, o tomada del body
    if body.get("area_id"):
        row.area_id = int(body["area_id"])
    elif row.etapa_producto and len(row.etapa_producto.areas) == 1:
        row.area_id = row.etapa_producto.areas[0].id
    row.fecha_inicio = now_ar()
    row.estado = "en_curso"
    row.usuario_inicio_id = user["id"]
    db.commit()
    areas = [{"id": a.id, "nombre": a.nombre} for a in row.etapa_producto.areas] if row.etapa_producto else []
    return {"ok": True, "area_id": row.area_id, "areas_posibles": areas}


@router.patch("/api/etapas-proceso/{etapa_orden_id}/area")
async def api_cambiar_area_etapa(
    etapa_orden_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: dict = Depends(require_auth),
):
    _exigir(user, "manejar_etapas")
    row = db.query(EtapaOrden).filter(EtapaOrden.id == etapa_orden_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Etapa no encontrada.")
    if row.estado not in ("en_curso", "pendiente"):
        raise HTTPException(status_code=400, detail="Solo se puede cambiar el área de etapas en curso o pendientes.")
    try:
        body = await request.json()
    except Exception:
        body = {}
    area_id = body.get("area_id")
    if not area_id:
        raise HTTPException(status_code=400, detail="Debe indicar un área.")
    row.area_id = int(area_id)
    db.commit()
    return {"ok": True, "area_nombre": row.area.nombre if row.area else None}


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
    row.fecha_fin = now_ar()
    row.estado = "completada"
    row.usuario_fin_id = user["id"]

    if parcial:
        # Crear siguiente iteración de estuchado
        ep = row.etapa_producto
        siguiente_iter = row.iteracion + 1
        nuevo = EtapaOrden(
            orden_id=row.orden_id,
            etapa_producto_id=row.etapa_producto_id,
            estado="pendiente",
            iteracion=siguiente_iter,
            nombre_display=f"{ep.nombre} {siguiente_iter}" if ep else f"Estuchado {siguiente_iter}",
        )
        # Actualizar nombre_display de la actual si no tiene
        if not row.nombre_display:
            ep_nombre = ep.nombre if ep else "Estuchado"
            row.nombre_display = f"{ep_nombre} 1"
        db.add(nuevo)
        db.commit()
        db.refresh(nuevo)
        return {"ok": True, "todas_completadas": False, "es_parcial": True, "nuevo_id": nuevo.id}

    db.commit()
    pendientes = db.query(EtapaOrden).filter(
        EtapaOrden.orden_id == row.orden_id,
        EtapaOrden.estado != "completada",
    ).count()

    todas_completadas = pendientes == 0
    return {"ok": True, "todas_completadas": todas_completadas, "es_parcial": False}




# ── API: revertir orden entregada → en_proceso (admin) ───────────────────────

@router.patch("/api/ordenes/{orden_id}/revertir-entregada")
async def api_revertir_orden_entregada(
    orden_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(require_auth),
):
    _exigir(user, "accion_admin")
    orden = _get_or_404(db, orden_id)
    if orden.estado != "entregada":
        raise HTTPException(status_code=422, detail="La orden no está en estado Terminado.")
    orden.estado = "en_proceso"
    orden.fecha_terminado = None
    orden.ultima_modificacion_por = user["id"]
    orden.ultima_modificacion_fecha = now_ar()
    db.add(HistorialEstado(
        orden_id=orden_id,
        estado_anterior="entregada",
        estado_nuevo="en_proceso",
        usuario_id=user["id"],
        fecha=now_ar(),
        observaciones="Reversión de orden Terminada a En Proceso por admin.",
    ))
    db.commit()
    return {"ok": True}


# ── API: revertir etapa (admin) ───────────────────────────────────────────────

@router.patch("/api/etapas-proceso/{etapa_orden_id}/revertir")
async def api_revertir_etapa(
    etapa_orden_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: dict = Depends(require_auth),
):
    _exigir(user, "accion_admin")
    row = db.query(EtapaOrden).filter(EtapaOrden.id == etapa_orden_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Etapa no encontrada.")
    try:
        body = await request.json()
    except Exception:
        body = {}
    tipo = body.get("tipo", "fin")

    orden = db.query(Orden).filter(Orden.id == row.orden_id).first()
    if tipo == "inicio":
        row.fecha_inicio = None
        row.fecha_fin = None
        row.estado = "pendiente"
        row.area_id = None
        row.usuario_inicio_id = None
        row.usuario_fin_id = None
    else:
        row.fecha_fin = None
        row.estado = "en_curso"
        row.usuario_fin_id = None
        # Si la orden quedó entregada por esta etapa, volver a en_proceso
        if orden and orden.estado == "entregada":
            orden.estado = "en_proceso"
            orden.fecha_terminado = None
            db.add(HistorialEstado(
                orden_id=row.orden_id,
                estado_anterior="entregada",
                estado_nuevo="en_proceso",
                usuario_id=user["id"],
                fecha=now_ar(),
                observaciones=f"Reversión de etapa por admin (id={etapa_orden_id})",
            ))

    db.commit()
    return {"ok": True}


# ── API: eliminar etapa (admin) ───────────────────────────────────────────────

@router.delete("/api/etapas-proceso/{etapa_orden_id}")
async def api_eliminar_etapa(
    etapa_orden_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(require_auth),
):
    _exigir(user, "accion_admin")
    row = db.query(EtapaOrden).filter(EtapaOrden.id == etapa_orden_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Etapa no encontrada.")
    db.delete(row)
    db.commit()
    return {"ok": True}


# ── API: eliminar entrega (admin) ─────────────────────────────────────────────

@router.delete("/api/entregas/{entrega_id}")
async def api_eliminar_entrega(
    entrega_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(require_auth),
):
    _exigir(user, "accion_admin")
    entrega = db.query(Entrega).filter(Entrega.id == entrega_id).first()
    if not entrega:
        raise HTTPException(status_code=404, detail="Entrega no encontrada.")

    orden = db.query(Orden).filter(Orden.id == entrega.orden_id).first()
    # Si era entrega final y la orden está en entregada, volver a en_proceso
    if entrega.es_entrega_final and orden and orden.estado == "entregada":
        orden.estado = "en_proceso"
        orden.fecha_terminado = None
        db.add(HistorialEstado(
            orden_id=entrega.orden_id,
            estado_anterior="entregada",
            estado_nuevo="en_proceso",
            usuario_id=user["id"],
            fecha=now_ar(),
            observaciones=f"Entrega final eliminada por admin (entrega id={entrega_id})",
        ))

    db.delete(entrega)
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
    es_admin = user.get("permisos", {}).get("accion_admin", False)
    if not es_admin and orden.estado not in ESTADOS_BORRABLES:
        raise HTTPException(
            status_code=422,
            detail=f"No se puede eliminar una orden en estado '{orden.estado}'."
        )
    db.query(Faltante).filter(Faltante.orden_id == orden_id).delete()
    db.query(HistorialEstado).filter(HistorialEstado.orden_id == orden_id).delete()
    db.query(EtapaOrden).filter(EtapaOrden.orden_id == orden_id).delete()
    db.query(Entrega).filter(Entrega.orden_id == orden_id).delete()
    db.delete(orden)
    db.commit()
    return {"ok": True}


# ── API: Gantt ────────────────────────────────────────────────────────────────

@router.get("/api/gantt")
async def api_gantt(
    request: Request,
    db: Session = Depends(get_db),
    user: dict = Depends(require_auth),
):
    ordenes = (
        db.query(Orden)
        .filter(Orden.estado.in_(["en_proceso", "emitido", "para_emitir"]))
        .order_by(Orden.fecha_carga.desc())
        .all()
    )
    result = []
    for o in ordenes:
        etapas = (
            db.query(EtapaOrden)
            .filter(EtapaOrden.orden_id == o.id)
            .order_by(EtapaOrden.id)
            .all()
        )
        etapas_data = []
        for e in etapas:
            ep = e.etapa_producto
            areas_posibles = [{"id": a.id, "nombre": a.nombre} for a in ep.areas] if ep else []
            etapas_data.append({
                "id":             e.id,
                "nombre":         ep.nombre if ep else "—",
                "nombre_display": e.nombre_display,
                "iteracion":      e.iteracion,
                "area":           e.area.nombre if e.area else None,
                "area_id":        e.area_id,
                "areas_posibles": areas_posibles,
                "estado":         e.estado,
                "fecha_inicio":   e.fecha_inicio.isoformat() if e.fecha_inicio else None,
                "fecha_fin":      e.fecha_fin.isoformat() if e.fecha_fin else None,
            })
        result.append({
            "id":                   o.id,
            "op":                   o.op,
            "lote_pt":              o.lote_pt,
            "codigo_producto":      o.codigo_producto,
            "descripcion_producto": o.descripcion_producto,
            "cantidad":             o.cantidad,
            "unidad":               o.unidad.value if o.unidad else None,
            "estado":               o.estado,
            "fecha_inicio":         o.fecha_inicio_produccion.isoformat() if o.fecha_inicio_produccion else None,
            "etapas":               etapas_data,
        })
    return result


# ── Vistas HTML ────────────────────────────────────────────────────────────────

@router.get("/gantt", response_class=HTMLResponse)
async def page_gantt(
    request: Request,
    user: dict = Depends(require_auth),
):
    return templates.TemplateResponse(request, "gantt.html", {"user": user})


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
    fc = now_ar()
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
        fecha=now_ar(),
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


def _orden_dict(o: Orden, creado_por_nombre: str = None, etapa_actual: str = None, etapa_estado: str = None, etapa_siguiente: str = None) -> dict:
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
        "etapa_actual":         etapa_actual,
        "etapa_estado":         etapa_estado,
        "etapa_siguiente":      etapa_siguiente,
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
