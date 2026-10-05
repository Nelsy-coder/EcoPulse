import pytest
from ecopulse_app import app, db, User, PayrollRecord

@pytest.fixture(scope='module')
def test_client():
    app.config['TESTING'] = True
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    with app.test_client() as client:
        with app.app_context():
            db.create_all()
        yield client
        with app.app_context():
            db.drop_all()


def create_user(username, role, password='secret', employee_id=None):
    u = User(username=username, email=f"{username}@example.com", role=role)
    u.set_password(password)
    if employee_id:
        u.employee_id = employee_id
    db.session.add(u)
    db.session.commit()
    return u


def login(client, route, username, password):
    return client.post(route, data={'username': username, 'password': password}, follow_redirects=True)


def test_failed_customer_login_does_not_crash(test_client):
    with app.app_context():
        db.session.query(User).delete()
        db.session.commit()

    rv = test_client.post('/login', data={'username': 'missing', 'password': 'wrong', 'meter_number': '123456'})
    assert rv.status_code == 200
    assert b'Invalid' in rv.data


def test_staff_login_and_dashboard(test_client):
    with app.app_context():
        admin = create_user('admin1', 'admin', password='adminpass', employee_id='ADM000001')
        examiner = create_user('exam1', 'examiner', password='exampass')
        hr = create_user('hr1', 'hr_manager', password='hrpass')

    # admin should land on the dedicated admin dashboard
    rv = login(test_client, '/ops/portal/login-2026', 'admin1', 'adminpass')
    assert rv.status_code == 200
    assert b'Financial Management' in rv.data or b'Admin' in rv.data

    # examiner should land on the dedicated examiner dashboard
    with app.app_context():
        db.session.query(User).delete()
        db.session.commit()
        create_user('examonly', 'examiner', password='expass', employee_id='EXM000001')

    rv2 = login(test_client, '/ops/portal/login-2026', 'examonly', 'expass')
    assert rv2.status_code == 200
    assert b'Examiner Dashboard' in rv2.data

    # customer cannot access staff dashboard (403)
    with app.app_context():
        cust = create_user('cust1', 'customer', password='custpass')
    # login as customer
    rv3 = login(test_client, '/login', 'cust1', 'custpass')
    assert b'Invalid' not in rv3.data
    # try access staff dashboard
    rv4 = test_client.get('/staff/dashboard')
    assert rv4.status_code == 403


def test_admin_security_and_endpoints(test_client):
    with app.app_context():
        db.session.query(User).delete()
        db.session.commit()
        admin = create_user('admin2', 'admin', password='apass')  # no employee_id -> should be forbidden

    # login admin without employee_id
    rv = test_client.post('/ops/portal/login-2026', data={'username': 'admin2', 'password': 'apass'})
    assert b'Staff Dashboard' not in rv.data
    # accessing admin tariff should be forbidden due to missing employee_id
    rv2 = test_client.get('/admin/tariff')
    assert rv2.status_code == 403

    # provision employee id and retry
    with app.app_context():
        admin = User.query.filter_by(username='admin2').first()
        admin.employee_id = 'ADM999999'
        db.session.commit()

    rv3 = test_client.get('/admin/tariff')
    # should either render HTML or JSON (200)
    assert rv3.status_code in (200,)


def test_hr_and_examiner_flows(test_client):
    with app.app_context():
        db.session.query(User).delete()
        db.session.commit()
        hr = create_user('hrx', 'hr_manager', password='hrp', employee_id='ADM123')
        exam = create_user('exx', 'examiner', password='examp', employee_id='ADM124')
        cust = create_user('cux', 'customer', password='cpw')

    # login HR
    rv = test_client.post('/ops/portal/login-2026', data={'username': 'hrx', 'password': 'hrp'})
    assert b'Staff Dashboard' in rv.data
    # create payroll
    with app.app_context():
        cust_db = User.query.filter_by(username='cux').first()
        cust_id = cust_db.id
    rv2 = test_client.post('/hr/payroll', data={'user_id': cust_id, 'period': '2026-05', 'gross_salary': '1000', 'deductions': '100'})
    assert rv2.status_code == 201
    data = rv2.get_json()
    assert 'net_salary' in data

    # logout and login as examiner to approve
    test_client.get('/logout', follow_redirects=True)
    test_client.post('/ops/portal/login-2026', data={'username': 'exx', 'password': 'examp'})
    # find payroll id
    with app.app_context():
        pr = PayrollRecord.query.first()
    rv3 = test_client.post(f'/examiner/payroll/{pr.id}/approve')
    assert rv3.status_code == 200
    d = rv3.get_json()
    assert d.get('status') == 'approved'


