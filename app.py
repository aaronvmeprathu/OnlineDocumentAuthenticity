"""Simple Flask app for registering documents and verifying their integrity."""

import hashlib
import ipaddress
import json
import os
import time
import uuid
from datetime import datetime
from urllib.parse import urlsplit
from zipfile import BadZipFile

import qrcode
from flask import Flask, jsonify, render_template, request, send_from_directory, url_for
from PIL import Image, ImageOps, UnidentifiedImageError
from PyPDF2 import PdfReader
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.utils import secure_filename


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_STORAGE_ROOT = BASE_DIR
STATIC_FOLDER = os.path.join(BASE_DIR, "static")
TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"

DOCUMENT_TYPE_BY_EXTENSION = {
    "pdf": "pdf",
    "docx": "docx",
    "png": "image",
    "jpg": "image",
    "jpeg": "image",
    "bmp": "image",
    "tif": "image",
    "tiff": "image",
    "webp": "image",
    "gif": "image",
}

SUPPORTED_TYPES_LABEL = "PDF, DOCX, PNG, JPG, JPEG, BMP, TIFF, WEBP, GIF"
UPLOAD_ACCEPT_ATTR = (
    ".pdf,.docx,.png,.jpg,.jpeg,.bmp,.tif,.tiff,.webp,.gif,"
    "image/*,application/pdf,"
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)

app = Flask(__name__, static_folder=STATIC_FOLDER, static_url_path="/static")
app.config["STORAGE_ROOT"] = os.environ.get("STORAGE_ROOT", DEFAULT_STORAGE_ROOT)
app.config["UPLOAD_FOLDER"] = os.path.join(app.config["STORAGE_ROOT"], "uploads")
app.config["DATA_FOLDER"] = os.path.join(app.config["STORAGE_ROOT"], "data")
app.config["QR_FOLDER"] = os.path.join(app.config["STORAGE_ROOT"], "qr_codes")
app.config["HASHES_FILE"] = os.path.join(app.config["DATA_FOLDER"], "hashes.json")
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1, x_prefix=1)


def ensure_storage_folders():
    """Create the folders the app uses if they are missing."""
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
    os.makedirs(app.config["DATA_FOLDER"], exist_ok=True)
    os.makedirs(app.config["QR_FOLDER"], exist_ok=True)
    os.makedirs(STATIC_FOLDER, exist_ok=True)


ensure_storage_folders()


def error_response(message, status_code):
    """Return a small JSON error payload."""
    return jsonify({"error": message}), status_code


def get_bool_env(env_name, default=False):
    """Read a boolean environment variable safely."""
    raw_value = os.environ.get(env_name)
    if raw_value is None:
        return default

    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


def get_server_host():
    """Return the host Flask should bind to."""
    return os.environ.get("APP_HOST", "0.0.0.0")


def get_server_port():
    """Return the port Flask should bind to."""
    raw_port = os.environ.get("PORT") or os.environ.get("APP_PORT") or "5000"

    try:
        return int(raw_port)
    except ValueError:
        return 5000


def get_public_base_url():
    """Return the public server URL used inside generated QR codes."""
    configured_base_url = os.environ.get("PUBLIC_BASE_URL", "").strip().rstrip("/")
    if configured_base_url:
        return configured_base_url

    return request.host_url.rstrip("/")


def build_public_url(endpoint, **values):
    """Build an externally reachable URL for a Flask endpoint."""
    return f"{get_public_base_url()}{url_for(endpoint, **values)}"


def is_local_only_url(url):
    """Detect URLs that only work on the same machine."""
    hostname = urlsplit(url).hostname or ""
    if hostname == "localhost":
        return True

    try:
        ip_address = ipaddress.ip_address(hostname)
    except ValueError:
        return False

    return ip_address.is_loopback or ip_address.is_unspecified


def get_file_extension(filename):
    """Return the file extension without the leading dot."""
    return os.path.splitext(filename)[1].lower().lstrip(".")


def get_hashes_file_path():
    """Return the path to the document registry JSON file."""
    return app.config["HASHES_FILE"]


def detect_document_type(filename):
    """Map a filename to one of our supported document types."""
    extension = get_file_extension(filename)
    return DOCUMENT_TYPE_BY_EXTENSION.get(extension)


