from odoo import models, fields, api
from odoo.exceptions import UserError


class ClinicPatient(models.Model):
    _name = 'clinic.patient'
    _description = 'Clinic Patient'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    patient_id = fields.Char(string='Patient ID', readonly=True, copy=False, default='New')
    name = fields.Char(string='Patient Name', required=True, tracking=True)
    birthdate = fields.Date(string='Date of Birth')
    age = fields.Integer(string='Age', compute='_compute_age', store=True)
    image = fields.Binary(string='Photo')

    # Billing contact (res.partner) - linked automatically on create
    partner_id = fields.Many2one('res.partner', string='Billing Contact')

    blood_group = fields.Selection([
        ('a+', 'A+'), ('a-', 'A-'),
        ('b+', 'B+'), ('b-', 'B-'),
        ('o+', 'O+'), ('o-', 'O-'),
        ('ab+', 'AB+'), ('ab-', 'AB-'),
    ], string='Blood Group')

    phone = fields.Char(string='Phone')
    email = fields.Char(string='Email')

    # --- DETAILED MEDICAL HISTORY FIELDS ---
    allergies = fields.Text(string='Allergies (e.g., Penicillin, Peanuts)')
    chronic_diseases = fields.Text(string='Chronic Diseases (e.g., Diabetes, Asthma)')
    past_surgeries = fields.Text(string='Past Surgeries')
    family_history = fields.Text(string='Family Medical History')
    vaccinations = fields.Text(string='Vaccination History')
    general_notes = fields.Text(string='General Medical Notes')

    appointment_ids = fields.One2many('clinic.appointment', 'patient_id', string='Appointments')
    appointment_count = fields.Integer(compute='_compute_appointment_count')
    prescription_ids = fields.One2many('clinic.prescription.line', 'patient_id', string='All Prescriptions')

    # --- Health-card helpers (not stored) ---
    initials = fields.Char(compute='_compute_flags')
    has_allergy = fields.Boolean(compute='_compute_flags')
    has_chronic = fields.Boolean(compute='_compute_flags')

    visit_count = fields.Integer(string='Visits', compute='_compute_visit_stats')
    last_visit = fields.Date(string='Last Visit', compute='_compute_visit_stats')
    next_appointment = fields.Datetime(string='Next Appointment', compute='_compute_visit_stats')
    currency_id = fields.Many2one('res.currency', compute='_compute_visit_stats')
    amount_due = fields.Monetary(string='Amount Due', compute='_compute_visit_stats',
                                 currency_field='currency_id')

    # ------------------------------------------------------------------
    # Computes
    # ------------------------------------------------------------------
    @api.depends('birthdate')
    def _compute_age(self):
        for rec in self:
            if rec.birthdate:
                today = fields.Date.today()
                rec.age = today.year - rec.birthdate.year - (
                        (today.month, today.day) < (rec.birthdate.month, rec.birthdate.day))
            else:
                rec.age = 0

    @api.depends('appointment_ids')
    def _compute_appointment_count(self):
        data = {p.id: c for p, c in self.env['clinic.appointment']._read_group(
            [('patient_id', 'in', self.ids)], ['patient_id'], ['__count'])}
        for rec in self:
            rec.appointment_count = data.get(rec.id, 0)

    @api.depends('name', 'allergies', 'chronic_diseases')
    def _compute_flags(self):
        for rec in self:
            words = (rec.name or '').split()
            rec.initials = ''.join(w[0] for w in words[:2]).upper() or '?'
            rec.has_allergy = bool((rec.allergies or '').strip())
            rec.has_chronic = bool((rec.chronic_diseases or '').strip())

    def _compute_visit_stats(self):
        Appt = self.env['clinic.appointment']
        now = fields.Datetime.now()
        currency = self.env.company.currency_id

        done = {p.id: (count, last) for p, count, last in Appt._read_group(
            [('patient_id', 'in', self.ids), ('state', '=', 'done')],
            ['patient_id'], ['__count', 'appointment_date:max'])}
        upcoming = {p.id: first for p, first in Appt._read_group(
            [('patient_id', 'in', self.ids), ('state', 'in', ('draft', 'confirmed')),
             ('appointment_date', '>=', now)],
            ['patient_id'], ['appointment_date:min'])}
        due = {p.id: total for p, total in self.env['account.move'].sudo()._read_group(
            [('move_type', '=', 'out_invoice'), ('state', '=', 'posted'),
             ('payment_state', 'in', ('not_paid', 'partial')),
             ('clinic_appointment_id', '!=', False),
             ('partner_id', 'in', self.partner_id.ids)],
            ['partner_id'], ['amount_residual:sum'])}

        for rec in self:
            count, last = done.get(rec.id, (0, False))
            rec.visit_count = count
            rec.last_visit = fields.Datetime.context_timestamp(rec, last).date() if last else False
            rec.next_appointment = upcoming.get(rec.id, False)
            rec.currency_id = currency
            rec.amount_due = due.get(rec.partner_id.id, 0.0)

    # ------------------------------------------------------------------
    # ORM
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('patient_id', 'New') == 'New':
                vals['patient_id'] = self.env['ir.sequence'].next_by_code('clinic.patient') or 'New'

            if not vals.get('partner_id') and vals.get('name'):
                partner = self.env['res.partner'].create({
                    'name': vals.get('name'),
                    'phone': vals.get('phone'),
                    'email': vals.get('email'),
                })
                vals['partner_id'] = partner.id
        return super().create(vals_list)

    def init(self):
        # Fix missing Patient IDs
        self.env.cr.execute(
            "SELECT id FROM clinic_patient WHERE patient_id IS NULL OR patient_id = 'New'"
        )
        stale_ids = [row[0] for row in self.env.cr.fetchall()]
        for record in self.browse(stale_ids):
            record.patient_id = self.env['ir.sequence'].next_by_code('clinic.patient')

        # Fix missing Billing Contacts (res.partner) for old patients
        self.env.cr.execute(
            "SELECT id FROM clinic_patient WHERE partner_id IS NULL"
        )
        no_partner_ids = [row[0] for row in self.env.cr.fetchall()]
        for record in self.browse(no_partner_ids):
            partner = self.env['res.partner'].create({
                'name': record.name,
                'phone': record.phone,
                'email': record.email,
            })
            record.partner_id = partner.id

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
            'domain': [('patient_id', '=', self.id)],
            'context': {'default_patient_id': self.id},
        }

    def action_book_appointment(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'New Appointment',
            'res_model': 'clinic.appointment',
            'view_mode': 'form',
            'target': 'current',
            'context': {'default_patient_id': self.id},
        }

    def action_open_invoices(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Invoices',
            'res_model': 'account.move',
            'view_mode': 'list,form',
            'domain': [('partner_id', '=', self.partner_id.id),
                       ('clinic_appointment_id', '!=', False)],
        }

    def action_create_user(self):
        """Grant portal access to the patient."""
        self.ensure_one()

        if not self.email:
            raise UserError("Please provide an email address for the patient before granting portal access.")
        if not self.partner_id:
            raise UserError("No billing contact linked to this patient.")

        if not self.partner_id.email:
            self.partner_id.email = self.email

        portal_group = self.env.ref('base.group_portal')
        user = self.env['res.users'].sudo().search(
            [('partner_id', '=', self.partner_id.id)], limit=1
        )

        if user:
            self.message_post(body=f"Portal access already exists for {self.email}.")
            return

        # Odoo 18 uses 'groups_id' ('group_ids' is the Odoo 19 name)
        user = self.env['res.users'].sudo().create({
            'name': self.name,
            'login': self.email,
            'email': self.email,
            'partner_id': self.partner_id.id,
            'groups_id': [(6, 0, [portal_group.id])],
        })
        user.action_reset_password()
        self.message_post(
            body=f"Portal access granted to {self.email}. An invitation email has been sent."
        )