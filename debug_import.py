import traceback

print('Starting import test...')
try:
    from server.app import app
    print('Imported app')
    from fastapi.testclient import TestClient
    client = TestClient(app)
    print('TestClient created successfully')
except Exception as e:
    print('ERROR during import or TestClient init:', repr(e))
    traceback.print_exc()
