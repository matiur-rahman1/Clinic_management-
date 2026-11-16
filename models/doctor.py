import pytz
from datetime import datetime, time, timedelta

from odoo import models, fields, api


class ClinicDoctor(models.Model):
    _name = 'clinic.doctor'
    _description = 'Clinic Doctor'

    name = fields.Char(string='Doctor Name', required=True)
    specialty = fields.Selection([
        ('general', 'General Physician'),
        ('cardio', 'Cardiologist'),
        ('derma', 'Dermatologist'),
        ('pediatric', 'Pediatrician'),
        ('ortho', 'Orthopedist'),
    ], string='Specialty', required=True)

    # Consultation Fee & Income Account
    qualifications = fields.Char(string='Qualifications', help="Shown on the prescription, e.g. MBBS, FCPS (Medicine)")
    reg_no = fields.Char(string='Registration No.', help="Medical council registration number (BMDC)")
    consultation_fee = fields.Float(string='Consultation Fee', default=500.0)
    income_account = fields.Many2one('account.account', string='Income Account',
                                     domain="[('account_type', '=', 'income')]",
                                     help="Consultation fee will be posted to this account.")

    phone = fields.Char(string='Phone')
    email = fields.Char(string='Email')
    image = fields.Binary(string='Photo')
    signature = fields.Binary(string='Doctor Signature')

    schedule_ids = fields.One2many('clinic.doctor.schedule', 'doctor_id', string='Weekly Schedule')
    appointment_ids = fields.One2many('clinic.appointment', 'doctor_id', string='Appointments')
    appointment_count = fields.Integer(compute='_compute_appointment_count')

    # Live status (not stored, recalculated every time)
    today_count = fields.Integer(string="Today's Appointments", compute='_compute_today_status')
    available_now = fields.Boolean(string='Available Now', compute='_compute_today_status')
    availability_label = fields.Char(string='Availability', compute='_compute_today_status')

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @api.model
    def _hm(self, value):
        """float hours -> 'HH:MM'"""
        return '%02d:%02d' % divmod(round(value * 60), 60)

    @api.model
    def _today_range_utc(self):
        """(start, end, now_local): today in the clinic timezone, start/end as naive UTC datetimes."""
        tz = pytz.timezone(self.env['clinic.appointment']._get_booking_tz())
        now_local = pytz.utc.localize(fields.Datetime.now()).astimezone(tz)
        start = tz.localize(datetime.combine(now_local.date(), time.min)) \
            .astimezone(pytz.utc).replace(tzinfo=None)
        return start, start + timedelta(days=1), now_local

    # ------------------------------------------------------------------
    # Computes
    # ------------------------------------------------------------------
    @api.depends('appointment_ids')
    def _compute_appointment_count(self):
        data = {d.id: c for d, c in self.env['clinic.appointment']._read_group(
            [('doctor_id', 'in', self.ids)], ['doctor_id'], ['__count'])}
        for rec in self:
            rec.appointment_count = data.get(rec.id, 0)

    def _compute_today_status(self):
        start, end, now_local = self._today_range_utc()
        hour = now_local.hour + now_local.minute / 60.0
        weekday = str(now_local.weekday())
        counts = {d.id: c for d, c in self.env['clinic.appointment']._read_group(
            [('doctor_id', 'in', self.ids), ('state', '!=', 'cancelled'),
             ('appointment_date', '>=', start), ('appointment_date', '<', end)],
            ['doctor_id'], ['__count'])}
        for rec in self:
            rec.today_count = counts.get(rec.id, 0)
            if not rec.schedule_ids:
                rec.available_now = False
                rec.availability_label = 'No schedule set'
                continue
            lines = rec.schedule_ids.filtered(lambda s: s.weekday == weekday).sorted('start_time')
            current = lines.filtered(lambda s: s.start_time <= hour < s.end_time)
            if current:
                rec.available_now = True
                rec.availability_label = 'Available until %s' % self._hm(current[0].end_time)
                continue
            rec.available_now = False
            upcoming = lines.filtered(lambda s: s.start_time > hour)
            if upcoming:
                rec.availability_label = 'Next at %s' % self._hm(upcoming[0].start_time)
            elif lines:
                rec.availability_label = 'Done for today'
            else:
                rec.availability_label = 'Off today'

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def action_open_appointments(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Appointments',
            'res_model': 'clinic.appointment',
            'view_mode': 'calendar,list,form',
            'domain': [('doctor_id', '=', self.id)],
            'context': {'default_doctor_id': self.id},
        }

    def action_open_today(self):
        self.ensure_one()
        start, end, _now = self._today_range_utc()
        return {
            'type': 'ir.actions.act_window',
            'name': "Today's Appointments",
            'res_model': 'clinic.appointment',
            'view_mode': 'list,form',
            'domain': [('doctor_id', '=', self.id),
                       ('appointment_date', '>=', start), ('appointment_date', '<', end)],
            'context': {'default_doctor_id': self.id},
        }

    def action_book_appointment(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'New Appointment',
            'res_model': 'clinic.appointment',
            'view_mode': 'form',
            'target': 'current',
            'context': {'default_doctor_id': self.id},
        }

    # ------------------------------------------------------------------
    # Free slots (portal / website)
    # ------------------------------------------------------------------
    def get_available_slots(self, date, tz_name):
        """Free slots for `date` (local date).
        Returns [{'utc': naive UTC datetime, 'value': local 'YYYY-MM-DDTHH:MM', 'label': 'HH:MM'}]
        """
        self.ensure_one()
        tz = pytz.timezone(tz_name)
        day_start = tz.localize(datetime.combine(date, time.min)).astimezone(pytz.utc).replace(tzinfo=None)
        busy = self.env['clinic.appointment'].sudo().search([
            ('doctor_id', '=', self.id),
            ('state', '!=', 'cancelled'),
            ('appointment_date', '<', day_start + timedelta(days=1)),
            ('end_date', '>', day_start),
        ])
        now = fields.Datetime.now()
        slots = []
        for sch in self.schedule_ids.filtered(lambda s: s.weekday == str(date.weekday())):
            t = sch.start_time
            while t + sch.slot_duration <= sch.end_time + 1e-6:
                local = tz.localize(datetime.combine(date, time.min) + timedelta(minutes=round(t * 60)))
                start = local.astimezone(pytz.utc).replace(tzinfo=None)
                end = start + timedelta(minutes=round(sch.slot_duration * 60))
                if start > now and not any(b.appointment_date < end and b.end_date > start for b in busy):
                    slots.append({
                        'utc': start,
                        'value': local.strftime('%Y-%m-%dT%H:%M'),
                        'label': local.strftime('%H:%M'),
                    })
                t += sch.slot_duration
        return slots