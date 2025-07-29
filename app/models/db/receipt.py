from sqlalchemy import Column, Integer, String, Float, ForeignKey
from sqlalchemy.orm import relationship
from app.core.database import Base


class ReceiptDB(Base):
    __tablename__ = "receipts"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, index=True)
    store = Column(String)
    date = Column(String)
    time = Column(String)
    total = Column(Float)
    currency = Column(String)

    items = relationship("ReceiptItemDB", back_populates="receipt", cascade="all, delete-orphan")


class ReceiptItemDB(Base):
    __tablename__ = "receipt_items"

    id = Column(Integer, primary_key=True, index=True)
    receipt_id = Column(Integer, ForeignKey("receipts.id"))
    name = Column(String)
    price = Column(Float)
    category = Column(String)
    category_id = Column(Integer)
    subcategory = Column(String)
    subcategory_id = Column(Integer)

    receipt = relationship("ReceiptDB", back_populates="items")
