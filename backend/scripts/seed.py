from backend.app.main import app
from backend.app.store import list_records
print({k:len(list_records(k)) for k in ['investors','products','documents']})
