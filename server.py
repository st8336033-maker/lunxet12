import os, random, requests, json, smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

# ── Конфіг ──────────────────────────────────────────────────
BOT_TOKEN  = os.getenv("BOT_TOKEN")
ADMIN_ID   = os.getenv("ADMIN_CHAT_ID")
EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASS = os.getenv("EMAIL_PASSWORD")
GEMINI_KEY = os.getenv("GEMINI_KEY")
SB_URL     = os.getenv("SUPABASE_URL")
SB_KEY     = os.getenv("SUPABASE_SERVICE_KEY")

sb = create_client(SB_URL, SB_KEY)

# ── Email ────────────────────────────────────────────────────
def send_email_code(target_email, code):
    try:
        msg = MIMEMultipart()
        msg['From']    = EMAIL_USER
        msg['To']      = target_email
        msg['Subject'] = "Код підтвердження LUNXET"
        body = f"""
        <html><body style="font-family:Arial,sans-serif;text-align:center;">
            <h2 style="color:#111;">Ваш код входу в LUNXET MART</h2>
            <div style="font-size:32px;font-weight:bold;color:#cdef2e;background:#111;padding:20px;display:inline-block;border-radius:10px;">
                {code}
            </div>
            <p style="color:#888;margin-top:15px;">Код дійсний 10 хвилин</p>
        </body></html>"""
        msg.attach(MIMEText(body, 'html'))
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(EMAIL_USER, EMAIL_PASS)
            server.sendmail(EMAIL_USER, target_email, msg.as_string())
        return True
    except Exception as e:
        print(f"❌ Email error: {e}")
        return False

# ── Маршрути ─────────────────────────────────────────────────

@app.route('/')
def index():
    return send_from_directory('static', 'sitr.html')

@app.route('/ai-helper')
def ai_helper():
    return send_from_directory('static', 'ai.html')

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory('uploads', filename)

@app.route('/static/uploads/<filename>')
def static_uploads(filename):
    return send_from_directory('static/uploads', filename)

# ── Товари (читаємо з Supabase) ──────────────────────────────
@app.route('/api/products', methods=['GET'])
def get_products():
    try:
        result = sb.table('products').select('*').eq('active', True).execute()
        products = []
        for row in result.data:
            products.append({
                'name':   row['name'],
                'price':  row['price'],
                'desc':   row.get('description', ''),
                'cat':    row.get('category', ''),
                'sizes':  row.get('sizes', []),
                'images': row.get('images', [])
            })
        return jsonify(products)
    except Exception as e:
        print(f"❌ Products error: {e}")
        return jsonify([])

# ── Авторизація: надіслати код ────────────────────────────────
@app.route('/api/auth/request', methods=['POST', 'OPTIONS'])
def send_auth_code():
    if request.method == 'OPTIONS':
        return jsonify({"success": True}), 200

    data    = request.json or {}
    contact = data.get('contact', '').strip()
    if not contact:
        return jsonify({"success": False, "message": "Вкажіть контакт"}), 400

    code = str(random.randint(1000, 9999))

    try:
        # Зберігаємо код в Supabase (видаляємо старі для цього контакту)
        sb.table('auth_codes').delete().eq('contact', contact).execute()
        sb.table('auth_codes').insert({'contact': contact, 'code': code}).execute()
    except Exception as e:
        print(f"❌ Supabase auth_codes error: {e}")

    if "@" in contact:
        if send_email_code(contact, code):
            return jsonify({"success": True})
        else:
            return jsonify({"success": False, "message": "Помилка Email"}), 500
    else:
        try:
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
            msg = f"🔑 Код LUNXET: <b>{code}</b>\n👤 Користувач: {contact}"
            requests.post(url, json={"chat_id": ADMIN_ID, "text": msg, "parse_mode": "HTML"}, timeout=5)
            return jsonify({"success": True})
        except Exception as e:
            return jsonify({"success": False, "message": "Помилка Telegram"}), 500

