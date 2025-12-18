from __future__ import annotations

import os
from datetime import datetime
from typing import Optional, Any, Dict, List

from fastapi import FastAPI, Request, Form, Response
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse, JSONResponse, HTMLResponse

from app.models import User, Booking, UsageLog
from app.data import db, BRAND_LOGO_URL

# === Google GenAI (optional) ===
try:
    from google.generativeai import GenerativeModel, configure
    GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
    if GOOGLE_API_KEY:
        configure(api_key=GOOGLE_API_KEY)
    else:
        GOOGLE_API_KEY = None
except ImportError:
    GOOGLE_API_KEY = None

# === Constants ===
# Giả sử STATUS_TRANS được định nghĩa như sau (bổ sung nếu chưa có)
STATUS_TRANS = {
    "AVAILABLE": "Sẵn sàng",
    "BOOKED": "Đã đặt",
    "IN_USE": "Đang dùng",
    "BROKEN": "Hư hỏng",
    "MAINTENANCE": "Bảo trì",
    "LIQUIDATED": "Đã thanh lý",
}

# === App setup ===
app = FastAPI()

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


# =========================================================
# Helpers: auth / context
# =========================================================

def get_current_user(request: Request) -> Optional[User]:
    user_id = request.cookies.get("user_id")
    if not user_id:
        return None
    return db.get_user(user_id)


def redirect_to(path: str) -> RedirectResponse:
    return RedirectResponse(path, status_code=302)


def require_login(request: Request) -> Optional[RedirectResponse]:
    if not get_current_user(request):
        return redirect_to("/login")
    return None


def require_staff(request: Request) -> Optional[RedirectResponse]:
    user = get_current_user(request)
    if not user:
        return redirect_to("/login")
    if user.role not in ["ADMIN", "STAFF"]:
        return redirect_to("/")
    return None


def require_admin(request: Request) -> Optional[RedirectResponse]:
    user = get_current_user(request)
    if not user:
        return redirect_to("/login")
    if user.role != "ADMIN":
        return redirect_to("/")
    return None


def _to_dict(x: Any) -> Dict[str, Any]:
    """Chuyển object sang dict, hỗ trợ Pydantic v1 (.dict()) và v2 (.model_dump())."""
    if hasattr(x, "model_dump"):
        return x.model_dump()
    if hasattr(x, "dict"):
        return x.dict()
    if hasattr(x, "__dict__"):
        return dict(x.__dict__)
    return dict(x)


def user_to_dict(u: Optional[User]) -> Dict[str, Any]:
    if not u:
        return {}
    return _to_dict(u)


def common_context(request: Request) -> dict:
    user = get_current_user(request)
    return {
        "request": request,
        "current_user": user,
        "current_user_json": user_to_dict(user),
        "home_config": getattr(db, "home_config", None),
        "brand_logo": BRAND_LOGO_URL,
        "visit_count": getattr(getattr(db, "home_config", None), "visitorCount", 0),
        "path": request.url.path,
        "now": datetime.now(),
    }


# =========================================================
# Middleware
# =========================================================

@app.middleware("http")
async def add_context_middleware(request: Request, call_next):
    response = await call_next(request)
    return response


# =========================================================
# Pages: Core
# =========================================================

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    ctx = common_context(request)
    home_cfg = getattr(db, "home_config", None)
    if home_cfg and hasattr(home_cfg, "visitorCount"):
        home_cfg.visitorCount += 1
        ctx["visit_count"] = home_cfg.visitorCount

    featured_ids = getattr(home_cfg, "featuredEquipmentIds", []) if home_cfg else []
    equipment_list = getattr(db, "equipment", [])
    featured = [e for e in equipment_list if getattr(e, "id", None) in featured_ids]

    ctx.update(
        {
            "page_title": "Trang chủ",
            "featured_equipment": featured,
            "labs": getattr(db, "labs", []),
        }
    )
    return templates.TemplateResponse("index.html", ctx)


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    if get_current_user(request):
        return redirect_to("/")
    ctx = common_context(request)
    ctx.update({"page_title": "Đăng nhập"})
    return templates.TemplateResponse("login.html", ctx)


