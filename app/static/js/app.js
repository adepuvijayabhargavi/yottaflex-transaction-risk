/**
 * YottaFlex Operations Interface Core Scripts
 */
document.addEventListener("DOMContentLoaded", () => {
    // Handle close buttons on flash alerts
    document.querySelectorAll(".btn-close[data-bs-dismiss='alert']").forEach((button) => {
        button.addEventListener("click", (event) => {
            const alertElement = event.target.closest(".alert");
            if (alertElement) {
                alertElement.style.transition = "opacity 0.3s ease";
                alertElement.style.opacity = "0";
                setTimeout(() => alertElement.remove(), 300);
            }
        });
    });

    // Auto-dismiss success flash messages after 6 seconds
    document.querySelectorAll(".alert-success").forEach((alertElement) => {
        setTimeout(() => {
            if (alertElement && alertElement.parentNode) {
                alertElement.style.transition = "opacity 0.5s ease";
                alertElement.style.opacity = "0";
                setTimeout(() => alertElement.remove(), 500);
            }
        }, 6000);
    });
});