def get_uploaded_file_from_request():
    """Read the uploaded file from the current request."""
    uploaded_file = request.files.get("file")

    if uploaded_file is None:
        return None, error_response("No file uploaded", 400)

    if uploaded_file.filename == "":
        return None, error_response("No selected file", 400)

    return uploaded_file, None


def save_uploaded_file(uploaded_file):
    """Save the uploaded file using a safe name and a unique stored name."""
    extension = get_file_extension(uploaded_file.filename)
    original_filename = secure_filename(uploaded_file.filename) or f"upload.{extension or 'bin'}"
    stored_filename = f"{uuid.uuid4().hex}.{extension}" if extension else uuid.uuid4().hex
    file_path = os.path.join(app.config["UPLOAD_FOLDER"], stored_filename)

    uploaded_file.save(file_path)
    return file_path, original_filename, stored_filename


def compare_content_hashes(current_hashes, saved_hashes):
    """Compare the uploaded file fingerprint against a saved fingerprint."""
    result = {
        "status": "Authentic",
        "modified_pages": [],
    }

    if len(current_hashes) != len(saved_hashes):
        result["status"] = "Tampered"
        result["reason"] = "Content structure mismatch"
        return result

    for section_name, saved_hash in saved_hashes.items():
        current_hash = current_hashes.get(section_name)
        if current_hash != saved_hash:
            result["status"] = "Tampered"
            result["modified_pages"].append(section_name)

    return result


def generate_pdf_hashes(pdf_path):
    """Hash the extracted text of each PDF page."""
    reader = PdfReader(pdf_path)
    page_hashes = {}

    for index, page in enumerate(reader.pages, start=1):
        page_text = page.extract_text() or ""
        page_hash = hashlib.sha256(page_text.encode("utf-8")).hexdigest()
        page_hashes[f"page_{index}"] = page_hash

    return page_hashes


def generate_docx_hashes(docx_path):
    """Hash each non-empty paragraph in a DOCX file."""
    try:
        from docx import Document as WordDocument
        from docx.opc.exceptions import PackageNotFoundError
    except ModuleNotFoundError as exc:
        raise ValueError(
            "DOCX support requires python-docx. Run: pip install -r requirements.txt"
        ) from exc

    try:
        document = WordDocument(docx_path)
    except (PackageNotFoundError, BadZipFile) as exc:
        raise ValueError("Unsupported or corrupted DOCX file") from exc

    paragraph_hashes = {}

    for index, paragraph in enumerate(document.paragraphs, start=1):
        paragraph_text = (paragraph.text or "").strip()
        if not paragraph_text:
            continue

        paragraph_hash = hashlib.sha256(paragraph_text.encode("utf-8")).hexdigest()
        paragraph_hashes[f"paragraph_{index}"] = paragraph_hash

    if not paragraph_hashes:
        paragraph_hashes["paragraph_1"] = hashlib.sha256(b"").hexdigest()

    return paragraph_hashes


def generate_image_hashes(image_path):
    """Hash the visible pixel data of an image."""
    try:
        with Image.open(image_path) as image:
            normalized_image = ImageOps.exif_transpose(image).convert("RGB")
            metadata = (
                f"{normalized_image.width}x{normalized_image.height}|{normalized_image.mode}"
            ).encode("utf-8")
            image_bytes = normalized_image.tobytes()
    except UnidentifiedImageError as exc:
        raise ValueError("Unsupported or corrupted image file") from exc

    image_hash = hashlib.sha256(metadata + image_bytes).hexdigest()
    return {"image_1": image_hash}


def generate_document_hashes(file_path, document_type):
    """Choose the correct hashing strategy for the uploaded file."""
    if document_type == "pdf":
        return generate_pdf_hashes(file_path)

    if document_type == "docx":
        return generate_docx_hashes(file_path)

    if document_type == "image":
        return generate_image_hashes(file_path)

    raise ValueError("Unsupported document type")


def verify_file_against_hashes(file_path, saved_hashes, document_type):
    """Generate fresh hashes for a file and compare them with saved hashes."""
    current_hashes = generate_document_hashes(file_path, document_type)
    return compare_content_hashes(current_hashes, saved_hashes)


def get_record_hashes(record):
    """Read hashes from both new and older saved record formats."""
    return record.get("content_hashes") or record.get("pages", {})


