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

    global.HSM = global.HSM || {};
    global.HSM.throttle = throttle;
    global.HSM.debounce = debounce;
}(window));