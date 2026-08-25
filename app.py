from flask import Flask, render_template, request, redirect, session
import db
import hashlib
from datetime import datetime, timedelta
import traceback, sys
import os
from email_service import (send_booking_confirmation, send_reminder,
                           send_invoice, send_email, get_settings,
                           smtp_configured, refresh_clinic_name, get_clinic_name)

app = Flask(__name__)
app.secret_key = 'dental_clinic_secret_key_2026'

DEFAULT_PRICES = {'consultation': 150, 'urgent': 250, 'surgery': 500}

CLINIC_DEFAULTS = {
    'clinic_name': 'عيادة دنتال كير',
    'branches': 'مصر الجديدة\nمدينة نصر\nالمعادي',
    'whatsapp': '201000000000',
    'facebook': 'https://facebook.com/DentalCare',
    'instagram': 'https://instagram.com/DentalCare',
    'clinic_email': '',
}

def hash_password(password):
    return hashlib.sha256(password.encode('utf-8')).hexdigest()

def get_setting(key, default=''):
    s = get_settings()
    return s.get(key, default)

def get_clinic():
    """بيانات العيادة من الإعدادات مع القيم الافتراضية"""
    s = get_settings()
    data = dict(CLINIC_DEFAULTS)
    for key in data:
        if s.get(key):
            data[key] = s[key]
    data['name'] = data['clinic_name']
    data['branch_list'] = [b.strip() for b in data['branches'].split('\n') if b.strip()]
    return data

def verify_admin_password(password):
    stored = get_setting('admin_password_hash')
    if not stored:
        return password == 'admin123'
    return hash_password(password) == stored

def get_price(booking_type):
    """قراءة سعر نوع الحجز من الإعدادات مع الرجوع للسعر الافتراضي"""
    prices = get_settings()
    return float(prices.get(f'price_{booking_type}', DEFAULT_PRICES.get(booking_type, 0)))

def init_db():
    conn = db.connect()
    c = conn.cursor()
    db.init_schema(c)
    try:
        c.execute("ALTER TABLE patients ADD COLUMN email TEXT DEFAULT ''")
    except Exception:
        pass
    for key, value in CLINIC_DEFAULTS.items():
        db.set_setting(c, key, value, ignore_existing=True)
    db.set_setting(c, 'admin_password_hash', hash_password('admin123'), ignore_existing=True)
    conn.commit()
    conn.close()

init_db()

@app.context_processor
def inject_clinic():
    """بيانات العيادة متاحة تلقائياً في كل القوالب"""
    return {'clinic': get_clinic()}

@app.errorhandler(500)
def internal_error(e):
    traceback.print_exc(file=sys.stdout)
    sys.stdout.flush()
    return "Internal Server Error", 500

# ---------- الصفحة الرئيسية ----------
@app.route('/')
def home():
    return render_template('home.html')

# ---------- صفحة حجز الموعد ----------
@app.route('/book')
def booking_form():
    booking_type = request.args.get('type', 'consultation')
    return render_template('booking.html', booking_type=booking_type)

