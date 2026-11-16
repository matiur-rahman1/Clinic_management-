from datetime import datetime, time, timedelta

import pytz

from odoo import api, fields, models


class ClinicAppointmentDashboard(models.Model):
    _inherit = 'clinic.appointment'

    @api.model
    def get_dashboard_data(self):
        """All numbers for the staff dashboard in one call (JSON-safe)."""
        tz = pytz.timezone(self._get_booking_tz())
        now_local = pytz.utc.localize(fields.Datetime.now()).astimezone(tz)
        today = now_local.date()

        def to_utc(d):
            return tz.localize(datetime.combine(d, time.min)).astimezone(pytz.utc).replace(tzinfo=None)

        def local_hm(dt):
            return pytz.utc.localize(dt).astimezone(tz).strftime('%H:%M')

        t0, t1 = to_utc(today), to_utc(today + timedelta(days=1))
        month_start = today.replace(day=1)
        m0 = to_utc(month_start)
        day_domain = [('appointment_date', '>=', t0), ('appointment_date', '<', t1)]
        now = fields.Datetime.now()

        fu_domain = [('follow_up_date', '>=', today), ('follow_up_date', '<=', today + timedelta(days=7))]
        Queue = self.env['clinic.queue']
        queue_today = [('check_in_time', '>=', t0), ('check_in_time', '<', t1)]

        # ---- KPIs ----
        invoices = self.env['account.move'].sudo().search([
            ('move_type', '=', 'out_invoice'), ('state', '=', 'posted'),
            ('clinic_appointment_id', '!=', False), ('invoice_date', '>=', month_start),
        ])
        kpis = {
            'today_total': self.search_count(day_domain + [('state', '!=', 'cancelled')]),
            'today_done': self.search_count(day_domain + [('state', '=', 'done')]),
            'queue_waiting': Queue.search_count([('state', '=', 'waiting')] + queue_today),
            'queue_active': Queue.search_count([('state', '=', 'in_consultation')] + queue_today),
            'patients': self.env['clinic.patient'].search_count([]),
            'new_patients_month': self.env['clinic.patient'].search_count([('create_date', '>=', m0)]),
            'revenue': sum(invoices.mapped('amount_total')),
            'paid': sum(invoices.filtered(
                lambda m: m.payment_state in ('paid', 'in_payment')).mapped('amount_total')),
            'followups': self.search_count(fu_domain),
        }

        # ---- last 7 days ----
        week = []
        for i in range(6, -1, -1):
            d = today - timedelta(days=i)
            count = self.search_count([
                ('appointment_date', '>=', to_utc(d)),
                ('appointment_date', '<', to_utc(d + timedelta(days=1))),
                ('state', '!=', 'cancelled'),
            ])
            week.append({'label': d.strftime('%a'), 'date': d.strftime('%d %b'),
                         'count': count, 'today': i == 0})

        # ---- status split (this month) ----
        labels = dict(self._fields['state'].selection)
        status = [
            {'key': key, 'label': labels.get(key, key), 'count': count}
            for key, count in self._read_group(
                [('appointment_date', '>=', m0)], ['state'], ['__count'])
        ]

        # ---- busiest doctors (this month) ----
        doctors = [
            {'name': doc.name, 'count': count}
            for doc, count in self._read_group(
                [('appointment_date', '>=', m0), ('state', '!=', 'cancelled')],
                ['doctor_id'], ['__count'], order='__count desc', limit=5)
        ]

        # ---- today's schedule ----
        schedule = [{
            'id': a.id, 'name': a.name, 'patient': a.patient_id.name,
            'doctor': a.doctor_id.name, 'time': local_hm(a.appointment_date), 'state': a.state,
        } for a in self.search(
            day_domain + [('state', 'in', ('draft', 'confirmed', 'in_progress'))],
            order='appointment_date', limit=8)]

        # ---- live queue ----
        queue = [{
            'id': q.id, 'token': q.token_number, 'patient': q.patient_id.name,
            'doctor': q.doctor_id.name or '', 'state': q.state,
            'minutes': max(int((now - q.check_in_time).total_seconds() // 60), 0),
        } for q in Queue.search(
            [('state', 'in', ('waiting', 'in_consultation'))] + queue_today,
            order='check_in_time', limit=8)]

        # ---- follow-ups due in the next 7 days ----
        followups = [{
            'id': a.id, 'patient': a.patient_id.name, 'doctor': a.doctor_id.name,
            'date': a.follow_up_date.strftime('%d %b'), 'days': (a.follow_up_date - today).days,
        } for a in self.search(fu_domain, order='follow_up_date', limit=6)]

        return {
            'user': self.env.user.name,
            'hour': now_local.hour,
            'date_text': now_local.strftime('%A, %d %B %Y'),
            'currency': self.env.company.currency_id.symbol or '',
            'range': {'from': fields.Datetime.to_string(t0), 'to': fields.Datetime.to_string(t1),
                      'fu_from': today.isoformat(), 'fu_to': (today + timedelta(days=7)).isoformat()},
            'kpis': kpis,
            'week': week,
            'status': status,
            'doctors': doctors,
            'schedule': schedule,
            'queue': queue,
            'followups': followups,
        }