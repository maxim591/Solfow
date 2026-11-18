from sqlalchemy import create_engine, text
from sqlalchemy.orm import declarative_base, sessionmaker

engine = create_engine("sqlite:///./payments.db", connect_args={"check_same_thread": False})

with engine.connect() as conn:
    conn.execute(text("PRAGMA secure_delete = ON"))
    conn.commit()

SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()