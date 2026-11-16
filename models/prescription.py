from odoo import models, fields, api
from odoo.exceptions import ValidationError

from .medicine import FORM_SELECTION, FORM_ABBR


class ClinicPrescriptionLine(models.Model):
    _name = 'clinic.prescription.line'
    _description = 'Prescription Line'
    _order = 'sequence, id'

    sequence = fields.Integer(default=10)
    appointment_id = fields.Many2one('clinic.appointment', string='Appointment', required=True, ondelete='cascade')
    patient_id = fields.Many2one('clinic.patient', string='Patient', related='appointment_id.patient_id', store=True)

    # Optional shortcut: picking a catalog entry fills the fields below. The doctor can ignore it
    # and simply type the drug name.
    medicine_id = fields.Many2one('clinic.medicine', string='Catalog', ondelete='set null')

    drug_name = fields.Char(string='Medicine', compute='_compute_drug_name', store=True,
                            readonly=False, precompute=True)
    strength = fields.Char(string='Strength', help="e.g. 500 mg")
    form = fields.Selection(FORM_SELECTION, string='Form')

    dosage = fields.Char(string='Frequency', required=True, help="e.g. 1+0+1 or 1 tab every 8 hours")
    duration = fields.Char(string='Duration', help="e.g. 5 days")
    instructions = fields.Char(string='Instructions', help="e.g. After meal")

    line_title = fields.Char(string='Prescribed As', compute='_compute_line_title')

    @api.depends('medicine_id')
    def _compute_drug_name(self):
        for rec in self:
            if rec.medicine_id:
                rec.drug_name = rec.medicine_id.name

    @api.depends('drug_name', 'strength', 'form')
    def _compute_line_title(self):
        for rec in self:
            parts = [FORM_ABBR.get(rec.form, ''), rec.drug_name or '', rec.strength or '']
            rec.line_title = ' '.join(p for p in parts if p)

    @api.onchange('medicine_id')
    def _onchange_medicine_id(self):
        med = self.medicine_id
        if med:
            self.strength = med.strength
            self.form = med.form
            self.dosage = med.default_dosage
            self.duration = med.default_duration
            self.instructions = med.default_instructions

    @api.constrains('drug_name', 'medicine_id')
    def _check_drug_name(self):
        for rec in self:
            if not (rec.drug_name or '').strip():
                raise ValidationError("Please enter the medicine name on every prescription line.")