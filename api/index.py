import os, random, requests, json, smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS

app = Flask(__name__, static_folder='../static')
CORS(app, resources={r"/*": {"origins": "*"}})

BOT_TOKEN  = os.environ.get("BOT_TOKEN", "")
ADMIN_ID   = os.environ.get("ADMIN_CHAT_ID", "")
EMAIL_USER = os.environ.get("EMAIL_USER", "")
EMAIL_PASS = os.environ.get("EMAIL_PASSWORD", "")
GEMINI_KEY = os.environ.get("GEMINI_KEY", "")
SB_URL     = os.environ.get("SUPABASE_URL", "")
SB_KEY     = os.environ.get("SUPABASE_SERVICE_KEY", "")

# ── Supabase через прямі HTTP запити (без бібліотеки) ──────────
SB_HEADERS = {
    "apikey": SB_KEY,
    "Authorization": f"Bearer {SB_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=representation"
}

def sb_select(table, filters=""):
    url = f"{SB_URL}/rest/v1/{table}?{filters}"
    r = requests.get(url, headers=SB_HEADERS, timeout=10)
    return r.json() if r.ok else []

def sb_insert(table, data):
    url = f"{SB_URL}/rest/v1/{table}"
    r = requests.post(url, headers=SB_HEADERS, json=data, timeout=10)
    return r.json() if r.ok else []

def sb_delete(table, filters):
    url = f"{SB_URL}/rest/v1/{table}?{filters}"
    r = requests.delete(url, headers=SB_HEADERS, timeout=10)
    return r.ok

def sb_upsert(table, data, on_conflict):
    url = f"{SB_URL}/rest/v1/{table}?on_conflict={on_conflict}"
    headers = {**SB_HEADERS, "Prefer": "resolution=merge-duplicates,return=representation"}
    r = requests.post(url, headers=headers, json=data, timeout=10)
    return r.json() if r.ok else []

# ── Email ──────────────────────────────────────────────────────
def send_email_code(target_email, code):
    try:
        msg = MIMEMultipart()
        msg['From']    = EMAIL_USER
        msg['To']      = target_email
        msg['Subject'] = "Код підтвердження LUNXET"
        body = f"""<html><body style="font-family:Arial,sans-serif;text-align:center;">
            <h2>Ваш код входу в LUNXET MART</h2>
            <div style="font-size:32px;font-weight:bold;color:#cdef2e;background:#111;padding:20px;display:inline-block;border-radius:10px;">{code}</div>
        </body></html>"""
        msg.attach(MIMEText(body, 'html'))
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(EMAIL_USER, EMAIL_PASS)
            server.sendmail(EMAIL_USER, target_email, msg.as_string())
        return True
    except Exception as e:
        print(f"Email error: {e}")
        return False

# ── Маршрути ───────────────────────────────────────────────────
@app.route('/')
def index():
    return send_from_directory('../static', 'sitr.html')

@app.route('/ai-helper')
def ai_helper():
    return send_from_directory('../static', 'ai.html')

@app.route('/static/<path:filename>')
def static_files(filename):
    return send_from_directory('../static', filename)

@app.route('/api/products', methods=['GET'])
def get_products():
    try:
        rows = sb_select('products', 'active=eq.true&select=*')
        products = []
        for row in rows:
            products.append({
                'name':   row.get('name', ''),
                'price':  row.get('price', 0),
                'desc':   row.get('description', ''),
                'cat':    row.get('category', ''),
                'sizes':  row.get('sizes', []),
                'images': row.get('images', [])
            })
        return jsonify(products)
    except Exception as e:
        print(f"Products error: {e}")
        return jsonify([])

