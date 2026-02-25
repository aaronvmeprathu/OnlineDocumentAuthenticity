from flask import Flask, jsonify
from flask import render_template
import hashlib
from PyPDF2 import PdfReader
from flask import request
import os
import json
import time
from datetime import datetime
import qrcode


def verify_document(pdf_path, stored_pages):
    new_hashes = generate_page_hashes(pdf_path)

    result = {
        "status": "Authentic",
        "modified_pages": []
    }

    # Page count mismatch
    if len(new_hashes) != len(stored_pages):
        result["status"] = "Tampered"
        result["reason"] = "Page count mismatch"
        return result

    # Compare page by page
    for page, stored_hash in stored_pages.items():
        new_hash = new_hashes.get(page)

        if new_hash != stored_hash:
            result["status"] = "Tampered"
            result["modified_pages"].append(page)

    return result

def generate_qr(doc_id):
    qr_data = f"http://127.0.0.1:5000/qr-verify/{doc_id}"
    qr = qrcode.make(qr_data)

    qr_path = f"static/{doc_id}.png"
    qr.save(qr_path)

    return qr_path


app = Flask(__name__)
UPLOAD_FOLDER = "uploads"
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER


# ----------------------------
# PAGE-LEVEL HASH FUNCTION
# ----------------------------
def generate_page_hashes(pdf_path):
    reader = PdfReader(pdf_path)
    page_hashes = {}

    for i, page in enumerate(reader.pages):
        text = page.extract_text()
        if text is None:
            text = ""

        page_bytes = text.encode("utf-8")
        hash_value = hashlib.sha256(page_bytes).hexdigest()

        page_hashes[f"page_{i+1}"] = hash_value

    return page_hashes

# ----------------------------
# LOAD HASHES FROM FILE
# ----------------------------
def load_hashes():
    with open("data/hashes.json", "r") as f:
        return json.load(f)


# ----------------------------
# SAVE HASHES TO FILE
# ----------------------------
def save_hashes(data):
    with open("data/hashes.json", "w") as f:
        json.dump(data, f, indent=2)



# ----------------------------
# TEST HASH ROUTE
# ----------------------------
@app.route("/test-hash")
def test_hash():
    pdf_path = "uploads/sample.pdf"  # make sure this file exists
    hashes = generate_page_hashes(pdf_path)
    return jsonify(hashes)

@app.route("/register", methods=["POST"])
def register_document():
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    file = request.files["file"]

    if file.filename == "":
        return jsonify({"error": "No selected file"}), 400

    if not file.filename.lower().endswith(".pdf"):
        return jsonify({"error": "Only PDF files are supported"}), 400

    file_path = os.path.join(app.config["UPLOAD_FOLDER"], file.filename)
    file.save(file_path)

    # Generate page hashes
    page_hashes = generate_page_hashes(file_path)

    data = load_hashes()
    doc_id = f"doc_{int(time.time())}"

    data[doc_id] = {
        "filename": file.filename,
        "pages": page_hashes,
        "uploaded_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }

    save_hashes(data)
    qr_path = generate_qr(doc_id)


    return jsonify({
    "message": "Document registered successfully",
    "document_id": doc_id,
    "qr_code": qr_path
})




@app.route("/verify", methods=["POST"])
def verify():
    doc_id = request.form.get("doc_id")

    if not doc_id:
        return jsonify({"error": "Document ID required"}), 400

    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    file = request.files["file"]
    file_path = os.path.join(app.config["UPLOAD_FOLDER"], file.filename)
    file.save(file_path)

    data = load_hashes()

    if doc_id not in data:
        return jsonify({"error": "Document ID not found"}), 404

    stored_pages = data[doc_id]["pages"]
    verification_result = verify_document(file_path, stored_pages)

    return jsonify({
        "document_id": doc_id,
        "verification_result": verification_result
    })

@app.route("/qr-verify/<doc_id>")
def qr_verify_page(doc_id):
    return f"""
    <h2>QR Document Verification</h2>
    <form action="/verify" method="post" enctype="multipart/form-data">
        <input type="hidden" name="doc_id" value="{doc_id}">
        <input type="file" name="file" required />
        <button type="submit">Verify Document</button>
    </form>
    """
# ----------------------------
# HOME ROUTE
# ----------------------------
@app.route("/")
def home():
    return render_template("index.html")


if __name__ == "__main__":
    app.run(debug=True)

