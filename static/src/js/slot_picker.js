/* Clinic slot picker: doctor + date -> free time buttons.
 * Writes the chosen local time ('YYYY-MM-DDTHH:MM') into a hidden "appointment_date" input. */
(function () {
    'use strict';

    function rpc(url, params) {
        return fetch(url, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({jsonrpc: '2.0', method: 'call', params: params}),
        }).then(function (r) { return r.json(); }).then(function (d) { return d.result; });
    }

    window.ClinicSlotPicker = function (o) {
        var form = o.form, dateEl = o.dateInput, box = o.slotsBox;
        var hidden = o.hidden, timeEl = o.timeInput;
        var onChange = o.onChange || function () {};
        var seq = 0;

        function setValue(v) {
            hidden.value = v || '';
            onChange(hidden.value);
        }

        function doctorId() {
            var el = form.querySelector('input[name="doctor_id"]:checked') ||
                     form.querySelector('select[name="doctor_id"]');
            return el && el.value ? el.value : '';
        }

        function hint(text, cls) {
            box.innerHTML = '';
            var d = document.createElement('div');
            d.className = 'small ' + (cls || 'text-muted');
            d.textContent = text;
            box.appendChild(d);
        }

        function render(res) {
            timeEl.classList.add('d-none');
            if (!res) { return hint('Could not load available times. Please try again.', 'text-danger'); }

            if (!res.has_schedule) {
                // Doctor has no weekly schedule: let the patient pick any time
                hint('Pick your preferred time:');
                timeEl.classList.remove('d-none');
                return;
            }
            if (!res.slots.length) {
                return hint('No free slots on this date. Please choose another date.', 'text-danger');
            }
            box.innerHTML = '';
            res.slots.forEach(function (s) {
                var b = document.createElement('button');
                b.type = 'button';
                b.className = 'btn btn-outline-primary btn-sm m-1 cl-slot';
                b.textContent = s.label;
                b.addEventListener('click', function () {
                    box.querySelectorAll('.cl-slot').forEach(function (x) {
                        x.classList.remove('btn-primary');
                        x.classList.add('btn-outline-primary');
                    });
                    b.classList.remove('btn-outline-primary');
                    b.classList.add('btn-primary');
                    setValue(s.value);
                });
                box.appendChild(b);
            });
        }

        function refresh() {
            setValue('');
            timeEl.value = '';
            timeEl.classList.add('d-none');
            var doc = doctorId(), day = dateEl.value;
            if (!doc || !day) {
                return hint('Select a doctor and a date to see available times.');
            }
            hint('Loading available times...');
            var token = ++seq;
            rpc('/clinic/slots', {doctor_id: doc, date: day}).then(function (res) {
                if (token === seq) { render(res); }
            }).catch(function () {
                if (token === seq) { render(null); }
            });
        }

        form.addEventListener('change', function (e) {
            if (e.target === dateEl || e.target.name === 'doctor_id') { refresh(); }
        });
        timeEl.addEventListener('change', function () {
            setValue(timeEl.value && dateEl.value ? dateEl.value + 'T' + timeEl.value : '');
        });

        // Capture phase: runs before the page's own submit handlers (loading spinner etc.)
        form.addEventListener('submit', function (e) {
            if (!hidden.value) {
                e.preventDefault();
                e.stopImmediatePropagation();
                var warn = box.querySelector('.cl-slot-warn');
                if (!warn) {
                    warn = document.createElement('div');
                    warn.className = 'cl-slot-warn text-danger small mt-2';
                    warn.textContent = 'Please select a time slot.';
                    box.appendChild(warn);
                }
            }
        }, true);

        refresh();
    };
})();