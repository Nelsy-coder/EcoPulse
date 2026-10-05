import pytest
from datetime import datetime

from ecopulse_app import app, db, User, FinancialRecord, PaymentTransaction, FeatureToggle


@pytest.fixture()
def client():
    app.config.update(TESTING=True, SQLALCHEMY_DATABASE_URI='sqlite:///:memory:')
    with app.app_context():
        db.drop_all()
        db.create_all()
    with app.test_client() as client:
        yield client
    with app.app_context():
        db.drop_all()


def create_user(username, role, password='secret', employee_id=None):
    user = User(username=username, email=f'{username}@example.com', role=role)
    user.set_password(password)
    if employee_id:
        user.employee_id = employee_id
    user.currency = 'Ksh'
    user.threshold = 100
    db.session.add(user)
    db.session.commit()
    return user


def test_customer_payment_page_creates_transaction(client):
    with app.app_context():
        customer = create_user('paycust', 'customer')
        invoice = FinancialRecord(
            user_id=customer.id,
            period='2026-07',
            total_consumption=120.0,
            total_cost=150.0,
            total_paid=0.0,
            balance=150.0,
            due_date=datetime.utcnow(),
            payment_status='pending'
        )
        db.session.add(invoice)
        db.session.commit()

    login = client.post('/login', data={'username': 'paycust', 'password': 'secret'}, follow_redirects=True)
    assert b'Invalid' not in login.data

    response = client.post(
        f'/customer/pay/{invoice.id}',
        data={
            'payment_amount': '50',
            'payment_method': 'mpesa',
            'payment_reference': 'ABC123XYZ7',
            'payment_phone': '0712345678'
        },
        follow_redirects=True
    )

    assert response.status_code == 200
    with app.app_context():
        invoice = FinancialRecord.query.get(invoice.id)
        assert invoice.balance == 100.0
        txn = PaymentTransaction.query.filter_by(user_id=customer.id).first()
        assert txn is not None
        assert txn.status == 'completed'
        assert txn.payment_method == 'mpesa'


def test_admin_can_toggle_ticketing_system(client):
    with app.app_context():
        create_user('adm', 'admin', password='adminpass', employee_id='ADM000001')
        create_user('cust', 'customer', password='custpass')

    client.post('/ops/portal/login-2026', data={'username': 'adm', 'password': 'adminpass'}, follow_redirects=True)
    response = client.post('/admin/ticketing-settings', data={'enabled': 'false'}, follow_redirects=True)
    assert response.status_code == 200

    with app.app_context():
        toggle = FeatureToggle.query.filter_by(name='customer_ticketing').first()
        assert toggle is not None
        assert toggle.enabled is False

    client.get('/logout', follow_redirects=True)
    login = client.post('/login', data={'username': 'cust', 'password': 'custpass'}, follow_redirects=True)
    assert b'Invalid' not in login.data

    support_page = client.get('/support')
    assert support_page.status_code == 200
    assert b'currently closed' in support_page.data.lower()
