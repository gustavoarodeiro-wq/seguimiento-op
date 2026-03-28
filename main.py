from fastapi import FastAPI, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware
import os

from sqlalchemy.orm import Session
from database import Base, engine, Orden, HistorialEstado, get_db
from routers.auth import router as auth_router, get_current_user
from routers.ordenes import router as ordenes_router
from routers.maestros import router as maestros_router
from routers.usuarios import router as usuarios_router
from routers.formulas import router as formulas_router
from routers.graneles import router as graneles_router
from routers.alertas import router as alertas_router
from routers.backup import router as backup_router, start_scheduler

# Crear tablas e inicializar datos al arrancar
Base.metadata.create_all(bind=engine)
from init_db import init as _init_db
_init_db()

app = FastAPI(title="Seguimiento de Órdenes de Producción", version="1.0.0")

# ── Middlewares ────────────────────────────────────────────────────────────────

app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv("SECRET_KEY", "cambia-esta-clave-en-produccion"),
    session_cookie="session_op",
    max_age=28800,  # 8 horas
    https_only=False,
    same_site="lax",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Archivos estáticos y templates ─────────────────────────────────────────────

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")
templates.env.cache = None  # workaround Python 3.14+

# ── Routers (API) ───────────────────────────────────────────────────────────────

app.include_router(auth_router)
app.include_router(ordenes_router)
app.include_router(maestros_router)
app.include_router(usuarios_router)
app.include_router(formulas_router)
app.include_router(graneles_router)
app.include_router(alertas_router)
app.include_router(backup_router)

# Arrancar hilo de backup automático
start_scheduler()


# ── Rutas HTML ─────────────────────────────────────────────────────────────────

def _user_or_redirect(request: Request):
    user = get_current_user(request)
    if not user:
        return None, RedirectResponse(url="/login", status_code=302)
    return user, None


@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    user, redir = _user_or_redirect(request)
    if redir:
        return redir
    return templates.TemplateResponse(request, "index.html", {"user": user})


@app.get("/productos", response_class=HTMLResponse)
async def page_productos(request: Request):
    user, redir = _user_or_redirect(request)
    if redir:
        return redir
    return templates.TemplateResponse(request, "maestros/productos.html", {"user": user})


@app.get("/materias-primas", response_class=HTMLResponse)
async def page_materias_primas(request: Request):
    user, redir = _user_or_redirect(request)
    if redir:
        return redir
    return templates.TemplateResponse(request, "maestros/materias_primas.html", {"user": user})


@app.get("/materiales-empaque", response_class=HTMLResponse)
async def page_materiales_empaque(request: Request):
    user, redir = _user_or_redirect(request)
    if redir:
        return redir
    return templates.TemplateResponse(request, "maestros/materiales_empaque.html", {"user": user})


@app.get("/formas-farmaceuticas", response_class=HTMLResponse)
async def page_formas_farmaceuticas(request: Request):
    user, redir = _user_or_redirect(request)
    if redir:
        return redir
    return templates.TemplateResponse(request, "maestros/formas_farmaceuticas.html", {"user": user})


@app.get("/graneles", response_class=HTMLResponse)
async def page_graneles(request: Request):
    user, redir = _user_or_redirect(request)
    if redir:
        return redir
    return templates.TemplateResponse(request, "maestros/graneles.html", {"user": user})


@app.get("/faltantes", response_class=HTMLResponse)
async def page_faltantes(request: Request):
    user, redir = _user_or_redirect(request)
    if redir:
        return redir
    return templates.TemplateResponse(request, "faltantes.html", {"user": user})


@app.get("/entregas", response_class=HTMLResponse)
async def page_entregas(request: Request):
    user, redir = _user_or_redirect(request)
    if redir:
        return redir
    return templates.TemplateResponse(request, "entregas.html", {"user": user})


@app.get("/alertas", response_class=HTMLResponse)
async def page_alertas(request: Request):
    user, redir = _user_or_redirect(request)
    if redir:
        return redir
    if not user.get("permisos", {}).get("ver_alertas"):
        return RedirectResponse(url="/", status_code=302)
    return templates.TemplateResponse(request, "alertas.html", {"user": user})


@app.get("/seguimiento", response_class=HTMLResponse)
async def panel_publico(request: Request):
    """Vista pública sin login para observadores."""
    return templates.TemplateResponse(request, "seguimiento_publico.html", {})


@app.get("/api/seguimiento/{orden_id}")
async def api_seguimiento_detalle(orden_id: int, db: Session = Depends(get_db)):
    """Detalle público de una orden (sin datos de usuario)."""
    orden = db.query(Orden).filter(Orden.id == orden_id).first()
    if not orden:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Orden no encontrada.")

    def fmt_mes_anio(d):
        return f"{d.month:02d}/{d.year}" if d else None

    historial = (
        db.query(HistorialEstado)
        .filter(HistorialEstado.orden_id == orden_id)
        .order_by(HistorialEstado.fecha.desc())
        .all()
    )
    return {
        "id":                   orden.id,
        "op":                   orden.op,
        "codigo_producto":      orden.codigo_producto,
        "descripcion_producto": orden.descripcion_producto,
        "cantidad":             orden.cantidad,
        "unidad":               orden.unidad.value if orden.unidad else None,
        "lote_pt":              orden.lote_pt,
        "lote_granel":          orden.lote_granel,
        "fecha_vencimiento":    fmt_mes_anio(orden.fecha_vencimiento),
        "estado":               orden.estado,
        "subestado":            orden.subestado,
        "historial": [
            {
                "estado_anterior": h.estado_anterior,
                "estado_nuevo":    h.estado_nuevo,
                "fecha":           h.fecha.isoformat() if h.fecha else None,
                "observaciones":   h.observaciones,
            }
            for h in historial
        ],
    }


@app.get("/api/seguimiento")
async def api_seguimiento(db: Session = Depends(get_db)):
    """API pública que alimenta el panel de seguimiento."""
    from sqlalchemy import case
    ordenes = (
        db.query(Orden)
        .order_by(
            case((Orden.op == None, 1), else_=0),
            Orden.op.asc(),
            Orden.fecha_carga.desc(),
        )
        .all()
    )
    def fmt_mes_anio(d):
        return f"{d.month:02d}/{d.year}" if d else None

    return [
        {
            "id":                   o.id,
            "op":                   o.op,
            "codigo_producto":      o.codigo_producto,
            "descripcion_producto": o.descripcion_producto,
            "cantidad":             o.cantidad,
            "unidad":               o.unidad.value if o.unidad else None,
            "lote_pt":              o.lote_pt,
            "lote_granel":          o.lote_granel,
            "fecha_vencimiento":    fmt_mes_anio(o.fecha_vencimiento),
            "estado":               o.estado,
            "subestado":            o.subestado,
        }
        for o in ordenes
    ]


@app.get("/health")
async def health():
    return {"status": "ok", "app": "Seguimiento OP"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
