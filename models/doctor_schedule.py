from odoo import models, fields, api
from odoo.exceptions import ValidationError


class ClinicDoctorSchedule(models.Model):
    _name = 'clinic.doctor.schedule'
    _description = 'Doctor Weekly Schedule'
    _order = 'doctor_id, weekday, start_time'

    doctor_id = fields.Many2one('clinic.doctor', required=True, ondelete='cascade')
    weekday = fields.Selection([
        ('0', 'Monday'), ('1', 'Tuesday'), ('2', 'Wednesday'), ('3', 'Thursday'),
        ('4', 'Friday'), ('5', 'Saturday'), ('6', 'Sunday'),
    ], required=True, default='0')
    start_time = fields.Float(string='From', required=True, default=9.0)
    end_time = fields.Float(string='To', required=True, default=17.0)
    slot_duration = fields.Float(string='Slot Length', default=0.5, required=True)
    max_patients = fields.Integer(
        string='Max Patients', default=16,
        help="Maximum patients in this time window. Slot Length is calculated automatically.")

    @api.onchange('max_patients', 'start_time', 'end_time')
    def _onchange_max_patients(self):
        for rec in self:
            if rec.max_patients > 0 and rec.end_time > rec.start_time:
                minutes = round((rec.end_time - rec.start_time) * 60 / rec.max_patients)
                rec.slot_duration = max(minutes, 1) / 60.0

    @api.onchange('slot_duration')
    def _onchange_slot_duration(self):
        for rec in self:
            if rec.slot_duration > 0 and rec.end_time > rec.start_time:
                rec.max_patients = int((rec.end_time - rec.start_time) / rec.slot_duration + 1e-6)

    @api.constrains('start_time', 'end_time', 'slot_duration', 'max_patients')
    def _check_times(self):
        for rec in self:
            if not (0 <= rec.start_time < rec.end_time <= 24):
                raise ValidationError("Invalid schedule: 'From' must be before 'To'.")
            if rec.slot_duration < 1 / 60.0:
                raise ValidationError("Slot Length must be at least 1 minute.")
            if rec.max_patients < 0:
                raise ValidationError("Max Patients cannot be negative.")