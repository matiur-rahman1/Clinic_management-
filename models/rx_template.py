from odoo import api, fields, models
from .medicine import FORM_SELECTION, FORM_ABBR


class ClinicRxTemplate(models.Model):
    _name = 'clinic.rx.template'
    _description = 'Prescription Protocol Template'
    _order = 'name'

    name = fields.Char(string='Protocol / Condition Name', required=True)
    specialty = fields.Selection([
        ('general', 'General Physician'),
        ('cardio', 'Cardiologist'),
        ('derma', 'Dermatologist'),
        ('pediatric', 'Pediatrician'),
        ('ortho', 'Orthopedist'),
    ], string='Specialty')
    chief_complaint = fields.Text(string='Typical Chief Complaint')
    diagnosis = fields.Text(string='Standard Diagnosis')
    advice = fields.Text(string='Standard Advice')
    follow_up_days = fields.Integer(string='Follow-up After (Days)', default=7,
                                    help="Automatically sets follow-up date when applied.")
    line_ids = fields.One2many('clinic.rx.template.line', 'template_id', string='Medicines', copy=True)
    line_count = fields.Integer(string='Medicines Count', compute='_compute_line_count')
    active = fields.Boolean(default=True)

    @api.depends('line_ids')
    def _compute_line_count(self):
        for rec in self:
            rec.line_count = len(rec.line_ids)


class ClinicRxTemplateLine(models.Model):
    _name = 'clinic.rx.template.line'
    _description = 'Prescription Template Line'
    _order = 'sequence, id'

    sequence = fields.Integer(default=10)
    template_id = fields.Many2one('clinic.rx.template', string='Template', required=True, ondelete='cascade')
    medicine_id = fields.Many2one('clinic.medicine', string='Catalog', ondelete='set null')
    drug_name = fields.Char(string='Medicine', required=True)
    strength = fields.Char(string='Strength')
    form = fields.Selection(FORM_SELECTION, string='Form')
    dosage = fields.Char(string='Frequency', required=True, default='1+0+1')
    duration = fields.Char(string='Duration', default='5 days')
    instructions = fields.Char(string='Instructions', default='After meal')

    @api.onchange('medicine_id')
    def _onchange_medicine_id(self):
        med = self.medicine_id
        if med:
            self.drug_name = med.name
            self.strength = med.strength
            self.form = med.form
            self.dosage = med.default_dosage or self.dosage
            self.duration = med.default_duration or self.duration
            self.instructions = med.default_instructions or self.instructions