# ── Авторизація: перевірити код ───────────────────────────────
@app.route('/api/auth/verify', methods=['POST', 'OPTIONS'])
def verify_auth_code():
    if request.method == 'OPTIONS':
        return jsonify({"success": True}), 200

    data    = request.json or {}
    contact = data.get('contact', '').strip()
    code    = data.get('code', '').strip()

    try:
        result = sb.table('auth_codes')\
            .select('*')\
            .eq('contact', contact)\
            .eq('code', code)\
            .execute()

        if result.data:
            # Видаляємо використаний код
            sb.table('auth_codes').delete().eq('contact', contact).execute()
            # Upsert користувача
            sb.table('users').upsert({'contact': contact}, on_conflict='contact').execute()
            return jsonify({"success": True})
        else:
            return jsonify({"success": False, "message": "Невірний код"}), 401
    except Exception as e:
        print(f"❌ Verify error: {e}")
        return jsonify({"success": False, "message": "Помилка сервера"}), 500

# ── AI генерація ──────────────────────────────────────────────
@app.route('/api/generate-look', methods=['POST', 'OPTIONS'])
def generate_look():
    if request.method == 'OPTIONS':
        return jsonify({"success": True}), 200

    try:
        data         = request.json or {}
        height       = data.get('height', '170')
        hair         = data.get('hair', 'brunette')
        gender       = data.get('gender', 'female')
        style        = data.get('style', 'casual')
        outfit_type  = data.get('outfit_type', 'full outfit')

        # Завантажуємо товари з Supabase
        products_res = sb.table('products').select('name, category, price').eq('active', True).execute()
        products     = products_res.data or []
        inventory    = ", ".join([f"{p['name']} ({p.get('category','')})" for p in products])

        prompt = f"""Ти стиліст магазину LUNXET. 
Клієнт: стать={gender}, зріст={height}см, волосся={hair}, стиль={style}.
Запит: {outfit_type}. Товари в наявності: {inventory}.
Поверни відповідь ТІЛЬКИ у форматі JSON без зайвих слів:
{{
  "items": ["назва товару"],
  "visual_prompt": "fashion photo prompt in English",
  "advice": "порада українською"
}}"""

        # Gemini API
        gemini_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_KEY}"
        resp = requests.post(gemini_url, json={
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.7, "maxOutputTokens": 512}
        }, timeout=15)
        resp.raise_for_status()

        raw = resp.json()['candidates'][0]['content']['parts'][0]['text'].strip()

        if "```json" in raw:
            raw = raw.split("```json")[1].split("```")[0].strip()
        elif "```" in raw:
            raw = raw.split("```")[1].split("```")[0].strip()

        final_data = json.loads(raw)
        return jsonify(final_data)

    except Exception as e:
        print(f"❌ generate-look error: {e}")
        return jsonify({
            "items":         ["Помилка AI"],
            "visual_prompt": "fashion model streetwear",
            "advice":        f"Помилка: {str(e)}"
        }), 200

# ── Замовлення ────────────────────────────────────────────────
@app.route('/api/orders', methods=['POST', 'OPTIONS'])
def create_order():
    if request.method == 'OPTIONS':
        return jsonify({"success": True}), 200

    data         = request.json or {}
    user_contact = data.get('user', 'guest')
    items        = data.get('items', [])
    total        = data.get('total', 0)
    address      = data.get('address', '')

    order_id = str(random.randint(10000, 99999))

    try:
        sb.table('orders').insert({
            'order_uid':    order_id,
            'user_contact': user_contact,
            'items':        items,
            'total':        total,
            'address':      address
        }).execute()
    except Exception as e:
        print(f"❌ Orders error: {e}")

    # Telegram сповіщення
    try:
        items_text = "\n".join([f"• {i.get('name','?')} — {i.get('price',0)} ₴" for i in items])
        msg = f"🛒 <b>Замовлення #{order_id}</b>\n👤 {user_contact}\n{items_text}\n💰 Разом: {total} ₴\n📍 {address}"
        requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={"chat_id": ADMIN_ID, "text": msg, "parse_mode": "HTML"},
            timeout=5
        )
    except:
        pass

    return jsonify({"success": True, "order_id": order_id})

if __name__ == '__main__':
    os.makedirs('uploads', exist_ok=True)
    os.makedirs('static/uploads', exist_ok=True)
    app.run(debug=True, port=5000)
