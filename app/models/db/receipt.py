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


class ReceiptItemDB(Base):
    __tablename__ = "receipt_items"

    id = Column(Integer, primary_key=True, index=True)
    receipt_id = Column(Integer, ForeignKey("receipts.id"))
    product_id = Column(Integer, ForeignKey("products.id"))
    price = Column(Float)

    receipt = relationship("ReceiptDB", back_populates="items")
    product = relationship("ProductDB", back_populates="items")