def test_admin_invitation_provisions_fixed_role_once(test_client):
    with app.app_context():
        db.session.query(User).delete()
        db.session.commit()
        create_user('invite_admin', 'admin', password='adminpass', employee_id='ADM000009')

    admin_login = test_client.post('/ops/portal/login-2026', data={
        'username': 'invite_admin',
        'password': 'adminpass'
    }, follow_redirects=True)
    assert admin_login.status_code == 200

    invitation = test_client.post('/api/admin/users/invite', json={
        'username': 'invited_hr',
        'email': 'invited_hr@example.com',
        'role': 'hr_manager',
        'full_name': 'Invited Employee',
        'id_number': 'ID123456',
        'phone_number': '0712345678'
    })
    assert invitation.status_code == 201
    invite_url = invitation.get_json()['invite_url']
    invite_path = invite_url.split('localhost', 1)[-1]
    assert test_client.get(invite_path).status_code == 200

    setup = test_client.post(invite_path, data={
        'password': 'newpassword123',
        'confirm_password': 'newpassword123',
        'role': 'admin'
    })
    assert setup.status_code == 302
    with app.app_context():
        invited_user = User.query.filter_by(username='invited_hr').one()
        assert invited_user.role == 'hr_manager'
        assert invited_user.employee_id.startswith('HRM')
        assert invited_user.full_name == 'Invited Employee'
        assert invited_user.id_number == 'ID123456'
        assert invited_user.phone_number == '0712345678'
        assert invited_user.check_password('newpassword123')

    assert test_client.get(invite_path).status_code == 400
    invalid_staff_role = test_client.post('/ops/portal/login-2026', data={
        'username': 'invited_hr',
        'password': 'newpassword123',
        'role': 'customer'
    })
    assert b'Invalid staff credentials' in invalid_staff_role.data


def test_admin_creates_employee_with_required_identity_details(test_client):
    with app.app_context():
        db.session.query(User).delete()
        db.session.commit()
        create_user('identity_admin', 'admin', password='adminpass', employee_id='ADM000010')

    login_response = test_client.post('/ops/portal/login-2026', data={
        'username': 'identity_admin',
        'password': 'adminpass'
    }, follow_redirects=True)
    assert login_response.status_code == 200
    assert b'Full Names' in login_response.data
    assert b'ID No.' in login_response.data

    users_page = test_client.get('/admin/users/ui')
    assert users_page.status_code == 200
    assert b'Full Names' in users_page.data
    assert b'Examiner' in users_page.data

    missing_details = test_client.post('/admin/manage_user', data={
        'action': 'create',
        'username': 'missing_details',
        'email': 'missing@example.com',
        'password': 'employee123',
        'role': 'examiner'
    }, follow_redirects=True)
    assert b'Provide ID number, phone number and full names' in missing_details.data

    created = test_client.post('/admin/manage_user', data={
        'action': 'create',
        'username': 'named_examiner',
        'email': 'examiner@example.com',
        'password': 'employee123',
        'role': 'examiner',
        'full_name': 'Named Examiner',
        'id_number': 'ID987654',
        'phone_number': '0798765432'
    }, follow_redirects=True)
    assert created.status_code == 200

    with app.app_context():
        examiner = User.query.filter_by(username='named_examiner').one()
        assert examiner.role == 'examiner'
        assert examiner.full_name == 'Named Examiner'
        assert examiner.id_number == 'ID987654'
        assert examiner.phone_number == '0798765432'
        assert examiner.employee_id.startswith('EXM')

    listed_users = test_client.get('/admin/users').get_json()
    listed_examiner = next(user for user in listed_users if user['username'] == 'named_examiner')
    assert listed_examiner['role'] == 'examiner'
    assert listed_examiner['full_name'] == 'Named Examiner'
    assert listed_examiner['id_number'] == 'ID987654'