@app.post("/api/login")
async def login_api(response: Response, user_id: str = Form(...), password: str = Form(...)):
    user = db.get_user(user_id)
    if user and user.password == password and not user.isLocked:
        resp = JSONResponse(content={"success": True, "redirect": "/"})
        resp.set_cookie(key="user_id", value=user.id, httponly=True, samesite="lax")
        return resp
    return JSONResponse(content={"success": False, "message": "Sai thông tin đăng nhập"}, status_code=401)


@app.get("/logout")
async def logout():
    resp = redirect_to("/login")
    resp.delete_cookie("user_id")
    return resp


# =========================================================
# Pages: Dashboard / Layout / AI Assistant / Profile
# =========================================================

@app.get("/layout", response_class=HTMLResponse)
async def layout_page(request: Request):
    r = require_login(request)
    if r:
        return r
    ctx = common_context(request)
    ctx.update({"page_title": "Layout"})
    return templates.TemplateResponse("layout.html", ctx)


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page(request: Request):
    r = require_staff(request)
    if r:
        return r
    ctx = common_context(request)
    ctx.update({"page_title": "Dashboard"})
    return templates.TemplateResponse("dashboard.html", ctx)


@app.get("/ai-assistant", response_class=HTMLResponse)
async def ai_assistant_page(request: Request):
    r = require_login(request)
    if r:
        return r
    ctx = common_context(request)
    ctx.update({"page_title": "AI Assistant"})
    return templates.TemplateResponse("assistant.html", ctx)


@app.get("/profile", response_class=HTMLResponse)
async def user_profile_page(request: Request):
    r = require_login(request)
    if r:
        return r
    ctx = common_context(request)
    ctx.update({"page_title": "Hồ sơ cá nhân", "profile_user": ctx["current_user"]})
    return templates.TemplateResponse("profile.html", ctx)


# =========================================================
# Pages: Equipment
# =========================================================

@app.get("/equipment", response_class=HTMLResponse)
async def equipment_list(request: Request, search: str = "", status: str = "ALL"):
    ctx = common_context(request)
    items = list(getattr(db, "equipment", []))

    if search:
        s = search.lower()
        items = [e for e in items if s in getattr(e, "name", "").lower() or s in getattr(e, "code", "").lower()]

    if status != "ALL":
        items = [e for e in items if getattr(e, "status", None) == status]

    ctx.update(
        {
            "page_title": "Thiết bị",
            "equipment": items,
            "search": search,
            "status_filter": status,
        }
    )
    return templates.TemplateResponse("equipment_list.html", ctx)


@app.get("/equipment/{id}", response_class=HTMLResponse)
async def equipment_detail(request: Request, id: str):
    ctx = common_context(request)
    item = db.get_equipment(id)
    if not item:
        return redirect_to("/equipment")

    logs = getattr(db, "logs", [])
    item_logs = [l for l in logs if getattr(l, "equipmentId", None) == id]
    manager = db.get_user(getattr(item, "managerId", ""))

    ctx.update(
        {
            "page_title": "Chi tiết thiết bị",
            "item": item,
            "manager": manager,
            "logs": item_logs,
        }
    )
    return templates.TemplateResponse("equipment_detail.html", ctx)


@app.get("/equipment-stats", response_class=HTMLResponse)
async def equipment_stats_page(request: Request):
    r = require_staff(request)
    if r:
        return r

    ctx = common_context(request)
    equipment_list = list(getattr(db, "equipment", []))

    total = len(equipment_list)
    by_status: Dict[str, int] = {}
    by_department: Dict[str, int] = {}

    for e in equipment_list:
        st = getattr(e, "status", "UNKNOWN") or "UNKNOWN"
        by_status[st] = by_status.get(st, 0) + 1

        dept = getattr(e, "usingDepartment", None) or "N/A"
        by_department[dept] = by_department.get(dept, 0) + 1

    ctx.update(
        {
            "page_title": "Thống kê thiết bị",
            "total_equipment": total,
            "by_status": by_status,
            "by_department": by_department,
        }
    )
    return templates.TemplateResponse("equipment_stats.html", ctx)


# =========================================================
# Pages: Bookings
# =========================================================

