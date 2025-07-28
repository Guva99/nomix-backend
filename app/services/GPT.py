import os
import openai
import base64
from dotenv import load_dotenv

# Загружаем переменные окружения
load_dotenv()
openai.api_key = os.getenv("OPEN_AI_API")

# Твой промпт
PROMPT = """
Ты получаешь **изображение**, предположительно содержащее **товарный чек**. Твоя задача — определить его содержание и вернуть результат в **строго заданном формате JSON**. 

## Часть 1: Проверка — это чек или нет

Если изображение **не содержит чек**, верни следующий JSON: 

{
  "is_receipt": false,
  "reason": "На изображении нет признаков товарного чека"
}

### Часть 2: Если это **чек**, верни JSON следующего формата:
{
  "is_receipt": true,
  "store": "название магазина или заведения",
  "date": "ГГГГ-ММ-ДД",
  "time": "ЧЧ:ММ",
  "total": сумма_в_формате_числа,
  "currency": "RUB",
  "items": [
    {
      "name": "название товара",
      "price": сумма_в_формате_числа,
      "category": "название категории",
      "category_id": числовой_id_категории,
      "subcategory": "название подкатегории",
      "subcategory_id": числовой_id_подкатегории
    }
  ]
}

## Категории и подкатегории (справочник): 
### **1. Еда и напитки** (`category_id`: `1`)
- алкоголь (`subcategory_id`: `11`)
- продукты (`subcategory_id`: `12`)
- табак (`subcategory_id`: `13`)
- рестораны и бары (`subcategory_id`: `14`)

### **2. Шопинг** (`category_id`: `2`)
- одежда (`subcategory_id`: `21`)
- обувь (`subcategory_id`: `22`)
- техника (`subcategory_id`: `23`)
- косметика (`subcategory_id`: `24`)
- товары для дома (`subcategory_id`: `25`)
- игрушки и подарки (`subcategory_id`: `26`)

### **3. Транспорт** (`category_id`: `3`)
- бензин (`subcategory_id`: `31`)
- такси (`subcategory_id`: `32`)
- билеты (`subcategory_id`: `33`)
- парковка (`subcategory_id`: `34`)
- автоуслуги (`subcategory_id`: `35`)

### **4. Здоровье** (`category_id`: `4`)
- аптека (`subcategory_id`: `41`)
- медицинские услуги (`subcategory_id`: `42`)
- страхование (`subcategory_id`: `43`)
- витамины и БАДы (`subcategory_id`: `44`)

### **5. Прочее** (`category_id`: `5`)
- подкатегория не обязательна  
→ `subcategory`: `null`, `subcategory_id`: `0`

## Логика и правила:
- Указывай категорию и подкатегорию **для каждого товара отдельно**.
- Названия товаров должны быть максимально точными.
- Если данные частично нечитаемы — опусти поле.
- Если не уверен в категории — используй `"Прочее"`.
- Все цены — **числа** (например, 189.90, без кавычек).
"""

async def analyze_receipt_from_bytes(image_bytes: bytes) -> str:
    image_base64 = base64.b64encode(image_bytes).decode("utf-8")

    response = openai.ChatCompletion.create(
        model="gpt-4o",
        messages=[
            {
                "role": "system",
                "content": "Ты — ассистент, который анализирует фото товарных чеков и возвращает строго заданный JSON."
            },
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": PROMPT},
                    {"type": "image_url", "image_url": {
                        "url": f"data:image/jpeg;base64,{image_base64}"
                    }}
                ]
            }
        ],
        temperature=0.1,
        max_tokens=2000
    )

    return response.choices[0].message["content"]

last_check_store = {}
