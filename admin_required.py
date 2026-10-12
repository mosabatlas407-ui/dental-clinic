from functools import wraps

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('admin'):
            return redirect('/admin/login')
        # Check session timeout
        last_activity = session.get('last_activity')
        if last_activity and (time.time() - last_activity) > 1800:  # 30 minutes
            session.clear()
            return redirect('/admin/login')
        session['last_activity'] = time.time()
        return f(*args, **kwargs)
    return decorated