from backend.app.store import Base,engine
Base.metadata.create_all(engine)
print('Schema v1 applied')
