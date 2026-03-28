from fastapi import APIRouter, Request, Form, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
import bcrypt as _bcrypt

from database import get_db, Usuario
from permissions import compute_permisos

router = APIRouter()
templates = Jinja2Templates(directory="templates")
templates.env.cache = None  # workaround Python 3.14+


# ── Dependencia de sesión ──────────────────────────────────────────────────────

def get_current_user(request: Request) -> dict | None:
    """Devuelve el dict de sesión del usuario o None si no hay sesión activa."""
    user = request.session.get("user")
    if user and "permisos" not in user:
        request.session.clear()
        return None
    return user


def require_auth(request: Request) -> dict:
    """Dependencia que redirige a /login si no hay sesión activa."""
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=303, headers={"Location": "/login"})
    return user


# ── Rutas ──────────────────────────────────────────────────────────────────────

@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    if request.session.get("user"):
        return RedirectResponse(url="/", status_code=302)
    return templates.TemplateResponse(request, "login.html", {"error": None})


@router.post("/login", response_class=HTMLResponse)
async def login_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    error = None
    usuario = db.query(Usuario).filter(
        Usuario.email == email.strip().lower(),
        Usuario.activo == True,
    ).first()

    if not usuario or not _bcrypt.checkpw(password.encode(), usuario.password_hash.encode()):
        error = "Email o contraseña incorrectos."
        return templates.TemplateResponse(
            request, "login.html", {"error": error}, status_code=401
        )

    permisos = compute_permisos(usuario.rol.value, usuario.permisos_json)
    request.session["user"] = {
        "id":       usuario.id,
        "nombre":   usuario.nombre,
        "email":    usuario.email,
        "rol":      usuario.rol.value,
        "permisos": permisos,
    }
    return RedirectResponse(url="/", status_code=302)


@router.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=302)
