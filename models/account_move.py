from odoo import fields, models

class AccountMove(models.Model):
    _inherit = 'account.move'

    clinic_appointment_id = fields.Many2one(
        'clinic.appointment', string='Clinic Appointment', index=True, copy=False
    )
