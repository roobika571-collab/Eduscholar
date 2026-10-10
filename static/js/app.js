/**
 * EduScholar - Main JavaScript Application
 */

document.addEventListener('DOMContentLoaded', () => {
    initMobileNav();
    initFlashAlerts();
    initFormValidation();
    initFileUploads();
    initModals();
});

/* Mobile Navigation Toggle */
function initMobileNav() {
    const toggle = document.getElementById('mobileToggle');
    const menu = document.getElementById('navMenu');
    if (toggle && menu) {
        toggle.addEventListener('click', () => {
            menu.classList.toggle('open');
        });
    }
}

/* Auto-dismiss flash alerts after 5 seconds */
function initFlashAlerts() {
    const alerts = document.querySelectorAll('.alert');
    alerts.forEach(alert => {
        setTimeout(() => {
            alert.style.transition = 'opacity 0.5s ease, transform 0.5s ease';
            alert.style.opacity = '0';
            alert.style.transform = 'translateY(-10px)';
            setTimeout(() => alert.remove(), 500);
        }, 5000);
    });
}

/* Client-side form validations */
function initFormValidation() {
    // Check password confirmation match
    const passwordInputs = document.querySelectorAll('input[type="password"]');
    const pwd = document.querySelector('input[name="password"], input[name="new_password"]');
    const confirmPwd = document.querySelector('input[name="confirm_password"], input[name="confirm_new_password"]');

    if (pwd && confirmPwd) {
        const validateMatch = () => {
            if (confirmPwd.value && pwd.value !== confirmPwd.value) {
                confirmPwd.setCustomValidity('Passwords do not match');
            } else {
                confirmPwd.setCustomValidity('');
            }
        };
        pwd.addEventListener('input', validateMatch);
        confirmPwd.addEventListener('input', validateMatch);
    }

    // GPA validation
    const gpaInput = document.querySelector('input[name="gpa"]');
    if (gpaInput) {
        gpaInput.addEventListener('input', (e) => {
            const val = parseFloat(e.target.value);
            if (e.target.value && (isNaN(val) || val < 0.0 || val > 4.0)) {
                e.target.setCustomValidity('GPA must be a number between 0.00 and 4.00');
            } else {
                e.target.setCustomValidity('');
            }
        });
    }
}

/* Enhanced File Upload with Live Name Feedback & Size Verification */
function initFileUploads() {
    const fileInputs = document.querySelectorAll('input[type="file"]');
    fileInputs.forEach(input => {
        input.addEventListener('change', (e) => {
            const file = e.target.files[0];
            const feedbackElem = document.getElementById(input.id + '-feedback') || 
                                 input.closest('.form-group')?.querySelector('.file-feedback');
            
            if (file) {
                const maxBytes = 16 * 1024 * 1024; // 16MB
                if (file.size > maxBytes) {
                    alert('Selected file exceeds the 16MB limit. Please choose a smaller document.');
                    input.value = '';
                    if (feedbackElem) feedbackElem.textContent = '';
                    return;
                }

                const sizeMb = (file.size / (1024 * 1024)).toFixed(2);
                if (feedbackElem) {
                    feedbackElem.innerHTML = `<strong>Selected file:</strong> ${file.name} (${sizeMb} MB)`;
                    feedbackElem.style.color = '#0d9488';
                }
            }
        });
    });
}

/* Accessible Modal Management */
function initModals() {
    // Open modal buttons
    document.querySelectorAll('[data-modal-target]').forEach(button => {
        button.addEventListener('click', () => {
            const modalId = button.getAttribute('data-modal-target');
            const modal = document.getElementById(modalId);
            if (modal) {
                modal.classList.add('open');
                document.body.style.overflow = 'hidden';
            }
        });
    });

    // Close buttons inside modal
    document.querySelectorAll('.modal-close, [data-modal-close]').forEach(button => {
        button.addEventListener('click', (e) => {
            const modal = button.closest('.modal-overlay');
            if (modal) {
                modal.classList.remove('open');
                document.body.style.overflow = '';
            }
        });
    });

    // Close on background click
    document.querySelectorAll('.modal-overlay').forEach(modal => {
        modal.addEventListener('click', (e) => {
            if (e.target === modal) {
                modal.classList.remove('open');
                document.body.style.overflow = '';
            }
        });
    });
}
