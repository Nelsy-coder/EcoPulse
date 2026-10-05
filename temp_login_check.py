from ecopulse_app import app, db, User

app.config.update(TESTING=True, SQLALCHEMY_DATABASE_URI='sqlite:///:memory:')

with app.app_context():
    db.drop_all()
    db.create_all()
    users = [
        ('admin1', 'admin', 'adminpass', 'ADM000001'),
        ('exam1', 'examiner', 'exampass', 'ADM000002'),
        ('hr1', 'hr_manager', 'hrpass', 'ADM000003'),
        ('cust1', 'customer', 'custpass', None),
    ]
    for username, role, password, employee_id in users:
        user = User(username=username, email=f'{username}@example.com', role=role)
        user.set_password(password)
        if employee_id:
            user.employee_id = employee_id
        db.session.add(user)
    db.session.commit()

with app.test_client() as client:
    checks = []

    rv = client.get('/login')
    checks.append(('GET /login', rv.status_code, 200))

    rv = client.post('/login', data={'username': 'cust1', 'password': 'custpass', 'meter_number': '123456'}, follow_redirects=True)
    body = rv.get_data(as_text=True).lower()
    checks.append(('customer login', rv.status_code, 200))
    checks.append(('customer dashboard redirect', 'dashboard' in body, True))

    rv = client.get('/staff/dashboard')
    checks.append(('staff dashboard for customer', rv.status_code, 403))

    rv = client.get('/logout', follow_redirects=True)
    checks.append(('logout', rv.status_code, 200))

    rv = client.post('/ops/portal/login-2026', data={'username': 'admin1', 'password': 'adminpass'}, follow_redirects=True)
    body = rv.get_data(as_text=True).lower()
    checks.append(('admin staff login', rv.status_code, 200))
    checks.append(('admin staff dashboard', 'staff dashboard' in body, True))

    rv = client.get('/admin/tariff')
    checks.append(('admin tariff page', rv.status_code, 200))

    rv = client.get('/logout', follow_redirects=True)
    checks.append(('logout after admin', rv.status_code, 200))

    rv = client.post('/ops/portal/login-2026', data={'username': 'exam1', 'password': 'exampass'}, follow_redirects=True)
    body = rv.get_data(as_text=True).lower()
    checks.append(('examiner staff login', rv.status_code, 200))
    checks.append(('examiner staff dashboard', 'staff dashboard' in body, True))

    rv = client.get('/examiner/payroll')
    checks.append(('examiner payroll page', rv.status_code, 200))

    rv = client.get('/logout', follow_redirects=True)
    checks.append(('logout after examiner', rv.status_code, 200))

    rv = client.post('/ops/portal/login-2026', data={'username': 'hr1', 'password': 'hrpass'}, follow_redirects=True)
    body = rv.get_data(as_text=True).lower()
    checks.append(('hr staff login', rv.status_code, 200))
    checks.append(('hr staff dashboard', 'staff dashboard' in body, True))

    rv = client.get('/hr/payroll')
    checks.append(('hr payroll page', rv.status_code, 200))

for name, actual, expected in checks:
    print(f'{name}: {actual} (expected {expected})')

failed = [(name, actual, expected) for name, actual, expected in checks if actual != expected]
if failed:
    raise SystemExit(f'Login check failed: {failed}')

print('All login and protected page checks passed.')
