@app.route('/admin/complete/<int:appointment_id>')
@admin_required
def admin_complete(appointment_id):
    try:
        with get_db() as conn:
            c = conn.cursor()
            c.execute('''
                SELECT a.patient_id, p.booking_type, a.appointment_date, p.name
                FROM appointments a JOIN patients p ON a.patient_id = p.id
                WHERE a.id = ?
            ''', (appointment_id,))
            row = c.fetchone()
            if not row:
                flash('الموعد غير موجود', 'error')
                return redirect('/admin/dashboard')
            
            patient_id, booking_type, appointment_date, patient_name = row
            c.execute('UPDATE appointments SET status=? WHERE id=?', ('مكتمل', appointment_id))
            c.execute('''
                INSERT INTO invoices (patient_id, appointment_id, created_at)
                VALUES (?, ?, ?)
            ''', (patient_id, appointment_id, datetime.now().strftime('%Y-%m-%d %H:%M')))
            invoice_id = c.lastrowid
            service_ar = {'consultation': 'فحص واستشارة', 'urgent': 'حالة طارئة', 'surgery': 'عملية جراحية'}.get(booking_type, booking_type)
            default_price = get_price(booking_type)
            c.execute('INSERT INTO invoice_items (invoice_id, description, price) VALUES (?, ?, ?)',
                      (invoice_id, service_ar, default_price))
            c.execute('UPDATE invoices SET total = (SELECT COALESCE(SUM(price),0) FROM invoice_items WHERE invoice_id=?) WHERE id=?',
                      (invoice_id, invoice_id))
            conn.commit()
            
            audit_log('appointment_completed', f'Completed appointment #{appointment_id} for {sanitize_for_log(patient_name)}, created invoice #{invoice_id}', user='admin')
            flash('تم إكمال الموعد وإنشاء الفاتورة بنجاح', 'success')
            return redirect(url_for('admin_invoice', invoice_id=invoice_id))
    
    except Exception as e:
        app.logger.error(f"[admin_complete] Failed to complete appointment #{appointment_id}: {e}")
        flash('حدث خطأ أثناء إكمال الموعد. حاول مرة أخرى.', 'error')
        return redirect('/admin/dashboard')