@app.route('/api/auth/request', methods=['POST', 'OPTIONS'])
def send_auth_code():
    if request.method == 'OPTIONS':
        return jsonify({"success": True}), 200
    data    = request.json or {}
    contact = data.get('contact', '').strip()
    if not contact:
        return jsonify({"success": False, "message": "Вкажіть контакт"}), 400

    code = str(random.randint(1000, 9999))

    sb_delete('auth_codes', f'contact=eq.{contact}')
    sb_insert('auth_codes', {'contact': contact, 'code': code})

    if "@" in contact:
        if send_email_code(contact, code):
            return jsonify({"success": True})
        return jsonify({"success": False, "message": "Помилка Email"}), 500
    else:
        try:
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
            msg = f"🔑 Код LUNXET: <b>{code}</b>\n👤 {contact}"
            requests.post(url, json={"chat_id": ADMIN_ID, "text": msg, "parse_mode": "HTML"}, timeout=5)
            return jsonify({"success": True})
        except Exception as e:
            return jsonify({"success": False, "message": "Помилка Telegram"}), 500

@app.route('/api/auth/verify', methods=['POST', 'OPTIONS'])
def verify_auth_code():
    if request.method == 'OPTIONS':
        return jsonify({"success": True}), 200
    data    = request.json or {}
    contact = data.get('contact', '').strip()
    code    = data.get('code', '').strip()

    try:
        rows = sb_select('auth_codes', f'contact=eq.{contact}&code=eq.{code}')
        if rows:
            sb_delete('auth_codes', f'contact=eq.{contact}')
            sb_upsert('users', {'contact': contact}, 'contact')
            return jsonify({"success": True})
        return jsonify({"success": False, "message": "Невірний код"}), 401
    except Exception as e:
        print(f"Verify error: {e}")
        return jsonify({"success": False, "message": "Помилка сервера"}), 500

@app.route('/api/generate-look', methods=['POST', 'OPTIONS'])
def generate_look():
    if request.method == 'OPTIONS':
        return jsonify({"success": True}), 200
    try:
        data        = request.json or {}
        height      = data.get('height', '170')
        hair        = data.get('hair', 'brunette')
        gender      = data.get('gender', 'female')
        style       = data.get('style', 'casual')
        outfit_type = data.get('outfit_type', 'full outfit')

        rows      = sb_select('products', 'active=eq.true&select=name,category')
        inventory = ", ".join([r.get('name', '') for r in rows])

        prompt = f"""Ти стиліст магазину LUNXET.
Клієнт: стать={gender}, зріст={height}см, волосся={hair}, стиль={style}.
Запит: {outfit_type}. Товари: {inventory}.
Відповідь ТІЛЬКИ JSON:
{{"items":["назва"],"visual_prompt":"fashion photo prompt english","advice":"порада українською"}}"""

        resp = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_KEY}",
            json={"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"temperature": 0.7, "maxOutputTokens": 512}},
            timeout=15
        )
        resp.raise_for_status()
        raw = resp.json()['candidates'][0]['content']['parts'][0]['text'].strip()
        if "```json" in raw:
            raw = raw.split("```json")[1].split("```")[0].strip()
        elif "```" in raw:
            raw = raw.split("```")[1].split("```")[0].strip()
        return jsonify(json.loads(raw))
    except Exception as e:
        print(f"generate-look error: {e}")
        return jsonify({"items": ["Помилка AI"], "visual_prompt": "fashion model", "advice": str(e)}), 200

@app.route('/api/orders', methods=['POST', 'OPTIONS'])
def create_order():
    if request.method == 'OPTIONS':
        return jsonify({"success": True}), 200
    data     = request.json or {}
    order_id = str(random.randint(10000, 99999))
    try:
        sb_insert('orders', {
            'order_uid':    order_id,
            'user_contact': data.get('user', 'guest'),
            'items':        data.get('items', []),
            'total':        data.get('total', 0),
            'address':      data.get('address', '')
        })
    except Exception as e:
        print(f"Orders error: {e}")
    try:
        items      = data.get('items', [])
        items_text = "\n".join([f"• {i.get('name','?')} — {i.get('price',0)} ₴" for i in items])
        msg        = f"🛒 <b>Замовлення #{order_id}</b>\n👤 {data.get('user','guest')}\n{items_text}\n💰 {data.get('total',0)} ₴\n📍 {data.get('address','')}"
        requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={"chat_id": ADMIN_ID, "text": msg, "parse_mode": "HTML"}, timeout=5)
    except:
        pass
    return jsonify({"success": True, "order_id": order_id})