# ---------- معالجة الحجز ----------
@app.route('/book', methods=['POST'])
def book():
    name = request.form['name']
    age = str(request.form.get('age', '')).strip()
    age = int(age) if age.isdigit() else None
    gender = request.form['gender']
    painkiller = ''
    address = request.form['address']
    email = request.form.get('email', '').strip()
    booking_type = request.form['booking_type']

    conn = db.connect()
    c = conn.cursor()
    patient_id = db.insert_returning_id(c, '''
        INSERT INTO patients (name, age, gender, painkiller, address, email, booking_type)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (name, age, gender, painkiller, address, email, booking_type))

    appointment_date, appointment_time = find_next_available_slot(c)

    c.execute('''
        INSERT INTO appointments (patient_id, appointment_date, appointment_time)
        VALUES (?, ?, ?)
    ''', (patient_id, appointment_date, appointment_time))
    conn.commit()
    conn.close()

    if email and smtp_configured():
        ok, msg = send_booking_confirmation(name, email, appointment_date, appointment_time)
        if not ok:
            print(f"[email] تأكيد الحجز فشل: {msg}")

    return f'''
    <html dir="rtl" lang="ar">
    <head><meta charset="UTF-8"><title>تم الحجز</title>
    <style>
        body {{ font-family: 'Segoe UI'; background: #f0f4f8; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; }}
        .card {{ background: white; padding: 30px; border-radius: 15px; box-shadow: 0 4px 8px rgba(0,0,0,0.2); text-align: center; }}
        h2 {{ color: #0077b6; }}
        .details {{ text-align: right; margin: 20px 0; line-height: 2; }}
        a {{ display: inline-block; margin-top: 20px; padding: 10px 20px; background: #0077b6; color: white; text-decoration: none; border-radius: 8px; }}
    </style></head>
    <body>
        <div class="card">
            <h2>✅ تم حجز الموعد بنجاح!</h2>
            <div class="details">
                <p><strong>الاسم:</strong> {name}</p>
                <p><strong>نوع الحجز:</strong> {booking_type}</p>
                <p><strong>تشخيص الحالة:</strong> {address}</p>
                <p><strong>التاريخ:</strong> {appointment_date}</p>
                <p><strong>الوقت:</strong> {appointment_time}</p>
            </div>
            <a href="/">العودة للرئيسية</a>
        </div>
    </body>
    </html>
    '''

def find_next_available_slot(c):
    """البحث عن أول موعد متاح (الأحد-الخميس، 9ص-5م)"""
    today = datetime.now().date()
    check_date = today + timedelta(days=1)
    work_days = [0, 1, 2, 3, 6]  # Mon-Thu + Sun

    for _ in range(60):
        if check_date.weekday() in work_days:
            for hour in range(9, 17):
                time_str = f"{hour:02d}:00"
                date_str = check_date.strftime("%Y-%m-%d")
                c.execute('''
                    SELECT COUNT(*) FROM appointments
                    WHERE appointment_date = ? AND appointment_time = ?
                ''', (date_str, time_str))
                if c.fetchone()[0] == 0:
                    return date_str, time_str
        check_date += timedelta(days=1)
    return "غير متاح", "غير متاح"

# ====================== Admin Routes ======================
@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        if verify_admin_password(request.form['password']):
            session['admin'] = True
            return redirect('/admin/dashboard')
        else:
            return render_template('admin_login.html', error='كلمة المرور غير صحيحة')
    return render_template('admin_login.html')

@app.route('/admin/logout')
def admin_logout():
    session.pop('admin', None)
    return redirect('/admin/login')

@app.route('/admin/dashboard')
def admin_dashboard():
    if not session.get('admin'):
        return redirect('/admin/login')
    conn = db.connect()
    c = conn.cursor()
    # استخدام تاريخ اليوم بصيغة نصية لتجنب مشاكل التوقيت
    today_str = datetime.now().date().strftime('%Y-%m-%d')
    c.execute('''
        SELECT a.id, p.name, p.booking_type, a.appointment_date, a.appointment_time, p.address, a.status, p.email
        FROM appointments a
        JOIN patients p ON a.patient_id = p.id
        WHERE a.appointment_date >= ?
        ORDER BY a.appointment_date, a.appointment_time
    ''', (today_str,))
    appointments = c.fetchall()
    conn.close()
    return render_template('admin_dashboard.html', appointments=appointments)

@app.route('/admin/cancel/<int:appointment_id>')
def admin_cancel(appointment_id):
    if not session.get('admin'):
        return redirect('/admin/login')
    conn = db.connect()
    c = conn.cursor()
    c.execute('DELETE FROM appointments WHERE id=?', (appointment_id,))
    conn.commit()
    conn.close()
    return redirect('/admin/dashboard')

@app.route('/admin/edit/<int:appointment_id>', methods=['GET', 'POST'])
def admin_edit(appointment_id):
    if not session.get('admin'):
        return redirect('/admin/login')
    conn = db.connect()
    c = conn.cursor()
    if request.method == 'POST':
        new_date = request.form['new_date']
        new_time = request.form['new_time']
        c.execute('UPDATE appointments SET appointment_date=?, appointment_time=? WHERE id=?',
                  (new_date, new_time, appointment_id))
        conn.commit()
        conn.close()
        return redirect('/admin/dashboard')
    else:
        c.execute('SELECT appointment_date, appointment_time FROM appointments WHERE id=?', (appointment_id,))
        row = c.fetchone()
        conn.close()
        if row:
            return render_template('admin_edit.html', appointment_id=appointment_id,
                                   current_date=row[0], current_time=row[1])
        else:
            return "غير موجود", 404

# ====================== إعدادات الأسعار ======================
@app.route('/admin/prices', methods=['GET', 'POST'])
def admin_prices():
    if not session.get('admin'):
        return redirect('/admin/login')
    msg = ''
    if request.method == 'POST':
        conn = db.connect()
        c = conn.cursor()
        for key in ['price_consultation', 'price_urgent', 'price_surgery']:
            val = request.form.get(key, '').strip()
            if val:
                db.set_setting(c, key, val)
        conn.commit()
        conn.close()
        msg = '✅ تم حفظ الأسعار'
    prices = {k: get_price(k) for k in DEFAULT_PRICES}
    return render_template('admin_prices.html', prices=prices, msg=msg)

# ====================== إعدادات العيادة والبريد ======================
@app.route('/admin/settings', methods=['GET', 'POST'])
def admin_settings():
    if not session.get('admin'):
        return redirect('/admin/login')
    msg = ''
    if request.method == 'POST':
        profile_keys = list(CLINIC_DEFAULTS.keys()) + ['smtp_email', 'smtp_password',
                                                       'smtp_host', 'smtp_port', 'smtp_secure']
        conn = db.connect()
        c = conn.cursor()
        for key in profile_keys:
            val = request.form.get(key)
            if val is not None and val.strip() != '':
                db.set_setting(c, key, val.strip())
            elif key in ('smtp_email', 'smtp_password', 'smtp_host', 'smtp_port', 'smtp_secure') and val is not None:
                db.set_setting(c, key, '')
        conn.commit()
        conn.close()
        refresh_clinic_name()
        msg = '✅ تم حفظ الإعدادات'
    settings = get_settings()
    return render_template('admin_settings.html', settings=settings, msg=msg)

@app.route('/admin/change_password', methods=['POST'])
def admin_change_password():
    if not session.get('admin'):
        return redirect('/admin/login')
    current = request.form.get('current_password', '')
    new = request.form.get('new_password', '')
    confirm = request.form.get('confirm_password', '')
    if not verify_admin_password(current):
        msg = '❌ كلمة المرور الحالية غير صحيحة'
    elif len(new) < 6:
        msg = '❌ كلمة المرور الجديدة قصيرة جداً (6 أحرف على الأقل)'
    elif new != confirm:
        msg = '❌ كلمتا المرور غير متطابقتين'
    else:
        conn = db.connect()
        c = conn.cursor()
        db.set_setting(c, 'admin_password_hash', hash_password(new))
        conn.commit()
        conn.close()
        msg = '✅ تم تغيير كلمة المرور بنجاح'
    return render_template('admin_settings.html', settings=get_settings(), msg=msg)

@app.route('/admin/settings/test', methods=['POST'])
def admin_settings_test():
    if not session.get('admin'):
        return redirect('/admin/login')
    test_email = request.form.get('test_email', '').strip()
    if not test_email:
        return redirect('/admin/settings')
    ok, msg = send_email(test_email, f'🔧 بريد تجريبي - {get_clinic_name()}',
                         '<html dir="rtl"><body style="font-family:Segoe UI;"><h3>✅ تم إرسال هذا البريد التجريبي بنجاح</h3><p>إعدادات البريد تعمل بشكل صحيح.</p></body></html>')
    return render_template('admin_settings.html', settings=get_settings(),
                           msg=f'📧 بريد تجريبي: {"✅ " + msg if ok else "❌ " + msg}')

# ====================== التذكيرات ======================
@app.route('/admin/remind/<int:appointment_id>')
def admin_remind(appointment_id):
    if not session.get('admin'):
        return redirect('/admin/login')
    conn = db.connect()
    c = conn.cursor()
    c.execute('''
        SELECT p.name, p.email, a.appointment_date, a.appointment_time, p.booking_type
        FROM appointments a JOIN patients p ON a.patient_id = p.id
        WHERE a.id = ?
    ''', (appointment_id,))
    row = c.fetchone()
    conn.close()
    if not row:
        return "الموعد غير موجود", 404
    name, email, date, time, booking_type = row
    if not email:
        return render_template('admin_settings.html', settings=get_settings(),
                               msg='⚠️ هذا المريض لا يمتلك بريداً إلكترونياً')
    ok, msg = send_reminder(name, email, date, time, booking_type)
    return render_template('admin_settings.html', settings=get_settings(),
                           msg=f'📧 تذكير: {"✅ " + msg if ok else "❌ " + msg}')

def send_daily_reminders():
    """إرسال تذكير تلقائي لكل موعد غد"""
    if not smtp_configured():
        print('[reminder] SMTP غير مضبوط - تخطي الإرسال التلقائي')
        return
    tomorrow = (datetime.now().date() + timedelta(days=1)).strftime('%Y-%m-%d')
    conn = db.connect()
    c = conn.cursor()
    c.execute('''
        SELECT p.name, p.email, a.id, a.appointment_date, a.appointment_time, p.booking_type
        FROM appointments a JOIN patients p ON a.patient_id = p.id
        WHERE a.appointment_date = ? AND a.status = 'محجوز' AND p.email != ''
    ''', (tomorrow,))
    rows = c.fetchall()
    conn.close()
    sent = 0
    for name, email, appt_id, date, time, booking_type in rows:
        ok, msg = send_reminder(name, email, date, time, booking_type)
        if ok:
            sent += 1
            print(f'[reminder] تم إرسال تذكير للموعد #{appt_id} ({name})')
        else:
            print(f'[reminder] فشل إرسال تذكير للموعد #{appt_id}: {msg}')
    print(f'[reminder] أُرسل {sent} تذكيراً لمواعيد {tomorrow}')

def start_scheduler():
    from apscheduler.schedulers.background import BackgroundScheduler
    scheduler = BackgroundScheduler(daemon=True)
    scheduler.add_job(send_daily_reminders, 'cron', hour=9, minute=0, id='daily_reminders')
    scheduler.start()
    print('[scheduler] بدأ المجدول اليومي (تذكير 9:00 صباحاً)')

if not app.debug or os.environ.get('WERKZEUG_RUN_MAIN') == 'true':
    try:
        start_scheduler()
    except Exception as e:
        print(f'[scheduler] تعذر البدء: {e}')

# ====================== نظام الفواتير ======================
@app.route('/admin/complete/<int:appointment_id>')
def admin_complete(appointment_id):
    if not session.get('admin'):
        return redirect('/admin/login')
    conn = db.connect()
    c = conn.cursor()
    c.execute('''
        SELECT a.patient_id, p.booking_type, a.appointment_date
        FROM appointments a JOIN patients p ON a.patient_id = p.id
        WHERE a.id = ?
    ''', (appointment_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        return "الموعد غير موجود", 404
    patient_id, booking_type, appointment_date = row
    c.execute('UPDATE appointments SET status=? WHERE id=?', ('مكتمل', appointment_id))
    invoice_id = db.insert_returning_id(c, '''
        INSERT INTO invoices (patient_id, appointment_id, created_at)
        VALUES (?, ?, ?)
    ''', (patient_id, appointment_id, datetime.now().strftime('%Y-%m-%d %H:%M')))
    service_ar = {'consultation': 'فحص واستشارة', 'urgent': 'حالة طارئة', 'surgery': 'عملية جراحية'}.get(booking_type, booking_type)
    default_price = get_price(booking_type)
    c.execute('INSERT INTO invoice_items (invoice_id, description, price) VALUES (?, ?, ?)',
              (invoice_id, service_ar, default_price))
    c.execute('UPDATE invoices SET total = (SELECT COALESCE(SUM(price),0) FROM invoice_items WHERE invoice_id=?) WHERE id=?',
              (invoice_id, invoice_id))
    conn.commit()
    conn.close()
    return redirect(f'/admin/invoices/{invoice_id}')

@app.route('/admin/invoices')
def admin_invoices():
    if not session.get('admin'):
        return redirect('/admin/login')
    conn = db.connect()
    c = conn.cursor()
    c.execute('''
        SELECT i.id, p.name, i.created_at, i.total, i.status, a.appointment_date
        FROM invoices i
        JOIN patients p ON i.patient_id = p.id
        LEFT JOIN appointments a ON i.appointment_id = a.id
        ORDER BY i.id DESC
    ''')
    invoices = c.fetchall()
    conn.close()
    return render_template('admin_invoices.html', invoices=invoices)

@app.route('/admin/invoices/<int:invoice_id>', methods=['GET', 'POST'])
def admin_invoice(invoice_id):
    if not session.get('admin'):
        return redirect('/admin/login')
    if request.method == 'POST':
        action = request.form.get('action')
        conn = db.connect()
        c = conn.cursor()
        if action == 'add_item':
            description = request.form.get('description', '').strip()
            price = float(request.form.get('price', 0) or 0)
            if description:
                c.execute('INSERT INTO invoice_items (invoice_id, description, price) VALUES (?, ?, ?)',
                          (invoice_id, description, price))
        elif action == 'delete_item':
            item_id = request.form.get('item_id')
            c.execute('DELETE FROM invoice_items WHERE id=? AND invoice_id=?', (item_id, invoice_id))
        elif action == 'toggle_status':
            c.execute("UPDATE invoices SET status = CASE WHEN status='مدفوعة' THEN 'غير مدفوعة' ELSE 'مدفوعة' END WHERE id=?",
                      (invoice_id,))
        c.execute('UPDATE invoices SET total = (SELECT COALESCE(SUM(price),0) FROM invoice_items WHERE invoice_id=?) WHERE id=?',
                  (invoice_id, invoice_id))
        conn.commit()
        conn.close()
        return redirect(f'/admin/invoices/{invoice_id}')
    conn = db.connect()
    c = conn.cursor()
    c.execute('''
        SELECT i.id, p.name, p.email, i.created_at, i.total, i.status, i.appointment_id
        FROM invoices i JOIN patients p ON i.patient_id = p.id
        WHERE i.id = ?
    ''', (invoice_id,))
    inv = c.fetchone()
    if not inv:
        conn.close()
        return "الفاتورة غير موجودة", 404
    c.execute('SELECT id, description, price FROM invoice_items WHERE invoice_id=?', (invoice_id,))
    items = c.fetchall()
    conn.close()
    return render_template('admin_invoice.html', inv=inv, items=items)

@app.route('/admin/invoices/<int:invoice_id>/delete')
def admin_invoice_delete(invoice_id):
    if not session.get('admin'):
        return redirect('/admin/login')
    conn = db.connect()
    c = conn.cursor()
    c.execute('DELETE FROM invoice_items WHERE invoice_id=?', (invoice_id,))
    c.execute('DELETE FROM invoices WHERE id=?', (invoice_id,))
    conn.commit()
    conn.close()
    return redirect('/admin/invoices')

@app.route('/admin/invoices/<int:invoice_id>/email')
def admin_invoice_email(invoice_id):
    if not session.get('admin'):
        return redirect('/admin/login')
    conn = db.connect()
    c = conn.cursor()
    c.execute('''
        SELECT p.name, p.email, a.appointment_date
        FROM invoices i JOIN patients p ON i.patient_id = p.id
        LEFT JOIN appointments a ON i.appointment_id = a.id
        WHERE i.id = ?
    ''', (invoice_id,))
    row = c.fetchone()
    conn.close()
    if not row:
        return "الفاتورة غير موجودة", 404
    name, email, appointment_date = row
    if not email:
        return render_template('admin_settings.html', settings=get_settings(),
                               msg='⚠️ هذا المريض لا يمتلك بريداً إلكترونياً')
    pdf_path = generate_invoice_pdf(invoice_id)
    ok, msg = send_invoice(name, email, invoice_id, appointment_date or '—', pdf_path)
    return render_template('admin_settings.html', settings=get_settings(),
                           msg=f'📧 فاتورة #{invoice_id}: {"✅ " + msg if ok else "❌ " + msg}')

# ====================== فاتورة PDF ======================
from fpdf import FPDF
import arabic_reshaper
from bidi.algorithm import get_display

def find_arabic_font():
    """البحث عن خط عربي: الملف المرفق مع المشروع أولاً ثم خطوط النظام"""
    bundled = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fonts', 'Amiri-Regular.ttf')
    if os.path.exists(bundled):
        return bundled
    for candidate in [r'C:\Windows\Fonts\arial.ttf', '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf']:
        if os.path.exists(candidate):
            return candidate
    return None

class InvoicePDF(FPDF):
    def add_arabic_font(self):
        font_path = find_arabic_font()
        if font_path:
            self.add_font('Arabic', '', font_path, uni=True)
            return True
        return False

def generate_invoice_pdf(invoice_id):
    conn = db.connect()
    c = conn.cursor()
    c.execute('''
        SELECT p.name, p.email, p.address, i.created_at, i.total, i.status, a.appointment_date
        FROM invoices i JOIN patients p ON i.patient_id = p.id
        LEFT JOIN appointments a ON i.appointment_id = a.id
        WHERE i.id = ?
    ''', (invoice_id,))
    inv = c.fetchone()
    c.execute('SELECT description, price FROM invoice_items WHERE invoice_id=?', (invoice_id,))
    items = c.fetchall()
    conn.close()
    if not inv:
        return None
    name, email, address, created_at, total, status, appt_date = inv

    pdf = InvoicePDF()
    pdf.add_page()
    if not pdf.add_arabic_font():
        print('[invoice] مفيش خط عربي متاح')
        return None
    pdf.set_font('Arabic', '', 16)
    pdf.cell(0, 12, get_display(arabic_reshaper.reshape(f'{get_clinic_name()} - فاتورة علاج')), align='C')
    pdf.ln(14)
    pdf.set_font('Arabic', '', 12)
    pdf.cell(0, 10, get_display(arabic_reshaper.reshape(f'فاتورة رقم: #{invoice_id}')), align='C')
    pdf.ln(10)
    pdf.cell(0, 10, get_display(arabic_reshaper.reshape(f'تاريخ الإصدار: {created_at}')), align='C')
    pdf.ln(10)
    pdf.cell(0, 10, get_display(arabic_reshaper.reshape(f'تاريخ الزيارة: {appt_date or "—"}')), align='C')
    pdf.ln(12)
    pdf.set_font('Arabic', '', 11)
    pdf.cell(0, 10, get_display(arabic_reshaper.reshape(f'المريض: {name}')), align='C')
    pdf.ln(8)
    if email:
        pdf.cell(0, 10, get_display(arabic_reshaper.reshape(f'البريد: {email}')), align='C')
        pdf.ln(8)
    if address:
        pdf.cell(0, 10, get_display(arabic_reshaper.reshape(f'التشخيص: {address}')), align='C')
    pdf.ln(12)

    col_widths = [80, 60, 45]
    headers = ['الخدمة', 'السعر (ج.م)', 'البيان']
    pdf.set_font('Arabic', '', 10)
    for i, header in enumerate(headers):
        pdf.cell(col_widths[i], 10, get_display(arabic_reshaper.reshape(header)), border=1, align='C')
    pdf.ln()
    for desc, price in items:
        pdf.cell(col_widths[2], 10, get_display(arabic_reshaper.reshape(str(desc))), border=1, align='C')
        pdf.cell(col_widths[1], 10, get_display(arabic_reshaper.reshape(str(price))), border=1, align='C')
        pdf.cell(col_widths[0], 10, '', border=1, align='C')
        pdf.ln()
    pdf.set_font('Arabic', '', 12)
    pdf.cell(80, 12, get_display(arabic_reshaper.reshape(f'الإجمالي: {total} ج.م')), border=1, align='C')
    pdf.cell(60, 12, '', border=1, align='C')
    pdf.cell(45, 12, get_display(arabic_reshaper.reshape(f'({status})')), border=1, align='C')
    pdf.ln(20)
    pdf.set_font('Arabic', '', 11)
    pdf.cell(0, 10, get_display(arabic_reshaper.reshape(f'شكراً لثقتكم ب{get_clinic_name()}')), align='C')

    filename = f'invoice_{invoice_id}.pdf'
    pdf.output(filename)
    return filename

@app.route('/admin/invoices/<int:invoice_id>/pdf')
def admin_invoice_pdf(invoice_id):
    if not session.get('admin'):
        return redirect('/admin/login')
    pdf_path = generate_invoice_pdf(invoice_id)
    if not pdf_path:
        return "تعذر إنشاء PDF", 500
    return f'''
    <html dir="rtl"><body style="font-family:Segoe UI; text-align:center; padding:40px;">
    <h2 style="color:#0077b6;">✅ تم إنشاء ملف الفاتورة بنجاح</h2>
    <p>الملف: {pdf_path}</p>
    <a href="/admin/invoices/{invoice_id}" style="color:#0077b6;">العودة للفاتورة</a>
    </body></html>
    '''

# ====================== PDF Generation ======================
from fpdf import FPDF
import arabic_reshaper
from bidi.algorithm import get_display

class ArabicPDF(FPDF):
    def add_arabic_font(self):
        font_path = find_arabic_font()
        if font_path:
            self.add_font('Arabic', '', font_path, uni=True)
            return True
        return False

@app.route('/admin/pdf')
def admin_pdf():
    if not session.get('admin'):
        return redirect('/admin/login')

    conn = db.connect()
    c = conn.cursor()
    today = datetime.now().date()
    
    # ✅ حساب الأحد الخاص بالأسبوع الحالي (وليس القادم)
    start_of_week = today - timedelta(days=(today.weekday() + 1) % 7)
    end_of_week = start_of_week + timedelta(days=4)  # الخميس

    c.execute('''
        SELECT a.appointment_date, a.appointment_time, p.name, p.booking_type, p.address
        FROM appointments a
        JOIN patients p ON a.patient_id = p.id
        WHERE a.appointment_date BETWEEN ? AND ?
        ORDER BY a.appointment_date, a.appointment_time
    ''', (start_of_week.strftime('%Y-%m-%d'), end_of_week.strftime('%Y-%m-%d')))
    records = c.fetchall()
    conn.close()

    pdf = ArabicPDF()
    pdf.add_page()
    pdf.add_arabic_font()

    pdf.set_font('Arabic', '', 16)
    title = f'{get_clinic_name()} - جدول مواعيد الأسبوع'
    pdf.cell(0, 12, get_display(arabic_reshaper.reshape(title)), align='C')
    pdf.ln(15)

    pdf.set_font('Arabic', '', 12)
    period_text = f'من {start_of_week} إلى {end_of_week}'
    pdf.cell(0, 10, get_display(arabic_reshaper.reshape(period_text)), align='C')
    pdf.ln(12)

    if not records:
        pdf.set_font('Arabic', '', 12)
        no_data = 'لا توجد مواعيد محجوزة هذا الأسبوع.'
        pdf.cell(0, 10, get_display(arabic_reshaper.reshape(no_data)), align='C')
    else:
        col_widths = [15, 30, 25, 40, 35, 35]
        headers = ['م', 'التاريخ', 'الوقت', 'الاسم', 'نوع الحجز', 'تشخيص الحالة']
        pdf.set_font('Arabic', '', 10)
        for i, header in enumerate(headers):
            reshaped = arabic_reshaper.reshape(header)
            bidi_header = get_display(reshaped)
            pdf.cell(col_widths[i], 10, bidi_header, border=1, align='C')
        pdf.ln()

        for idx, record in enumerate(records, start=1):
            date, time, name, booking_type, address = record
            if booking_type == 'consultation':
                type_ar = 'استشارة'
            elif booking_type == 'urgent':
                type_ar = 'حجز مستعجل'
            else:
                type_ar = 'عملية'

            row_data = [str(idx), date, time, name, type_ar, address]
            for i, data in enumerate(row_data):
                reshaped = arabic_reshaper.reshape(str(data))
                bidi_data = get_display(reshaped)
                pdf.set_font('Arabic', '', 10)
                pdf.cell(col_widths[i], 10, bidi_data, border=1, align='C')
            pdf.ln()

    filename = f'weekly_schedule_{start_of_week}.pdf'
    pdf.output(filename)

    return f'''
    <html dir="rtl"><body style="font-family:Segoe UI; text-align:center; padding:40px;">
    <h2 style="color:#0077b6;">✅ تم إنشاء ملف PDF بنجاح</h2>
    <p>الملف: {filename}</p>
    <a href="/admin/dashboard" style="color:#0077b6;">العودة للوحة التحكم</a>
    </body></html>
    '''

if __name__ == '__main__':
    init_db()
    port = int(os.environ.get('PORT', 5000))
    host = os.environ.get('HOST', '0.0.0.0' if os.environ.get('PORT') else '127.0.0.1')
    debug = 'PORT' not in os.environ
    app.run(debug=debug, host=host, port=port)