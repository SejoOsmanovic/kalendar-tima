const badge = document.getElementById("registration-count");
let updating = false;

async function refreshCount() {
    if (document.hidden || updating) return;
    updating = true;
    try {
        const response = await fetch(badge.dataset.url, {cache: "no-store", redirect: "error"});
        if (!response.ok) return;
        const {count} = await response.json();
        if (Number.isInteger(count) && count >= 0 && badge.textContent !== String(count)) {
            badge.textContent = String(count);
        }
    } catch {
        // Keep the last count until the next successful check.
    } finally {
        updating = false;
    }
}

setInterval(refreshCount, 15000);
document.addEventListener("visibilitychange", refreshCount);
