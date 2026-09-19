const flashToastStorageKey = 'cronator:flash-toast';

window.showToast = function showToast(message, type = 'info', timeoutMs = 2000) {
    const container = document.getElementById('toast-container');
    if (!container) {
        return;
    }

    const toneConfig = {
        success: {
            label: 'Success',
            panelClass: 'border-success/30 bg-base-100/95',
            labelClass: 'text-success',
            dotClass: 'bg-success',
        },
        error: {
            label: 'Error',
            panelClass: 'border-error/30 bg-base-100/95',
            labelClass: 'text-error',
            dotClass: 'bg-error',
        },
        warning: {
            label: 'Warning',
            panelClass: 'border-warning/30 bg-base-100/95',
            labelClass: 'text-warning',
            dotClass: 'bg-warning',
        },
        info: {
            label: 'Info',
            panelClass: 'border-info/30 bg-base-100/95',
            labelClass: 'text-info',
            dotClass: 'bg-info',
        },
    };

    const selectedTone = toneConfig[type] || toneConfig.info;
    const tone = {
        label: selectedTone.label,
        panelClass: selectedTone.panelClass,
        labelClass: selectedTone.labelClass,
        dotClass: selectedTone.dotClass,
    };

    const el = document.createElement('div');
    el.setAttribute('data-testid', 'toast');
    el.setAttribute('data-toast-level', type);
    el.setAttribute('role', 'alert');
    el.className = `shadow-lg border rounded-box backdrop-blur-sm ${tone.panelClass}`;
    el.style.pointerEvents = 'auto';
    el.style.width = '100%';
    el.style.padding = '0.9rem 1rem';
    el.style.borderRadius = '0.9rem';
    el.style.display = 'flex';
    el.style.flexDirection = 'column';
    el.style.alignItems = 'flex-start';
    el.style.gap = '0.35rem';
    el.style.boxShadow = '0 14px 32px rgba(0,0,0,0.28)';
    el.style.transform = 'translateX(100%)';
    el.style.opacity = '0';
    el.style.transition = 'transform 0.3s ease-out, opacity 0.3s ease-out';
    el.style.backdropFilter = 'blur(10px)';

    const label = document.createElement('div');
    label.className = `flex items-center gap-2 text-[0.72rem] font-bold uppercase tracking-[0.08em] ${tone.labelClass}`;

    const dot = document.createElement('span');
    dot.className = tone.dotClass;
    dot.style.width = '0.55rem';
    dot.style.height = '0.55rem';
    dot.style.borderRadius = '9999px';

    const labelText = document.createElement('span');
    labelText.textContent = tone.label;

    label.appendChild(dot);
    label.appendChild(labelText);

    const body = document.createElement('div');
    body.className = 'text-sm break-words text-base-content';
    body.style.lineHeight = '1.45';
    body.textContent = String(message);

    el.appendChild(label);
    el.appendChild(body);
    container.appendChild(el);

    requestAnimationFrame(() => {
        el.style.transform = 'translateX(0)';
        el.style.opacity = '1';
    });

    const remove = () => {
        el.style.transition = 'transform 0.5s ease-in-out, opacity 0.5s ease-in-out';
        el.style.transform = 'translateX(50px)';
        el.style.opacity = '0';
        setTimeout(() => {
            if (el && el.parentNode) el.parentNode.removeChild(el);
        }, 500);
    };
    setTimeout(remove, timeoutMs);
};

window.queueToast = function queueToast(message, type = 'info', timeoutMs = 2000) {
    if (!message) {
        return;
    }

    try {
        sessionStorage.setItem(
            flashToastStorageKey,
            JSON.stringify({
                message: String(message),
                type,
                timeoutMs,
            })
        );
    } catch (error) {
        console.warn('Failed to queue toast for the next page', error);
    }
};

function consumeQueuedToast() {
    let rawToast = null;

    try {
        rawToast = sessionStorage.getItem(flashToastStorageKey);
        if (!rawToast) {
            return;
        }

        sessionStorage.removeItem(flashToastStorageKey);
        const toast = JSON.parse(rawToast);
        if (toast?.message) {
            window.showToast(toast.message, toast.type || 'info', toast.timeoutMs || 2000);
        }
    } catch (error) {
        if (rawToast) {
            sessionStorage.removeItem(flashToastStorageKey);
        }
        console.warn('Failed to restore queued toast', error);
    }
}

consumeQueuedToast();

// F16: Theme toggle — persist to localStorage and POST to server
const themeSelect = document.getElementById('theme-select');
if (themeSelect) {
    const savedTheme = localStorage.getItem('crinator-theme');
    if (savedTheme && savedTheme !== themeSelect.value) {
        themeSelect.value = savedTheme;
        document.documentElement.setAttribute('data-theme', savedTheme);
    }
    themeSelect.addEventListener('change', async () => {
        const newTheme = themeSelect.value;
        document.documentElement.setAttribute('data-theme', newTheme);
        localStorage.setItem('crinator-theme', newTheme);
        try {
            await fetch('/api/settings/update', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ theme: newTheme }),
            });
        } catch (e) {
            console.warn('Failed to persist theme preference', e);
        }
    });
}

// Confirm dangerous actions
document.querySelectorAll('[data-confirm]').forEach(el => {
    el.addEventListener('click', (e) => {
        if (!confirm(el.dataset.confirm)) {
            e.preventDefault();
        }
    });
});
