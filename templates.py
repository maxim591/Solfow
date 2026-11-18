from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

templates = Jinja2Templates(directory="templates")

def render(request: Request, name: str, context: dict = None, status_code: int = 200) -> HTMLResponse:
    ctx = {"request": request}
    if context:
        ctx.update(context)
    return templates.TemplateResponse(request, name, ctx, status_code=status_code)

def error_page(request: Request, message: str, status_code: int = 400, back_url: str = "/") -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "index.html",
        {"request": request, "error": message, "back_url": back_url},
        status_code=status_code,
    )