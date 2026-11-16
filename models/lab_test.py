from odoo import models, fields, api


class ClinicLabTest(models.Model):
    _name = 'clinic.lab.test'
    _description = 'Laboratory Test'
    _order = 'priority desc, test_date desc, id desc'

    name = fields.Char(string='Test Name', required=True)
    patient_id = fields.Many2one('clinic.patient', string='Patient', required=True)
    doctor_id = fields.Many2one('clinic.doctor', string='Prescribed By')
    appointment_id = fields.Many2one('clinic.appointment', string='Appointment', ondelete='set null', index=True)
    test_date = fields.Date(string='Date', default=fields.Date.today)
    priority = fields.Selection([('routine', 'Routine'), ('urgent', 'Urgent (STAT)')],
                                string='Priority', default='routine', required=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('in_progress', 'In Progress'),
        ('done', 'Result Ready')
    ], string='Status', default='draft', group_expand='_group_expand_state')
    result_notes = fields.Text(string='Lab Results')

    # Structured numeric result (optional)
    result_value = fields.Float(string='Result Value', digits=(16, 2))
    result_unit = fields.Char(string='Unit', help="e.g. g/dL, mg/dL, mmol/L")
    ref_min = fields.Float(string='Normal From', digits=(16, 2))
    ref_max = fields.Float(string='Normal To', digits=(16, 2))
    result_flag = fields.Selection([
        ('none', 'No numeric result'),
        ('low', 'Low'),
        ('normal', 'Normal'),
        ('high', 'High'),
    ], string='Flag', compute='_compute_flag', store=True)

    # Display helpers (not stored)
    range_pct = fields.Integer(compute='_compute_display')
    ref_label = fields.Char(string='Reference', compute='_compute_display')
    patient_initials = fields.Char(compute='_compute_display')

    def _group_expand_state(self, states, domain, order=None):
        return [key for key, val in self._fields['state'].selection]

    @api.depends('result_value', 'ref_min', 'ref_max')
    def _compute_flag(self):
        for rec in self:
            if rec.ref_max > rec.ref_min and rec.result_value:
                if rec.result_value < rec.ref_min:
                    rec.result_flag = 'low'
                elif rec.result_value > rec.ref_max:
                    rec.result_flag = 'high'
                else:
                    rec.result_flag = 'normal'
            else:
                rec.result_flag = 'none'

    @api.depends('result_value', 'ref_min', 'ref_max', 'result_unit', 'patient_id.name')
    def _compute_display(self):
        for rec in self:
            words = (rec.patient_id.name or '').split()
            rec.patient_initials = ''.join(w[0] for w in words[:2]).upper() or '?'
            if rec.ref_max > rec.ref_min:
                span = rec.ref_max - rec.ref_min
                window_start = rec.ref_min - span * 0.5      # normal zone = 25%..75% of the bar
                pct = (rec.result_value - window_start) / (span * 2.0) * 100
                rec.range_pct = int(max(3, min(97, round(pct))))
                rec.ref_label = 'Normal: %g - %g %s' % (rec.ref_min, rec.ref_max, rec.result_unit or '')
            else:
                rec.range_pct = 50
                rec.ref_label = ''

    # ------------------------------------------------------------------
    # Workflow
    # ------------------------------------------------------------------
    def action_start(self):
        self.write({'state': 'in_progress'})

    def action_done(self):
        self.write({'state': 'done'})

    def action_reset(self):
        self.write({'state': 'draft'})