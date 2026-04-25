// Centralized realtime lifecycle manager to prevent duplicated streams and timers.
(function () {
	if (window.ORTRealtime) {
		return;
	}

	var _streams = new Map();
	var _pollers = new Map();
	var _statusPollers = new Map();

	function _safeCall(fn, payload) {
		try {
			if (typeof fn === "function") {
				fn(payload);
			}
		} catch (_) {}
	}

	function attachJobStream(opts) {
		if (!opts || !opts.jobId) {
			return null;
		}

		detachJobStream(opts.jobId);

		var source = new EventSource('/jobs/' + opts.jobId + '/events');

		source.addEventListener('log', function (event) {
			try {
				var data = JSON.parse(event.data || '{}');
				_safeCall(opts.onLog, data);
			} catch (_) {}
		});

		source.addEventListener('status', function (event) {
			try {
				var data = JSON.parse(event.data || '{}');
				_safeCall(opts.onStatus, data);
			} catch (_) {}
		});

		source.addEventListener('ai-report', function (event) {
			try {
				var data = JSON.parse(event.data || '{}');
				_safeCall(opts.onAiReport, data);
			} catch (_) {}
		});

		source.onerror = function () {
			detachJobStream(opts.jobId);
			_safeCall(opts.onError, { type: 'stream-error' });
		};

		_streams.set(opts.jobId, source);
		return source;
	}

	function detachJobStream(jobId) {
		var source = _streams.get(jobId);
		if (!source) {
			return;
		}
		try {
			source.close();
		} catch (_) {}
		_streams.delete(jobId);
	}

	function startAiFallbackPoll(opts) {
		if (!opts || !opts.jobId) {
			return;
		}

		stopAiFallbackPoll(opts.jobId);

		var delayMs = typeof opts.intervalMs === 'number' ? opts.intervalMs : 6000;
		var attempts = 0;
		var maxAttempts = typeof opts.maxAttempts === 'number' ? opts.maxAttempts : 120;
		var timer = null;

		function schedule(nextDelay) {
			timer = window.setTimeout(run, nextDelay);
			_pollers.set(opts.jobId, timer);
		}

		async function run() {
			attempts += 1;
			if (attempts > maxAttempts) {
				stopAiFallbackPoll(opts.jobId);
				return;
			}

			// Avoid stressing backend when tab is hidden.
			if (document.hidden) {
				schedule(Math.min(delayMs * 2, 30000));
				return;
			}

			try {
				var response = await fetch('/jobs/' + opts.jobId + '/api/status', {
					headers: { 'Cache-Control': 'no-cache' },
				});
				var data = await response.json();
				_safeCall(opts.onTick, data);

				if (data.ai_report_status && data.ai_report_status !== 'pending') {
					stopAiFallbackPoll(opts.jobId);
					_safeCall(opts.onDone, data);
					return;
				}
			} catch (_) {}

			schedule(delayMs);
		}

		schedule(delayMs);
	}

	function stopAiFallbackPoll(jobId) {
		var timer = _pollers.get(jobId);
		if (!timer) {
			return;
		}
		clearTimeout(timer);
		_pollers.delete(jobId);
	}

	function startJobStatusFallbackPoll(opts) {
		if (!opts || !opts.jobId) {
			return;
		}

		stopJobStatusFallbackPoll(opts.jobId);

		var delayMs = typeof opts.intervalMs === 'number' ? opts.intervalMs : 4000;
		var attempts = 0;
		var maxAttempts = typeof opts.maxAttempts === 'number' ? opts.maxAttempts : 450;
		var timer = null;

		function schedule(nextDelay) {
			timer = window.setTimeout(run, nextDelay);
			_statusPollers.set(opts.jobId, timer);
		}

		async function run() {
			attempts += 1;
			if (attempts > maxAttempts) {
				stopJobStatusFallbackPoll(opts.jobId);
				return;
			}

			if (document.hidden) {
				schedule(Math.min(delayMs * 2, 20000));
				return;
			}

			try {
				var response = await fetch('/jobs/' + opts.jobId + '/api/status', {
					headers: { 'Cache-Control': 'no-cache' },
				});
				var data = await response.json();
				_safeCall(opts.onTick, data);

				if (data.status && ['success', 'failed', 'cancelled'].indexOf(data.status) >= 0) {
					stopJobStatusFallbackPoll(opts.jobId);
					_safeCall(opts.onDone, data);
					return;
				}
			} catch (_) {}

			schedule(delayMs);
		}

		schedule(delayMs);
	}

	function stopJobStatusFallbackPoll(jobId) {
		var timer = _statusPollers.get(jobId);
		if (!timer) {
			return;
		}
		clearTimeout(timer);
		_statusPollers.delete(jobId);
	}

	function teardownAll() {
		Array.from(_streams.keys()).forEach(detachJobStream);
		Array.from(_pollers.keys()).forEach(stopAiFallbackPoll);
		Array.from(_statusPollers.keys()).forEach(stopJobStatusFallbackPoll);
	}

	window.ORTRealtime = {
		attachJobStream: attachJobStream,
		detachJobStream: detachJobStream,
		startAiFallbackPoll: startAiFallbackPoll,
		stopAiFallbackPoll: stopAiFallbackPoll,
		startJobStatusFallbackPoll: startJobStatusFallbackPoll,
		stopJobStatusFallbackPoll: stopJobStatusFallbackPoll,
		teardownAll: teardownAll,
	};
})();
