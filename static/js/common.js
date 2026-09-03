(function (global) {
    'use strict';

    /**
     * Returns a throttled version of `fn` that runs at most once every
     * `limit` milliseconds. A leading call fires immediately; any trailing
     * calls made during the cooldown are collapsed into a single call at the
     * end so rapid bursts never swamp the network but no action is dropped.
     */
    function throttle(fn, limit) {
        limit = limit || 300;
        let lastRun = 0;
        let timer = null;
        return function () {
            const context = this;
            const args = arguments;
            const now = Date.now();
            const elapsed = now - lastRun;
            if (timer) {
                clearTimeout(timer);
                timer = null;
            }
            if (elapsed >= limit) {
                lastRun = now;
                fn.apply(context, args);
            } else {
                timer = setTimeout(function () {
                    lastRun = Date.now();
                    fn.apply(context, args);
                }, limit - elapsed);
            }
        };
    }

    /**
     * Returns a debounced version of `fn` that runs only after `wait`
     * milliseconds of silence following the last call.
     */
    function debounce(fn, wait) {
        wait = wait || 300;
        let timer = null;
        return function () {
            const context = this;
            const args = arguments;
            clearTimeout(timer);
            timer = setTimeout(function () {
                fn.apply(context, args);
            }, wait);
        };
    }

    // ——— Password visibility toggle (eye icon) ———
    function createEyeButton(input) {
        var btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'absolute top-1/2 right-0 px-3 -translate-y-1/2 text-slate-500 hover:text-slate-700 transition cursor-pointer';
        btn.setAttribute('tabindex', '-1');
        btn.setAttribute('aria-label', 'Show password');
        btn.innerHTML =
            '<svg class="eye-open w-5 h-5" fill="none" stroke="currentColor" stroke-width="1.8" viewBox="0 0 24 24" aria-hidden="true"><path stroke-linecap="round" stroke-linejoin="round" d="M2.036 12.322a1.012 1.012 0 010-.639C3.423 7.51 7.36 4.5 12 4.5c4.638 0 8.573 3.007 9.963 7.178.07.207.07.431 0 .639C20.577 16.49 16.64 19.5 12 19.5c-4.638 0-8.573-3.007-9.963-7.178z"/><path stroke-linecap="round" stroke-linejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"/></svg>' +
            '<svg class="eye-off w-5 h-5 hidden" fill="none" stroke="currentColor" stroke-width="1.8" viewBox="0 0 24 24" aria-hidden="true"><path stroke-linecap="round" stroke-linejoin="round" d="M3.98 8.223A10.477 10.477 0 001.934 12c1.292 4.338 5.31 7.5 10.066 7.5.993 0 1.953-.138 2.863-.395M6.228 6.228A10.45 10.45 0 0112 4.5c4.756 0 8.773 3.162 10.065 7.498a10.523 10.523 0 01-4.293 5.774M6.228 6.228L3 3m3.228 3.228l3.65 3.65m7.894 7.894L21 21m-3.228-3.228l-3.65-3.65m0 0a3 3 0 10-4.243-4.243m4.242 4.242L9.88 9.88"/></svg>';
        btn.addEventListener('click', function () {
            var isHidden = input.type === 'password';
            input.type = isHidden ? 'text' : 'password';
            btn.querySelector('.eye-open').classList.toggle('hidden', isHidden);
            btn.querySelector('.eye-off').classList.toggle('hidden', !isHidden);
            btn.setAttribute('aria-label', isHidden ? 'Hide password' : 'Show password');
        });
        return btn;
    }

    function initPasswordToggles() {
        var inputs = document.querySelectorAll('input[type="password"]');
        inputs.forEach(function (input) {
            // Skip if already enhanced or inside an already-enhanced wrapper
            if (input.dataset.toggleEnhanced) return;
            // Skip if the next sibling is already a toggle button (e.g. login.html renders its own)
            if (input.nextElementSibling && input.nextElementSibling.querySelector && input.nextElementSibling.querySelector('.eye-open')) return;
            var parent = input.parentElement;
            // Don't double-wrap inputs already in a relative container with a button
            if (parent && parent.querySelector('button .eye-open')) return;

            var wrapper = document.createElement('div');
            wrapper.className = 'relative';
            // Ensure input has right padding for the icon
            if (!input.classList.contains('pr-11') && !input.classList.contains('pr-10')) {
                input.classList.add('pr-11');
            }
            input.parentNode.insertBefore(wrapper, input);
            wrapper.appendChild(input);
            wrapper.appendChild(createEyeButton(input));
            input.dataset.toggleEnhanced = 'true';
        });
    }

    // global alias for inline onclick="togglePassword(...)" in login.html
    function togglePassword(inputId, btn) {
        var input = document.getElementById(inputId);
        if (!input || !btn) return;
        var isHidden = input.type === 'password';
        input.type = isHidden ? 'text' : 'password';
        var eyeOpen = btn.querySelector('.eye-open');
        var eyeOff = btn.querySelector('.eye-off');
        if (eyeOpen) eyeOpen.classList.toggle('hidden', isHidden);
        if (eyeOff) eyeOff.classList.toggle('hidden', !isHidden);
        btn.setAttribute('aria-label', isHidden ? 'Hide password' : 'Show password');
    }

    global.HSM = global.HSM || {};
    global.HSM.throttle = throttle;
    global.HSM.debounce = debounce;
    global.HSM.initPasswordToggles = initPasswordToggles;
    global.HSM.togglePassword = togglePassword;
    global.togglePassword = togglePassword;

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initPasswordToggles);
    } else {
        initPasswordToggles();
    }
}(window));