def get_record_document_type(record):
    """Read the saved document type, or infer it for older records."""
    saved_type = record.get("doc_type")
    if saved_type:
        return saved_type

    inferred_type = detect_document_type(record.get("filename", ""))
    return inferred_type or "pdf"


def find_best_document_match(current_hashes, registered_documents, document_type):
    """Find the closest saved record for an uploaded document."""
    best_document_id = None
    best_rank = None
    best_result = None

    for candidate_id, record in registered_documents.items():
        candidate_type = get_record_document_type(record)
        if candidate_type != document_type:
            continue

        saved_hashes = get_record_hashes(record)
        comparison = compare_content_hashes(current_hashes, saved_hashes)

        if comparison["status"] == "Authentic":
            comparison["reason"] = "Exact fingerprint match found"
            return candidate_id, comparison

        common_sections = set(current_hashes) & set(saved_hashes)
        matching_sections = sum(
            1 for section_name in common_sections
            if current_hashes.get(section_name) == saved_hashes.get(section_name)
        )

        rank = (
            int(len(current_hashes) == len(saved_hashes)),
            matching_sections,
            -abs(len(current_hashes) - len(saved_hashes)),
        )

        if best_rank is None or rank > best_rank:
            best_rank = rank
            best_document_id = candidate_id
            best_result = comparison

    if best_document_id is None:
        return None, {
            "status": "Unknown",
            "modified_pages": [],
            "reason": f"No registered {document_type} records found",
        }

    if best_rank[1] == 0:
        return None, {
            "status": "Unknown",
            "modified_pages": [],
            "reason": "No matching registered record found",
        }

    if "reason" not in best_result:
        best_result["reason"] = "Closest registered document match found"

    return best_document_id, best_result


def load_registered_documents():
    """Load all saved document records from disk."""
    hashes_file = get_hashes_file_path()
    if not os.path.exists(hashes_file):
        return {}

    with open(hashes_file, "r", encoding="utf-8") as file_handle:
        return json.load(file_handle)


def save_registered_documents(registered_documents):
    """Save all document records back to disk."""
    with open(get_hashes_file_path(), "w", encoding="utf-8") as file_handle:
        json.dump(registered_documents, file_handle, indent=2)


def create_document_id():
    """Create a short unique ID that is easy to copy into the UI."""
    return f"doc_{int(time.time())}_{uuid.uuid4().hex[:6]}"


def build_document_record(original_filename, stored_filename, document_type, content_hashes):
    """Create the JSON record we store for each registered document."""
    return {
        "filename": original_filename,
        "stored_filename": stored_filename,
        "doc_type": document_type,
        "content_hashes": content_hashes,
        "uploaded_at": datetime.now().strftime(TIMESTAMP_FORMAT),
    }


def generate_qr_code(doc_id, verification_url):
    """Create a QR code that opens the verification page for one document."""
    qr_image = qrcode.make(verification_url)
    qr_filename = f"{doc_id}.png"

    qr_image.save(os.path.join(app.config["QR_FOLDER"], qr_filename))
    return url_for("qr_code_asset", filename=qr_filename)


def verify_using_document_id(doc_id, file_path, uploaded_doc_type, registered_documents):
    """Verify an upload against one exact saved record."""
    record = registered_documents.get(doc_id)
    if record is None:
        return error_response("Document ID not found", 404)

    registered_doc_type = get_record_document_type(record)
    if registered_doc_type != uploaded_doc_type:
        return error_response(
            (
                f"Uploaded file type ({uploaded_doc_type}) does not match "
                f"registered type ({registered_doc_type})"
            ),
            400,
        )

    verification_result = verify_file_against_hashes(
        file_path=file_path,
        saved_hashes=get_record_hashes(record),
        document_type=registered_doc_type,
    )

    return jsonify({
        "verification_mode": "document-id",
        "uploaded_doc_type": uploaded_doc_type,
        "registered_doc_type": registered_doc_type,
        "matched_document_id": doc_id,
        "verification_result": verification_result,
    })


