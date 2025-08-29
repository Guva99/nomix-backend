from sqlalchemy import Column, Integer, String
from sqlalchemy.orm import relationship
from app.core.database import Base

class ProductDB(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    brand = Column(String, nullable=True)
    barcode = Column(String, unique=True, nullable=True)
    category = Column(String, nullable=True)
    category_id = Column(Integer, nullable=True)
    subcategory = Column(String, nullable=True)
    subcategory_id = Column(Integer, nullable=True)

    items = relationship("ReceiptItemDB", back_populates="product")