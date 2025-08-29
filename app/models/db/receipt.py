from sqlalchemy import Column, Integer, String, Float, ForeignKey, BigInteger
from sqlalchemy.orm import relationship
from app.core.database import Base


class ReceiptDB(Base):
    __tablename__ = "receipts"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(BigInteger, index=True)
    store = Column(String)
    date = Column(String)
    time = Column(String)
    total = Column(Float)
    currency = Column(String)
    image_url = Column(String, nullable=True)

    items = relationship("ReceiptItemDB", back_populates="receipt", cascade="all, delete-orphan")