@app.get("/bookings", response_class=HTMLResponse)
async def bookings_page(request: Request):
    ctx = common_context(request)
    user = ctx["current_user"]
    if not user:
        return redirect_to("/login")

    bookings = list(getattr(db, "bookings", []))
    if user.role not in ["ADMIN", "STAFF"]:
        bookings = [b for b in bookings if getattr(b, "userId", None) == user.id]

    enhanced = []
    for b in bookings:
        eq = db.get_equipment(getattr(b, "equipmentId", ""))
        enhanced.append({
            **_to_dict(b),
            "equipmentName": getattr(eq, "name", "Unknown") if eq else "Unknown",
            "equipmentCode": getattr(eq, "code", "") if eq else "",
        })

    logs = list(getattr(db, "logs", []))
    logged_booking_ids = {getattr(l, "bookingId") for l in logs if getattr(l, "bookingId")}

    active_tab = request.query_params.get("tab", "PENDING")
    selected_year = int(request.query_params.get("year", datetime.now().year))

    def filter_by_tab(bookings, tab, logged_ids, year=None):
        if tab == "PENDING":
            return [b for b in bookings if b.get("status") == "PENDING"]
        elif tab == "APPROVED":
            return [b for b in bookings if b.get("status") == "APPROVED"]
        elif tab == "ACTIVE":
            return [b for b in bookings if b.get("status") == "ACTIVE"]
        elif tab == "WAITING_LOG":
            return [b for b in bookings if b.get("status") == "COMPLETED" and b.get("id") not in logged_ids]
        elif tab == "HISTORY":
            filtered = [b for b in bookings if b.get("status") in ["COMPLETED", "CANCELLED", "REJECTED"]]
            if year:
                filtered = [b for b in filtered if datetime.fromisoformat(b["startTime"]).year == year]
            return filtered
        return bookings

    filtered_bookings = filter_by_tab(enhanced, active_tab, logged_booking_ids, selected_year)

    all_logged_ids = logged_booking_ids
    ctx.update({
        "page_title": "Booking List",
        "bookings": enhanced,
        "filtered_bookings": filtered_bookings,
        "active_tab": active_tab,
        "selected_history_year": selected_year,
        "history_years": sorted({datetime.fromisoformat(b["startTime"]).year for b in enhanced if b.get("status") in ["COMPLETED", "CANCELLED", "REJECTED"]}, reverse=True) or [datetime.now().year],
        "pending_count": len([b for b in enhanced if b.get("status") == "PENDING"]),
        "approved_count": len([b for b in enhanced if b.get("status") == "APPROVED"]),
        "active_count": len([b for b in enhanced if b.get("status") == "ACTIVE"]),
        "waiting_log_count": len([b for b in enhanced if b.get("status") == "COMPLETED" and b.get("id") not in all_logged_ids]),
        "history_count": len([b for b in enhanced if b.get("status") in ["COMPLETED", "CANCELLED", "REJECTED"]]),
    })
    return templates.TemplateResponse("bookings.html", ctx)


@app.post("/api/bookings/create")
async def create_booking(request: Request):
    data = await request.json()
    new_booking = Booking(**data)
    if not hasattr(db, "bookings"):
        db.bookings = []
    db.bookings.append(new_booking)
    return {"success": True}


# =========================================================
# Pages: Maintenance
# =========================================================

@app.get("/maintenance", response_class=HTMLResponse)
async def maintenance(request: Request):
    r = require_staff(request)
    if r:
        return r
    ctx = common_context(request)
    ctx.update({"page_title": "Bảo trì & Sửa chữa"})
    return templates.TemplateResponse("maintenance.html", ctx)


@app.get("/maintenance-list", response_class=HTMLResponse)
async def maintenance_list_page(request: Request):
    r = require_staff(request)
    if r:
        return r
    ctx = common_context(request)
    ctx.update({"page_title": "Maintenance List"})
    return templates.TemplateResponse("maintenance_list.html", ctx)


# =========================================================
# Pages: QR Scanner
# =========================================================

@app.get("/scan", response_class=HTMLResponse)
async def qr_scan_page(request: Request):
    ctx = common_context(request)
    ctx.update({"page_title": "Quét QR"})
    return templates.TemplateResponse("qr_scanner.html", ctx)


