from ecopulse_app import app
client = app.test_client()
print('ROOT', client.get('/').status_code)
print('LOGIN', client.get('/login').status_code)
