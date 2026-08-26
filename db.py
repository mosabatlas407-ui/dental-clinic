"""طبقة اتصال موحدة بقاعدة البيانات
- محلياً (بدون متغيرات): SQLite ملف clinic.db كما هو
- على السحابة: PostgreSQL تلقائياً عند وجود متغير البيئة DATABASE_URL
"""
import os

DATABASE_URL = (os.environ.get('DATABASE_URL') or '').strip()
IS_PG = DATABASE_URL.startswith(('postgres://', 'postgresql://'))

if IS_PG:
    import psycopg2
    if DATABASE_URL.startswith('postgres://'):
        DATABASE_URL = 'postgresql://' + DATABASE_URL.split('://', 1)[1]
    if 'connect_timeout' not in DATABASE_URL:
        sep = '&' if '?' in DATABASE_URL else '?'
        DATABASE_URL += f'{sep}connect_timeout=10'


def translate(sql):
    """تحويل صيغة SQL المشتركة إلى dialekt المحرك الحالي"""
    if not IS_PG:
        return sql
    sql = sql.replace('INTEGER PRIMARY KEY AUTOINCREMENT', 'SERIAL PRIMARY KEY')
    return sql.replace('?', '%s')


class _Cursor:
    """مؤشر يترجم الاستعلامات تلقائياً حسب المحرك"""
    def __init__(self, cur):
        self._cur = cur

    def execute(self, sql, params=()):
        return self._cur.execute(translate(sql), tuple(params))

    def executemany(self, sql, seq):
        return self._cur.executemany(translate(sql), [tuple(p) for p in seq])

    def __getattr__(self, name):
        return getattr(self._cur, name)


class _Connection:
    """غلاف اتصال يرجع مؤشرات مترجمة"""
    def __init__(self, conn):
        self._conn = conn

    def cursor(self, *args, **kwargs):
        return _Cursor(self._conn.cursor(*args, **kwargs))

    def commit(self):
        return self._conn.commit()

    def rollback(self):
        return self._conn.rollback()

    def close(self):
        return self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def connect():
    """فتح اتصال جديد بقاعدة البيانات"""
    if IS_PG:
        return _Connection(psycopg2.connect(DATABASE_URL))
    import sqlite3
    return _Connection(sqlite3.connect(os.environ.get('DB_PATH', 'clinic.db')))


def set_setting(c, key, value, ignore_existing=False):
    """حفظ قيمة في جدول الإعدادات بشكل متوافق مع المحركين
    ignore_existing=True تعني لا تلمس القيمة إن كانت موجودة أصلاً
    """
    if IS_PG:
        action = 'DO NOTHING' if ignore_existing else 'DO UPDATE SET value = EXCLUDED.value'
        c.execute(
            f'INSERT INTO settings (key, value) VALUES (?, ?) '
            f'ON CONFLICT (key) {action}',
            (key, value),
        )
    else:
        verb = 'INSERT OR IGNORE' if ignore_existing else 'INSERT OR REPLACE'
        c.execute(f'{verb} INTO settings (key, value) VALUES (?, ?)', (key, value))


def insert_returning_id(c, sql, params=()):
    """تنفيذ INSERT وإرجاع معرف الصف الجديد في المحركين"""
    if IS_PG:
        c.execute(sql + ' RETURNING id', params)
        return c.fetchone()[0]
    c.execute(sql, params)
    return c.lastrowid


def init_schema(c):
    """إنشاء الجداول - نفس بنية الجداول في المحركين"""
    c.execute('''
        CREATE TABLE IF NOT EXISTS patients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            age INTEGER,
            gender TEXT,
            painkiller TEXT,
            address TEXT,
            booking_type TEXT,
            email TEXT DEFAULT '',
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
    c.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS invoices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL,
            appointment_id INTEGER,
            total REAL DEFAULT 0,
            status TEXT DEFAULT 'غير مدفوعة',
            created_at TEXT,
            FOREIGN KEY(patient_id) REFERENCES patients(id)
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS invoice_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            invoice_id INTEGER NOT NULL,
            description TEXT NOT NULL,
            price REAL DEFAULT 0,
            FOREIGN KEY(invoice_id) REFERENCES invoices(id)
        )
    ''')