@app.get("/qr-scanner", response_class=HTMLResponse)
async def qr_scanner_alias(request: Request):
    return await qr_scan_page(request)


# =========================================================
# Pages: Usage Logs
# =========================================================

@app.get("/usage-logs", response_class=HTMLResponse)
async def usage_log_list_page(request: Request):
    r = require_staff(request)
    if r:
        return r
    ctx = common_context(request)
    ctx.update({"page_title": "Usage Logs", "logs": getattr(db, "logs", [])})
    return templates.TemplateResponse("usage_logs.html", ctx)


# =========================================================
# Pages: Inventory
# =========================================================

@app.get("/inventory", response_class=HTMLResponse)
async def inventory_list_page(request: Request):
    r = require_staff(request)
    if r:
        return r
    ctx = common_context(request)
    sessions = getattr(db, "inventorySessions", [])
    ctx.update({"page_title": "Inventory", "inventory_sessions": sessions})
    return templates.TemplateResponse("inventory.html", ctx)


# =========================================================
# Pages: Admin
# =========================================================

@app.get("/admin", response_class=HTMLResponse)
async def admin_panel(request: Request):
    r = require_admin(request)
    if r:
        return r

    ctx = common_context(request)
    users_json = [_to_dict(u) for u in getattr(db, "users", [])]

    ctx.update(
        {
            "page_title": "Quản trị",
            "users": users_json,
        }
    )
    return templates.TemplateResponse("admin.html", ctx)


@app.get("/admin-panel", response_class=HTMLResponse)
async def admin_panel_alias(request: Request):
    return await admin_panel(request)


# =========================================================
# APIs: Inventory (CRUD)
# =========================================================

def _ensure_inventory_store():
    if not hasattr(db, "inventorySessions") or db.inventorySessions is None:
        db.inventorySessions = []


@app.get("/api/inventory/sessions")
async def api_inventory_sessions(request: Request, year: Optional[int] = None):
    r = require_staff(request)
    if r:
        return JSONResponse({"success": False, "message": "Unauthorized"}, status_code=401)

    _ensure_inventory_store()
    sessions = db.inventorySessions

    if year is not None:
        filtered = []
        for s in sessions:
            date_str = s.get("date") if isinstance(s, dict) else getattr(s, "date", None)
            try:
                y = datetime.fromisoformat(date_str).year if date_str else None
            except Exception:
                y = None
            if y == year:
                filtered.append(s)
        sessions = filtered

    return {"success": True, "data": sessions}


@app.post("/api/inventory/sessions")
async def api_inventory_create_session(request: Request):
    r = require_staff(request)
    if r:
        return JSONResponse({"success": False, "message": "Unauthorized"}, status_code=401)

    payload = await request.json()
    _ensure_inventory_store()
    db.inventorySessions.append(payload)
    return {"success": True, "data": payload}


@app.put("/api/inventory/sessions/{session_id}")
async def api_inventory_update_session(request: Request, session_id: str):
    r = require_staff(request)
    if r:
        return JSONResponse({"success": False, "message": "Unauthorized"}, status_code=401)

    payload = await request.json()
    _ensure_inventory_store()

    updated = False
    new_list = []
    for s in db.inventorySessions:
        sid = s.get("id") if isinstance(s, dict) else getattr(s, "id", None)
        if sid == session_id and isinstance(s, dict):
            new_list.append({**s, **payload})
            updated = True
        else:
            new_list.append(s)

    db.inventorySessions = new_list
    return {"success": True, "updated": updated}


@app.delete("/api/inventory/sessions/{session_id}")
async def api_inventory_delete_session(request: Request, session_id: str):
    r = require_staff(request)
    if r:
        return JSONResponse({"success": False, "message": "Unauthorized"}, status_code=401)

    _ensure_inventory_store()

    before = len(db.inventorySessions)
    db.inventorySessions = [
        s for s in db.inventorySessions
        if (s.get("id") if isinstance(s, dict) else getattr(s, "id", None)) != session_id
    ]
    return {"success": True, "deleted": (before - len(db.inventorySessions))}


# =========================================================
# APIs: Basic data
# =========================================================

@app.get("/api/me")
async def api_me(request: Request):
    user = get_current_user(request)
    if not user:
        return JSONResponse({"success": False, "message": "Unauthorized"}, status_code=401)
    return {"success": True, "data": _to_dict(user)}


