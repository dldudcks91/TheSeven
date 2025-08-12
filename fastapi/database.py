

from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker


host = 'localhost'
user = 'root'
password = 'an98'
db='TheSeven'
charset='utf8'
DATABASE_URL = f"mysql+pymysql://{user}:{password}@{host}:3306/{db}?charset-{charset}"

engine = create_engine(DATABASE_URL)
    
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()