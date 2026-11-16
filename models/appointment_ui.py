import pytz

from odoo import api, fields, models


class ClinicAppointmentUI(models.Model):
    """Display-only helper fields for the appointment ticket UI (nothing stored)."""
    _inherit = 'clinic.appointment'

    time_label = fields.Char(compute='_compute_ui_labels')
    day_label = fields.Char(compute='_compute_ui_labels')
    is_today = fields.Boolean(compute='_compute_ui_labels')
    is_overdue = fields.Boolean(compute='_compute_ui_labels')
    patient_initials = fields.Char(compute='_compute_ui_labels')
    doctor_initials = fields.Char(compute='_compute_ui_labels')

    @staticmethod
    def _make_initials(name):
        words = (name or '').replace('Dr.', '').split()
        return ''.join(w[0] for w in words[:2]).upper() or '?'

    @api.depends('appointment_date', 'state', 'patient_id.name', 'doctor_id.name')
    def _compute_ui_labels(self):
        tz = pytz.timezone(self._get_booking_tz())
        now = fields.Datetime.now()
        today = pytz.utc.localize(now).astimezone(tz).date()
        for rec in self:
            rec.patient_initials = self._make_initials(rec.patient_id.name)
            rec.doctor_initials = self._make_initials(rec.doctor_id.name)
            if rec.appointment_date:
                local = pytz.utc.localize(rec.appointment_date).astimezone(tz)
                rec.time_label = local.strftime('%I:%M %p').lstrip('0')
                rec.day_label = local.strftime('%a, %d %b')
                rec.is_today = local.date() == today
                rec.is_overdue = rec.appointment_date < now and rec.state in ('draft', 'confirmed')
            else:
                rec.time_label = ''
                rec.day_label = ''
                rec.is_today = False
                rec.is_overdue = False