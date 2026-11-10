import os
from pathlib import Path
from contextlib import contextmanager
from sqlalchemy import create_engine, String, JSON, DateTime, func, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

class Base(DeclarativeBase): pass
class Record(Base):
    __tablename__='records'
    id: Mapped[str]=mapped_column(String(120),primary_key=True)
    kind: Mapped[str]=mapped_column(String(40),index=True)
    data: Mapped[dict]=mapped_column(JSON)
    created_at: Mapped[object]=mapped_column(DateTime(timezone=True),server_default=func.now())
class User(Base):
    __tablename__='users'
    id: Mapped[str]=mapped_column(String(60),primary_key=True)
    email: Mapped[str]=mapped_column(String(200),unique=True,index=True)
    password: Mapped[str]=mapped_column(String(400))
    role: Mapped[str]=mapped_column(String(40),default='VIEWER')
    name: Mapped[str]=mapped_column(String(100))

url=os.getenv('DATABASE_URL') or ('sqlite:////tmp/fingraph.db' if os.getenv('VERCEL') else 'sqlite:///./data/fingraph.db')
if url.startswith('postgres://'): url=url.replace('postgres://','postgresql+psycopg://',1)
elif url.startswith('postgresql://'): url=url.replace('postgresql://','postgresql+psycopg://',1)
if url.startswith('sqlite:///'): Path(url[10:]).parent.mkdir(parents=True,exist_ok=True)
engine=create_engine(url,connect_args={'check_same_thread':False,'timeout':30} if url.startswith('sqlite') else {},pool_pre_ping=True)
Session=sessionmaker(engine,expire_on_commit=False)
Base.metadata.create_all(engine)
@contextmanager
def db():
    with Session() as s:
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback(); raise
def list_records(kind):
    with db() as s: return [r.data for r in s.query(Record).filter_by(kind=kind).order_by(Record.created_at).all()]
def get_record(kind,id):
    with db() as s:
        r=s.get(Record,id)
        return r.data if r and r.kind==kind else None
def put_record(kind,data):
    with db() as s:
        r=s.get(Record,data['id'])
        if r: r.data=data
        else: s.add(Record(id=data['id'],kind=kind,data=data))
    return data
def delete_record(kind,id):
    with db() as s:
        r=s.get(Record,id)
        if r and r.kind==kind: s.delete(r); return True
    return False
