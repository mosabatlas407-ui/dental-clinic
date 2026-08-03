from flask import Flask, render_template, request, redirect, session
import sqlite3
from datetime import datetime, timedelta
import traceback, sys

app = Flask(__name__)
app.secret_key = 'dental_clinic_secret_key_2026'

ADMIN_PASSWORD = "admin123"

def init_db():
    conn = sqlite3.connect('clinic.db')
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS patients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            age INTEGER,
            gender TEXT,
            painkiller TEXT,
            address TEXT,
            booking_type TEXT,
            initial_diagnosis TEXT DEFAULT 'تحت الفحص'
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS appointments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER,
            appointment_date TEXT NOT NULL,
            appointment_time TEXT NOT NULL,
            status TEXT DEFAULT 'محجوز',
            FOREIGN KEY(patient_id) REFERENCES patients(id)
        )
    ''')
    conn.commit()
    conn.close()

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
    age = request.form['age']
    gender = request.form['gender']
    painkiller = request.form['painkiller']
    address = request.form['address']
    booking_type = request.form['booking_type']

    conn = sqlite3.connect('clinic.db')
    c = conn.cursor()
    c.execute('''
        INSERT INTO patients (name, age, gender, painkiller, address, booking_type)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (name, age, gender, painkiller, address, booking_type))
    patient_id = c.lastrowid

    appointment_date, appointment_time = find_next_available_slot(c)

    c.execute('''
        INSERT INTO appointments (patient_id, appointment_date, appointment_time)
        VALUES (?, ?, ?)
    ''', (patient_id, appointment_date, appointment_time))
    conn.commit()
    conn.close()

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
                <p><strong>مكان السكن:</strong> {address}</p>
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
        if request.form['password'] == ADMIN_PASSWORD:
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
    conn = sqlite3.connect('clinic.db')
    c = conn.cursor()
    # استخدام تاريخ اليوم بصيغة نصية لتجنب مشاكل التوقيت
    today_str = datetime.now().date().strftime('%Y-%m-%d')
    c.execute('''
        SELECT a.id, p.name, p.booking_type, a.appointment_date, a.appointment_time, p.address, a.status
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
    conn = sqlite3.connect('clinic.db')
    c = conn.cursor()
    c.execute('DELETE FROM appointments WHERE id=?', (appointment_id,))
    conn.commit()
    conn.close()
    return redirect('/admin/dashboard')

@app.route('/admin/edit/<int:appointment_id>', methods=['GET', 'POST'])
def admin_edit(appointment_id):
    if not session.get('admin'):
        return redirect('/admin/login')
    conn = sqlite3.connect('clinic.db')
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

# ====================== PDF Generation ======================
from fpdf import FPDF
import arabic_reshaper
from bidi.algorithm import get_display

class ArabicPDF(FPDF):
    def add_arabic_font(self):
        self.add_font('Arabic', '', r'C:\Windows\Fonts\arial.ttf', uni=True)

@app.route('/admin/pdf')
def admin_pdf():
    if not session.get('admin'):
        return redirect('/admin/login')

    conn = sqlite3.connect('clinic.db')
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
    title = 'عيادة دنتال كير - جدول مواعيد الأسبوع'
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
        headers = ['م', 'التاريخ', 'الوقت', 'الاسم', 'نوع الحجز', 'مكان السكن']
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
    app.run(debug=True)