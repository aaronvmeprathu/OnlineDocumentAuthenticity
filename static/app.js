const registerForm = document.getElementById("register-form");
const verifyForm = document.getElementById("verify-form");
const registerButton = document.getElementById("register-submit");
const verifyButton = document.getElementById("verify-submit");
const alertBox = document.getElementById("alert-box");
const registerResult = document.getElementById("register-result");
const verifyResult = document.getElementById("verify-result");
const docIdInput = document.getElementById("doc-id");

function escapeHtml(value) {
    return String(value)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}

function normalizeAssetPath(path) {
    if (!path) return "";
    if (path.startsWith("/")) return path;
    return `/${path}`;
}

function toggleLoading(button, isLoading, label) {
    if (!button) return;
    button.disabled = isLoading;
    button.textContent = isLoading ? `${label}...` : label;
}

function showAlert(type, message) {
    if (!alertBox) return;
    alertBox.className = `alert ${type}`;
    alertBox.textContent = message;
}

function hideAlert() {
    if (!alertBox) return;
    alertBox.className = "alert hidden";
    alertBox.textContent = "";
}

function showRegisterResult(payload) {
    if (!registerResult) return;

    const safeDocId = escapeHtml(payload.document_id || "-");
    const qrPath = normalizeAssetPath(payload.qr_code);
    const verificationUrl = escapeHtml(payload.verification_url || "");
    const qrSection = qrPath
        ? `
            <div class="qr-wrap">
                <span>Verification QR</span>
                <img src="${escapeHtml(qrPath)}?v=${Date.now()}" alt="QR code for document verification" />
            </div>
        `
        : "";
    const verificationLink = verificationUrl
        ? `<p>Verification link: <a href="${verificationUrl}" target="_blank" rel="noreferrer">${verificationUrl}</a></p>`
        : "";
    const serverHint = verificationUrl
        ? (
            payload.qr_remote_ready
                ? "<p>The QR code is using the server's current public address.</p>"
                : "<p>The QR code currently points to a local-only address. Set <code>PUBLIC_BASE_URL</code> or open the app using your LAN/server URL before sharing it.</p>"
        )
        : "";

    registerResult.innerHTML = `
        <h3>Registration Complete</h3>
        <p class="doc-id">${safeDocId}</p>
        <p>Your file has been fingerprinted and stored for integrity verification.</p>
        ${verificationLink}
        ${serverHint}
        ${qrSection}
    `;

    registerResult.classList.remove("hidden");
}

function showVerifyResult(payload) {
    if (!verifyResult) return;

    const data = payload.verification_result || {};
    const status = data.status || "Unknown";
    const normalizedStatus = status.toLowerCase();
    const isAuthentic = normalizedStatus === "authentic";
    const statusClass = ["authentic", "tampered", "unknown"].includes(normalizedStatus)
        ? normalizedStatus
        : "unknown";
    const pages = Array.isArray(data.modified_pages) ? data.modified_pages : [];
    const reason = data.reason ? `<p>${escapeHtml(data.reason)}</p>` : "";
    const matchedId = payload.matched_document_id
        ? `<p>Matched record: <span class="doc-id">${escapeHtml(payload.matched_document_id)}</span></p>`
        : "";

    const chips = pages.length
        ? `<div class="meta-row">${pages.map((page) => `<span class="chip">${escapeHtml(page)}</span>`).join("")}</div>`
        : "";

    verifyResult.innerHTML = `
        <h3>Verification Result</h3>
        <span class="status ${statusClass}">${escapeHtml(status)}</span>
        ${matchedId}
        ${reason}
        ${pages.length ? "<p>Modified sections detected:</p>" : (isAuthentic ? "<p>No modifications detected.</p>" : "")}
        ${chips}
    `;

    verifyResult.classList.remove("hidden");
}

async function parseJsonResponse(response) {
    let data = {};
    try {
        data = await response.json();
    } catch {
        data = {};
    }

    if (!response.ok) {
        const message = data.error || "Request failed. Please check your input and try again.";
        throw new Error(message);
    }

    return data;
}

if (registerForm) {
    registerForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        hideAlert();

        const formData = new FormData(registerForm);

        try {
            toggleLoading(registerButton, true, "Registering");
            const response = await fetch(registerForm.action, {
                method: "POST",
                body: formData
            });
            const payload = await parseJsonResponse(response);
            showRegisterResult(payload);

            if (docIdInput && payload.document_id) {
                docIdInput.value = payload.document_id;
            }

            showAlert("success", "Document registered successfully.");
        } catch (error) {
            showAlert("error", error.message);
        } finally {
            toggleLoading(registerButton, false, "Register Document");
        }
    });
}

if (verifyForm) {
    verifyForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        hideAlert();

        const formData = new FormData(verifyForm);

        try {
            toggleLoading(verifyButton, true, "Verifying");
            const response = await fetch(verifyForm.action, {
                method: "POST",
                body: formData
            });
            const payload = await parseJsonResponse(response);
            showVerifyResult(payload);
            showAlert("success", "Verification completed.");
        } catch (error) {
            showAlert("error", error.message);
        } finally {
            toggleLoading(verifyButton, false, "Verify Document");
        }
    });
}
