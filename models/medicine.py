from odoo import models, fields, api

FORM_SELECTION = [
    ('tablet', 'Tablet'),
    ('capsule', 'Capsule'),
    ('syrup', 'Syrup / Suspension'),
    ('injection', 'Injection'),
    ('drops', 'Drops'),
    ('cream', 'Cream / Ointment'),
    ('inhaler', 'Inhaler'),
    ('powder', 'Powder / Sachet'),
    ('other', 'Other'),
]
FORM_ABBR = {
    'tablet': 'Tab.', 'capsule': 'Cap.', 'syrup': 'Syr.', 'injection': 'Inj.',
    'drops': 'Drops', 'cream': 'Oint.', 'inhaler': 'Inh.', 'powder': 'Sachet',
}


class ClinicMedicine(models.Model):
    """Drug catalog: a reference list that speeds up writing prescriptions.

    The clinic does not sell medicine, so there is no stock, price or dispensing here.
    Doctors may also type any drug that is not in the catalog directly on the prescription.
    """
    _name = 'clinic.medicine'
    _description = 'Drug Catalog'
    _order = 'name'
    _rec_names_search = ['name', 'generic_name']

    name = fields.Char(string='Brand / Drug Name', required=True)
    generic_name = fields.Char(string='Generic Name')
    strength = fields.Char(string='Strength', help="e.g. 500 mg, 5 mg/5 ml")
    form = fields.Selection(FORM_SELECTION, string='Form')

    default_dosage = fields.Char(string='Default Frequency', help="e.g. 1+0+1")
    default_duration = fields.Char(string='Default Duration', help="e.g. 5 days")
    default_instructions = fields.Char(string='Default Instructions', help="e.g. After meal")
    note = fields.Text(string='Notes')
    active = fields.Boolean(default=True)

    @api.depends('name', 'strength', 'generic_name')
    def _compute_display_name(self):
        for rec in self:
            label = rec.name or ''
            if rec.strength:
                label += ' ' + rec.strength
            if rec.generic_name:
                label += ' (%s)' % rec.generic_name
            rec.display_name = label