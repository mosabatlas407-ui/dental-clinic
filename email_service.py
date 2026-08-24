import smtplib
import sqlite3
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from email.utils import formataddr
import os

def get_clinic_name():
    conn = sqlite3.connect('clinic.db')
    c = conn.cursor()
    try:
        c.execute("SELECT value FROM settings WHERE key='clinic_name'")
        row = c.fetchone()
        return (row[0] if row and row[0] else 'عيادة دنتال كير')
    except sqlite3.OperationalError:
        return 'عيادة دنتال كير'
    finally:
        conn.close()

CLINIC_NAME = get_clinic_name()

def refresh_clinic_name():
    global CLINIC_NAME
    CLINIC_NAME = get_clinic_name()
    return CLINIC_NAME

def get_settings():
    conn = sqlite3.connect('clinic.db')
    c = conn.cursor()
    c.execute('SELECT key, value FROM settings')
    rows = c.fetchall()
    conn.close()
    return dict(rows)

def smtp_configured():
    s = get_settings()
    return bool(s.get('smtp_email') and s.get('smtp_password'))

def send_email(to_email, subject, html_body, attachment_path=None):
    settings = get_settings()
    smtp_email = settings.get('smtp_email')
    smtp_password = settings.get('smtp_password')
    if not smtp_email or not smtp_password:
        return False, 'إعدادات SMTP غير مضبوطة'

    msg = MIMEMultipart('alternative')
    msg['From'] = formataddr((CLINIC_NAME, smtp_email))
    msg['To'] = to_email
    msg['Subject'] = subject
    msg.attach(MIMEText(html_body, 'html', 'utf-8'))

    if attachment_path and os.path.exists(attachment_path):
        with open(attachment_path, 'rb') as f:
            part = MIMEApplication(f.read(), _subtype='pdf')
            part.add_header('Content-Disposition', 'attachment', filename=os.path.basename(attachment_path))
            msg.attach(part)

    try:
        server = smtplib.SMTP_SSL('smtp.gmail.com', 465, timeout=30)
        server.login(smtp_email, smtp_password)
        server.sendmail(smtp_email, [to_email], msg.as_string())
        server.quit()
        return True, 'تم الإرسال بنجاح'
    except Exception as e:
        return False, f'فشل الإرسال: {str(e)}'

def send_booking_confirmation(patient_name, to_email, appointment_date, appointment_time):
    html = f'''
    <html dir="rtl"><body style="font-family:'Segoe UI',Tahoma;background:#f0f4f8;padding:30px;">
    <div style="max-width:500px;margin:auto;background:white;border-radius:15px;overflow:hidden;box-shadow:0 4px 12px rgba(0,0,0,0.15);">
        <div style="background:linear-gradient(90deg,#0077b6,#00b4d8);color:white;text-align:center;padding:20px;">
            <h2 style="margin:0;">🦷 {CLINIC_NAME}</h2>
            <p style="margin:5px 0 0;">تأكيد حجز موعد</p>
        </div>
        <div style="padding:25px;line-height:2;color:#333;">
            <p>أهلاً <strong>{patient_name}</strong>،</p>
            <p>تم حجز موعدك بنجاح ✅</p>
            <p style="background:#e8f6ff;padding:12px;border-radius:8px;text-align:center;">
                📅 التاريخ: <strong>{appointment_date}</strong><br>
                ⏰ الوقت: <strong>{appointment_time}</strong>
            </p>
            <p>نرجو الحضور قبل الموعد بـ 10 دقائق. في حال رغبت بتغيير الموعد يرجى الاتصال بالعيادة.</p>
        </div>
    </div>
    </body></html>
    '''
    return send_email(to_email, f'✅ تأكيد حجز موعد - {CLINIC_NAME}', html)

def send_reminder(patient_name, to_email, appointment_date, appointment_time, booking_type):
    type_ar = {'consultation': 'استشارة', 'urgent': 'حجز مستعجل', 'surgery': 'عملية'}.get(booking_type, booking_type)
    html = f'''
    <html dir="rtl"><body style="font-family:'Segoe UI',Tahoma;background:#f0f4f8;padding:30px;">
    <div style="max-width:500px;margin:auto;background:white;border-radius:15px;overflow:hidden;box-shadow:0 4px 12px rgba(0,0,0,0.15);">
        <div style="background:linear-gradient(90deg,#2a9d8f,#264653);color:white;text-align:center;padding:20px;">
            <h2 style="margin:0;">⏰ تذكير بموعدك</h2>
            <p style="margin:5px 0 0;">{CLINIC_NAME}</p>
        </div>
        <div style="padding:25px;line-height:2;color:#333;">
            <p>أهلاً <strong>{patient_name}</strong>،</p>
            <p>نذكّرك بموعدك غداً في العيادة:</p>
            <p style="background:#f0f9f0;padding:12px;border-radius:8px;text-align:center;">
                🩺 نوع الزيارة: <strong>{type_ar}</strong><br>
                📅 التاريخ: <strong>{appointment_date}</strong><br>
                ⏰ الوقت: <strong>{appointment_time}</strong>
            </p>
            <p>للاستفسار أو التعديل، يرجى التواصل مع العيادة. ننتظرك! 😊</p>
        </div>
    </div>
    </body></html>
    '''
    return send_email(to_email, f'⏰ تذكير بموعدك غداً - {CLINIC_NAME}', html)

def send_invoice(patient_name, to_email, invoice_id, appointment_date, pdf_path=None):
    html = f'''
    <html dir="rtl"><body style="font-family:'Segoe UI',Tahoma;background:#f0f4f8;padding:30px;">
    <div style="max-width:500px;margin:auto;background:white;border-radius:15px;overflow:hidden;box-shadow:0 4px 12px rgba(0,0,0,0.15);">
        <div style="background:linear-gradient(90deg,#e76f51,#f4a261);color:white;text-align:center;padding:20px;">
            <h2 style="margin:0;">🧾 فاتورة علاج</h2>
            <p style="margin:5px 0 0;">{CLINIC_NAME}</p>
        </div>
        <div style="padding:25px;line-height:2;color:#333;">
            <p>أهلاً <strong>{patient_name}</strong>،</p>
            <p>فاتورتك رقم <strong>#{invoice_id}</strong> للزيارة بتاريخ <strong>{appointment_date}</strong> جاهزة.</p>
            <p>الفاتورة مرفقة بهذا البريد بصيغة PDF.</p>
            <p>شكراً لثقتكم بعيادتنا 🙏</p>
        </div>
    </div>
    </body></html>
    '''
    return send_email(to_email, f'🧾 فاتورتك رقم #{invoice_id} - {CLINIC_NAME}', html, attachment_path=pdf_path)