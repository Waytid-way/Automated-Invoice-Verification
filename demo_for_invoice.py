from typhoon_ocr import ocr_document
import requests
import os
import json
import re
import matplotlib.pyplot as plt
from pdf2image import convert_from_path

# --- Configuration ---
llm_api = "http://localhost:11434/v1"
ocr_model = "scb10x/typhoon-ocr1.5-3b"
llm_structure_model = "scb10x/typhoon2.5-qwen3-4b"

# --- Mock Database (จำลองฐานข้อมูล Mango Anywhere/ERP) ---
DATABASE_PO = {
    "PO-2023-001": {"vendor": "บริษัท วัสดุก่อสร้าง จำกัด", "approved_amount": 10700.00, "status": "Approved"},
    "PO-2023-002": {"vendor": "ร้านเหล็กไทย", "approved_amount": 50000.00, "status": "Approved"},
    "IV1806-0002": {"vendor": "surebattstore", "approved_amount": 410.00, "status": "Approved"} #ตัวอย่างจริง
}

# --- Clean JSON ---
# บางที LLM จะตอบมาพร้อมกับ ```json ... ``` เราต้องล้างออกก่อน
def clean_json_response(text):
    text = re.sub(r'```json', '', text)
    text = re.sub(r'```', '', text)
    return text.strip()

# ==========================================
# Step 1: OCR (Extraction - Eyes)
# ==========================================
input_path = r"invoice_sample.jpg"
print("--- Scanning Document... ---")

try:
    markdown_text = ocr_document(
        input_path,
        base_url=llm_api,
        api_key="ollama",
        model=ocr_model, #typhoon-ocr1.5-3b
        page_num=1
    )
    print(f'[OCR Result]: Document scanned successfully.')
    print(f'This is markdown text \n {markdown_text}')
except Exception as e:
    print(f"Error during OCR: {e}")
    markdown_text = "จำลองข้อความ: ใบแจ้งหนี้ เลขที่ INV-999 อ้างถึงใบสั่งซื้อ PO-2023-001 ยอดรวมสุทธิ 10,700.00 บาท บริษัท วัสดุก่อสร้าง จำกัด" # Fallback สำหรับเทสถ้าไม่มีไฟล์

# ==========================================
# Step 2: Extract Structured Info (Reasoning - Brain)
# ==========================================
print("--- Extracting Data with LLM... ---")

prompt_for_llm_structure = f"""
คุณคือผู้ช่วยฝ่ายบัญชี หน้าที่ของคุณคือดึงข้อมูลจากข้อความ OCR ของใบแจ้งหนี้ (Invoice)
โดยให้ดึงข้อมูลดังนี้:
1. invoice_number (เลขที่ใบแจ้งหนี้)
2. po_reference (เลขที่ใบสั่งซื้อที่อ้างถึง มักขึ้นต้นด้วย PO)
3. total_amount (ยอดเงินรวมสุทธิ ขอเป็นตัวเลขเท่านั้น ไม่เอาเครื่องหมายลูกน้ำ)
4. vendor_name (ชื่อบริษัทผู้ขาย)

Text from OCR:
{markdown_text}

Return output as JSON format only. Keys: "invoice_number", "po_reference", "total_amount", "vendor_name"
"""

response = requests.post(
    f"{llm_api}/chat/completions",
    json={
        "model": llm_structure_model, #typhoon2.5-qwen3-4b
        "messages": [{"role": "user", "content": prompt_for_llm_structure}],
        "temperature": 0,
    }
)
result = response.json()
raw_content = result["choices"][0]["message"]["content"]
cleaned_json = clean_json_response(raw_content)

try:
    extracted_data = json.loads(cleaned_json)
    print(f"[Extracted Data]: {json.dumps(extracted_data, indent=4, ensure_ascii=False)}")
except json.JSONDecodeError:
    print("Failed to parse JSON from LLM")
    extracted_data = {}

# ==========================================
# Step 3: Verification Agent Logic (Action - Agent)
# ==========================================
print("\n--- Agent Verification Process ---")

if extracted_data:
    invoice_number = extracted_data.get("invoice_number") # IV1806-0002
    invoice_amount = float(extracted_data.get("total_amount", 0)) # 410
    
    # 3.1 Check if invoice_number exists
    if invoice_number in DATABASE_PO:
        db_record = DATABASE_PO[invoice_number] #เช็คใน db ว่ามี invoice_number นี้ไหม
        print(f"Found PO: {invoice_number} in Database.")
        
        # 3.2 Verify Amount (Cross-check)
        db_amount = db_record["approved_amount"] #ดึง ยอดของ บิลนี้มา
        
        if invoice_amount == db_amount:
            print(f"STATUS: PASSED | ยอดเงินตรงกัน ({invoice_amount} บาท)")
            print(">> Action: ส่งต่อให้ฝ่ายการเงินอนุมัติจ่าย")
        else:
            print(f"STATUS: FAILED | ยอดเงินไม่ตรง (Invoice: {invoice_amount} vs PO: {db_amount})")
            print(">> Action: แจ้งเตือนจัดซื้อให้ตรวจสอบส่วนต่าง")
            
    else:
        print(f"STATUS: WARNING | ไม่พบเลขที่ PO: {invoice_number} ในระบบ")
        print(">> Action: ตีกลับเอกสาร ขอให้ระบุเลข PO ที่ถูกต้อง")
else:
    print("Error: No data extracted.")

# ==========================================
# Step 4: Visualization
# ==========================================
if os.path.exists(input_path):
    ext = os.path.splitext(input_path)[1].lower()

    if ext == ".pdf":
        pages = convert_from_path(input_path, dpi=200)
        if pages:
            plt.figure(figsize=(8, 10))
            plt.imshow(pages[0])
            plt.title(f"Invoice: {extracted_data.get('invoice_number', 'Unknown')}")
            plt.axis('off')
            plt.show()

    elif ext in [".jpg", ".jpeg", ".png"]:
        img = plt.imread(input_path)
        plt.figure(figsize=(8, 10))
        plt.imshow(img)
        plt.axis('off')
        plt.show()


# Support type Images: PNG, JPEG /Documents: PDF