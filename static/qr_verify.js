const qrVerifyForm = document.getElementById("qr-verify-form");
const qrVerifyButton = document.getElementById("qr-verify-submit");
const qrAlert = document.getElementById("qr-alert");
const qrResult = document.getElementById("qr-result");
const qrHistoryList = document.getElementById("qr-history-list");
const qrHistoryBadge = document.getElementById("qr-history-badge");
const qrCurrentStatus = document.getElementById("qr-current-status");
const qrStatusNote = document.getElementById("qr-status-note");

function escapeHtml(value) {
    return String(value)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}

function getStatusClass(status) {
    const normalizedStatus = String(status || "unknown").toLowerCase();
    return ["authentic", "tampered", "unknown"].includes(normalizedStatus)
        ? normalizedStatus
        : "unknown";
}

function humanizeVerificationMode(mode) {
    const modeLabels = {
        "document-id": "QR record match",
        "auto-match": "Auto match"
    };
    return modeLabels[mode] || mode || "Unknown";
}

function toggleLoading(button, isLoading, label) {
    if (!button) return;
    button.disabled = isLoading;
    button.textContent = isLoading ? `${label}...` : label;
}

function showAlert(type, message) {
    if (!qrAlert) return;
    qrAlert.className = `alert ${type}`;
    qrAlert.textContent = message;
}

function hideAlert() {
    if (!qrAlert) return;
    qrAlert.className = "alert hidden";
    qrAlert.textContent = "";
}

function renderDocumentSummary(summary) {
    if (!summary || !qrCurrentStatus || !qrStatusNote) return;

    const latestStatus = summary.last_verification_status || "Awaiting Verification";
    qrCurrentStatus.className = `status ${getStatusClass(latestStatus)}`;
    qrCurrentStatus.textContent = latestStatus;
    qrStatusNote.textContent = summary.last_verified_at
        ? `Last checked on ${summary.last_verified_at}.`
        : "No verification attempts have been recorded yet.";
}

function renderHistoryItem(item) {
    const status = item.status || "Unknown";
    const reason = item.reason || "Verification completed.";
    const modifiedSections = Array.isArray(item.modified_sections) ? item.modified_sections : [];
    const modifiedChip = modifiedSections.length
        ? `<span class="chip">Modified: ${escapeHtml(modifiedSections.join(", "))}</span>`
        : "";

    return `
        <article class="history-item">
            <div class="history-item-head">
                <span class="status ${getStatusClass(status)}">${escapeHtml(status)}</span>
                <span class="history-time">${escapeHtml(item.verified_at || "-")}</span>
            </div>
            <p class="history-reason">${escapeHtml(reason)}</p>
            <div class="meta-row">
                <span class="chip">${escapeHtml(item.uploaded_filename || "Unknown file")}</span>
                <span class="chip">${escapeHtml(String(item.uploaded_doc_type || "unknown").toUpperCase())}</span>
                <span class="chip">${escapeHtml(humanizeVerificationMode(item.verification_mode))}</span>
                ${modifiedChip}
            </div>
        </article>
    `;
}

function renderHistory(history) {
    if (!qrHistoryList) return;

    if (!Array.isArray(history) || !history.length) {
        qrHistoryList.innerHTML = "<p class=\"empty-state\">No verification attempts have been recorded for this document yet.</p>";
        if (qrHistoryBadge) {
            qrHistoryBadge.textContent = "Latest 0";
        }
        return;
    }

    qrHistoryList.innerHTML = history.map(renderHistoryItem).join("");
    if (qrHistoryBadge) {
        qrHistoryBadge.textContent = `Latest ${history.length}`;
    }
}

function renderResult(payload) {
    if (!qrResult) return;

    const result = payload.verification_result || {};
    const status = result.status || "Unknown";
    const reason = result.reason || "Verification completed.";
    const modifiedSections = Array.isArray(result.modified_pages) ? result.modified_pages : [];
    const modifiedSectionHtml = modifiedSections.length
        ? `
            <p class="result-copy">Modified sections detected:</p>
            <div class="meta-row">
                ${modifiedSections.map((sectionName) => `<span class="chip">${escapeHtml(sectionName)}</span>`).join("")}
            </div>
        `
        : "";

    qrResult.innerHTML = `
        <h3>Verification Result</h3>
        <div class="result-head">
            <span class="status ${getStatusClass(status)}">${escapeHtml(status)}</span>
            <span class="result-time">${escapeHtml(payload.verification_timestamp || "-")}</span>
        </div>
        <p class="result-copy">${escapeHtml(reason)}</p>
        <div class="detail-grid compact-grid">
            <div class="detail-card">
                <span class="detail-label">Uploaded File</span>
                <strong class="detail-value">${escapeHtml(payload.uploaded_filename || "-")}</strong>
            </div>
            <div class="detail-card">
                <span class="detail-label">Uploaded Type</span>
                <strong class="detail-value">${escapeHtml(String(payload.uploaded_doc_type || "-").toUpperCase())}</strong>
            </div>
            <div class="detail-card">
                <span class="detail-label">Matched Record</span>
                <strong class="detail-value">${escapeHtml(payload.matched_document_id || "-")}</strong>
            </div>
            <div class="detail-card">
                <span class="detail-label">Verification Mode</span>
                <strong class="detail-value">${escapeHtml(humanizeVerificationMode(payload.verification_mode))}</strong>
            </div>
        </div>
        ${modifiedSectionHtml}
    `;

    qrResult.classList.remove("hidden");
}

async function parseJsonResponse(response) {
    let data = {};
    try {
        data = await response.json();
    } catch {
        data = {};
    }

    if (!response.ok) {
        throw new Error(data.error || "Verification request failed.");
    }

    return data;
}

if (qrVerifyForm) {
    qrVerifyForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        hideAlert();

        const formData = new FormData(qrVerifyForm);

        try {
            toggleLoading(qrVerifyButton, true, "Verifying");
            const response = await fetch(qrVerifyForm.action, {
                method: "POST",
                body: formData
            });
            const payload = await parseJsonResponse(response);
            renderResult(payload);
            renderDocumentSummary(payload.document_summary);
            renderHistory(payload.recent_verifications);
            showAlert("success", "Verification completed successfully.");
        } catch (error) {
            showAlert("error", error.message);
        } finally {
            toggleLoading(qrVerifyButton, false, "Verify Document");
        }
    });
}