def verify_using_auto_match(file_path, uploaded_doc_type, registered_documents):
    """Verify an upload by finding the closest saved record automatically."""
    current_hashes = generate_document_hashes(file_path, uploaded_doc_type)
    matched_document_id, verification_result = find_best_document_match(
        current_hashes=current_hashes,
        registered_documents=registered_documents,
        document_type=uploaded_doc_type,
    )

    response_payload = {
        "verification_mode": "auto-match",
        "uploaded_doc_type": uploaded_doc_type,
        "verification_result": verification_result,
    }

    if matched_document_id:
        response_payload["matched_document_id"] = matched_document_id
        response_payload["registered_doc_type"] = get_record_document_type(
            registered_documents[matched_document_id]
        )

    return jsonify(response_payload)


@app.route("/test-hash")
def test_hash():
    """Small debug route for checking PDF hashing quickly."""
    sample_path = os.path.join(app.config["UPLOAD_FOLDER"], "sample.pdf")
    if not os.path.exists(sample_path):
        return error_response("Sample file not found", 404)

    return jsonify(generate_pdf_hashes(sample_path))


@app.route("/health")
def health_check():
    """Return a lightweight health response for deployment probes."""
    return jsonify({"status": "ok"})


@app.route("/register", methods=["POST"])
def register_document():
    """Register a document and save its fingerprint."""
    uploaded_file, upload_error = get_uploaded_file_from_request()
    if upload_error:
        return upload_error

    document_type = detect_document_type(uploaded_file.filename)
    if not document_type:
        return error_response(f"Supported file types: {SUPPORTED_TYPES_LABEL}", 400)

    file_path, original_filename, stored_filename = save_uploaded_file(uploaded_file)

    try:
        content_hashes = generate_document_hashes(file_path, document_type)
    except ValueError as exc:
        return error_response(str(exc), 400)

    registered_documents = load_registered_documents()
    doc_id = create_document_id()

    registered_documents[doc_id] = build_document_record(
        original_filename=original_filename,
        stored_filename=stored_filename,
        document_type=document_type,
        content_hashes=content_hashes,
    )

    save_registered_documents(registered_documents)
    verification_url = build_public_url("qr_verify_page", doc_id=doc_id)

    return jsonify({
        "message": "Document registered successfully",
        "document_id": doc_id,
        "doc_type": document_type,
        "qr_code": generate_qr_code(doc_id, verification_url),
        "verification_url": verification_url,
        "qr_remote_ready": not is_local_only_url(verification_url),
        "public_base_url": get_public_base_url(),
    })


@app.route("/verify", methods=["POST"])
def verify_document_route():
    """Verify an uploaded document either by ID or by auto-match."""
    requested_doc_id = (request.form.get("doc_id") or "").strip()

    uploaded_file, upload_error = get_uploaded_file_from_request()
    if upload_error:
        return upload_error

    uploaded_doc_type = detect_document_type(uploaded_file.filename)
    if not uploaded_doc_type:
        return error_response(f"Supported file types: {SUPPORTED_TYPES_LABEL}", 400)

    file_path, _, _ = save_uploaded_file(uploaded_file)
    registered_documents = load_registered_documents()

    if not registered_documents:
        return error_response("No registered documents found", 404)

    try:
        if requested_doc_id:
            return verify_using_document_id(
                doc_id=requested_doc_id,
                file_path=file_path,
                uploaded_doc_type=uploaded_doc_type,
                registered_documents=registered_documents,
            )

        return verify_using_auto_match(
            file_path=file_path,
            uploaded_doc_type=uploaded_doc_type,
            registered_documents=registered_documents,
        )
    except ValueError as exc:
        return error_response(str(exc), 400)


@app.route("/qr-verify/<doc_id>")
def qr_verify_page(doc_id):
    """Show a tiny upload form for QR-based verification."""
    return f"""
    <h2>QR Document Verification</h2>
    <form action="{url_for('verify_document_route')}" method="post" enctype="multipart/form-data">
        <input type="hidden" name="doc_id" value="{doc_id}">
        <input type="file" name="file" accept="{UPLOAD_ACCEPT_ATTR}" required />
        <button type="submit">Verify Document</button>
    </form>
    """


@app.route("/qr-code/<path:filename>")
def qr_code_asset(filename):
    """Serve generated QR code images from runtime storage."""
    return send_from_directory(app.config["QR_FOLDER"], filename)


@app.route("/")
def home():
    """Render the main page."""
    return render_template("index.html")


if __name__ == "__main__":
    app.run(
        host=get_server_host(),
        port=get_server_port(),
        debug=get_bool_env("FLASK_DEBUG", True),
    )
