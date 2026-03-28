from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from passlib.context import CryptContext

import json
from database import get_db, Usuario, RolUsuario
from routers.auth import require_auth
from permissions import compute_permisos, TODOS_LOS_PERMISOS, GRUPOS_PERMISOS, default_permisos

router = APIRouter()
templates = Jinja2Templates(directory="templates")
templates.env.cache = None  # workaround Python 3.14+

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

ROLES_VALIDOS = {r.value for r in RolUsuario}


def _solo_admin(user: dict):
    if user["rol"] != "admin":
        raise HTTPException(status_code=403, detail="Solo administradores.")


# ── API ────────────────────────────────────────────────────────────────────────

@router.get("/api/usuarios")
async def api_list_usuarios(
    request: Request,
    db: Session = Depends(get_db),
    user: dict = Depends(require_auth),
):
    _solo_admin(user)
    items = db.query(Usuario).order_by(Usuario.nombre).all()
    return [_u_dict(u) for u in items]


@router.post("/api/usuarios")
async def api_create_usuario(
    request: Request,
    db: Session = Depends(get_db),
    user: dict = Depends(require_auth),
):
    _solo_admin(user)
    body = await request.json()

    nombre   = body.get("nombre", "").strip()
    email    = body.get("email", "").strip().lower()
    password = body.get("password", "").strip()
    rol      = body.get("rol", "operador").strip()

    if not nombre:
        raise HTTPException(status_code=422, detail="El nombre es obligatorio.")
    if not email or "@" not in email:
        raise HTTPException(status_code=422, detail="El email no es válido.")
    if not password or len(password) < 6:
        raise HTTPException(status_code=422, detail="La contraseña debe tener al menos 6 caracteres.")
    if rol not in ROLES_VALIDOS:
        raise HTTPException(status_code=422, detail=f"Rol inválido. Usar: {', '.join(ROLES_VALIDOS)}")
    if db.query(Usuario).filter(Usuario.email == email).first():
        raise HTTPException(status_code=409, detail=f"Ya existe un usuario con el email '{email}'.")

    nuevo = Usuario(
        nombre=nombre,
        email=email,
        password_hash=pwd_context.hash(password),
        rol=RolUsuario(rol),
        activo=True,
    )
    db.add(nuevo)
    db.commit()
    db.refresh(nuevo)
    return _u_dict(nuevo)


@router.put("/api/usuarios/{usuario_id}")
async def api_update_usuario(
    usuario_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: dict = Depends(require_auth),
):
    _solo_admin(user)
    item = _get_or_404(db, usuario_id)
    body = await request.json()

    if "nombre" in body:
        nombre = body["nombre"].strip()
        if not nombre:
            raise HTTPException(status_code=422, detail="El nombre es obligatorio.")
        item.nombre = nombre

    if "email" in body:
        email = body["email"].strip().lower()
        if not email or "@" not in email:
            raise HTTPException(status_code=422, detail="El email no es válido.")
        existe = db.query(Usuario).filter(
            Usuario.email == email, Usuario.id != usuario_id
        ).first()
        if existe:
            raise HTTPException(status_code=409, detail=f"El email '{email}' ya está en uso.")
        item.email = email

    if "rol" in body:
        rol = body["rol"].strip()
        if rol not in ROLES_VALIDOS:
            raise HTTPException(status_code=422, detail=f"Rol inválido.")
        # Evitar que el admin se quite su propio rol
        if usuario_id == user["id"] and rol != "admin":
            raise HTTPException(status_code=422, detail="No podés cambiar tu propio rol.")
        item.rol = RolUsuario(rol)

    db.commit()
    db.refresh(item)
    return _u_dict(item)


@router.patch("/api/usuarios/{usuario_id}/password")
async def api_cambiar_password(
    usuario_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: dict = Depends(require_auth),
):
    _solo_admin(user)
    item = _get_or_404(db, usuario_id)
    body = await request.json()
    password = body.get("password", "").strip()
    if not password or len(password) < 6:
        raise HTTPException(status_code=422, detail="La contraseña debe tener al menos 6 caracteres.")
    item.password_hash = pwd_context.hash(password)
    db.commit()
    return {"ok": True}


@router.patch("/api/usuarios/{usuario_id}/toggle")
async def api_toggle_usuario(
    usuario_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: dict = Depends(require_auth),
):
    _solo_admin(user)
    if usuario_id == user["id"]:
        raise HTTPException(status_code=422, detail="No podés desactivarte a vos mismo.")
    item = _get_or_404(db, usuario_id)
    item.activo = not item.activo
    db.commit()
    return {"id": item.id, "activo": item.activo}


# ── Vista HTML ─────────────────────────────────────────────────────────────────

@router.get("/usuarios", response_class=HTMLResponse)
async def page_usuarios(
    request: Request,
    user: dict = Depends(require_auth),
):
    if user["rol"] != "admin":
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url="/", status_code=302)
    return templates.TemplateResponse(request, "usuarios.html", {"user": user})


# ── Helpers ────────────────────────────────────────────────────────────────────

def _get_or_404(db: Session, usuario_id: int) -> Usuario:
    item = db.query(Usuario).filter(Usuario.id == usuario_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Usuario no encontrado.")
    return item


def _u_dict(u: Usuario) -> dict:
    return {
        "id":     u.id,
        "nombre": u.nombre,
        "email":  u.email,
        "rol":    u.rol.value,
        "activo": u.activo,
    }


# ── API: permisos por usuario ──────────────────────────────────────────────────

@router.get("/api/usuarios/{usuario_id}/permisos")
async def api_get_permisos(
    usuario_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(require_auth),
):
    _solo_admin(user)
    item = _get_or_404(db, usuario_id)
    efectivos  = compute_permisos(item.rol.value, item.permisos_json)
    defaults   = default_permisos(item.rol.value)
    overrides  = json.loads(item.permisos_json) if item.permisos_json else {}
    return {
        "usuario_id": item.id,
        "rol":        item.rol.value,
        "efectivos":  efectivos,
        "defaults":   defaults,
        "overrides":  overrides,
        "grupos":     GRUPOS_PERMISOS,
        "descripciones": TODOS_LOS_PERMISOS,
    }


@router.put("/api/usuarios/{usuario_id}/permisos/{permiso}")
async def api_set_permiso(
    usuario_id: int,
    permiso: str,
    request: Request,
    db: Session = Depends(get_db),
    user: dict = Depends(require_auth),
):
    _solo_admin(user)
    if permiso not in TODOS_LOS_PERMISOS:
        raise HTTPException(status_code=422, detail=f"Permiso desconocido: {permiso}")
    item = _get_or_404(db, usuario_id)
    body = await request.json()
    # valor: True / False / None (None = reset a default del rol)
    valor = body.get("valor")

    overrides = json.loads(item.permisos_json) if item.permisos_json else {}
    if valor is None:
        overrides.pop(permiso, None)  # reset a default
    else:
        overrides[permiso] = bool(valor)

    item.permisos_json = json.dumps(overrides) if overrides else None
    db.commit()
    efectivos = compute_permisos(item.rol.value, item.permisos_json)
    return {"permiso": permiso, "valor": efectivos[permiso], "es_override": permiso in overrides}


@router.delete("/api/usuarios/{usuario_id}/permisos")
async def api_reset_permisos(
    usuario_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(require_auth),
):
    """Reset todos los overrides — vuelve a los defaults del rol."""
    _solo_admin(user)
    item = _get_or_404(db, usuario_id)
    item.permisos_json = None
    db.commit()
    return {"ok": True, "efectivos": default_permisos(item.rol.value)}