@app.get("/api/equipment")
async def api_equipment_list(request: Request):
    r = require_login(request)
    if r:
        return JSONResponse({"success": False, "message": "Unauthorized"}, status_code=401)

    items = getattr(db, "equipment", [])
    out = [_to_dict(e) for e in items]
    return {"success": True, "data": out}


@app.get("/api/users")
async def api_users(request: Request):
    r = require_staff(request)
    if r:
        return JSONResponse({"success": False, "message": "Unauthorized"}, status_code=401)

    users = getattr(db, "users", [])
    out = [_to_dict(u) for u in users]
    return {"success": True, "data": out}


@app.get("/api/usage-logs")
async def api_usage_logs(request: Request):
    r = require_staff(request)
    if r:
        return JSONResponse({"success": False, "message": "Unauthorized"}, status_code=401)

    logs = getattr(db, "logs", [])
    out = [_to_dict(l) for l in logs]
    return {"success": True, "data": out}


# =========================================================
# AI Chat API
# =========================================================

@app.post("/api/ai/chat")
async def ai_chat_api(request: Request):
    user = get_current_user(request)
    if not user:
        return JSONResponse({"success": False, "message": "Unauthorized"}, status_code=401)

    if not GOOGLE_API_KEY:
        return JSONResponse({"success": False, "message": "AI chưa được cấu hình."}, status_code=500)

    try:
        data = await request.json()
        user_message = data.get("message", "").strip()
        if not user_message:
            return JSONResponse({"success": False, "message": "Empty message"}, status_code=400)

        equip_summary = "\n".join([
            f"- {getattr(e, 'name', 'N/A')} (Mã: {getattr(e, 'code', 'N/A')}): Vị trí {getattr(e, 'location', 'N/A')}, Trạng thái: {STATUS_TRANS.get(getattr(e, 'status', ''), getattr(e, 'status', ''))}, Mô tả: {getattr(e, 'notes', 'Không có')}"
            for e in getattr(db, "equipment", [])
        ])

        lab_summary = "\n".join([
            f"- {getattr(l, 'name', 'N/A')} ({getattr(l, 'locationCode', 'N/A')}): {getattr(l, 'description', '')}"
            for l in getattr(db, "labs", [])
        ])

        system_prompt = f"""
Bạn là trợ lý AI thông minh cho hệ thống quản lý thiết bị phòng thí nghiệm "SciEquip" của Trường Đại học Y Dược Cần Thơ.

THÔNG TIN NGƯỜI DÙNG HIỆN TẠI:
- Tên: {getattr(user, 'name', 'Ẩn danh')}
- Vai trò: {getattr(user, 'role', 'USER')}
- Phòng ban: {getattr(user, 'department', 'N/A')}

DANH SÁCH THIẾT BỊ HIỆN CÓ:
{equip_summary}

DANH SÁCH PHÒNG LAB:
{lab_summary}

NHIỆM VỤ CỦA BẠN:
1. Trả lời các câu hỏi về vị trí, trạng thái và thông tin của thiết bị.
2. Hỗ trợ người dùng hiểu quy trình đăng ký, báo hỏng (nhắc họ dùng các nút chức năng trên giao diện).
3. Giải thích ngắn gọn các thuật ngữ khoa học nếu được hỏi.
4. Luôn trả lời bằng Tiếng Việt, văn phong lịch sự, ngắn gọn và hữu ích.
5. Nếu người dùng hỏi về thiết bị không có trong danh sách, hãy báo là không tìm thấy.

LƯU Ý: Bạn chỉ là trợ lý tra cứu, bạn không thể trực tiếp thực hiện hành động trên database.
        """

        model = GenerativeModel('gemini-3.0-flash-latest')
        chat = model.start_chat(history=[])
        full_prompt = system_prompt + "\n\nCâu hỏi của người dùng:\n" + user_message
        ai_response = await chat.send_message_async(full_prompt)
        text = ai_response.text.strip()

        return {"success": True, "response": text}

    except Exception as e:
        print("AI Error:", e)
        return JSONResponse({"success": False, "message": "Lỗi máy chủ AI"}, status_code=500)