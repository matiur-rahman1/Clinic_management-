import pytz
from datetime import datetime, timedelta

from odoo import models, fields, api
from odoo.exceptions import UserError, ValidationError


class ClinicAppointment(models.Model):
    _name = 'clinic.appointment'
    _description = 'Clinic Appointment'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _rec_name = 'name'

    name = fields.Char(string='Appointment Ref', readonly=True, copy=False, default='New')
    patient_id = fields.Many2one('clinic.patient', string='Patient', required=True, tracking=True)
    doctor_id = fields.Many2one('clinic.doctor', string='Doctor', required=True, tracking=True)
    appointment_date = fields.Datetime(string='Date & Time', required=True, default=fields.Datetime.now)
    duration = fields.Float(string='Duration (Hours)', default=0.5)
    end_date = fields.Datetime(string='End Time', compute='_compute_end_date', store=True)

    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed'),
        ('in_progress', 'In Progress'),
        ('done', 'Done'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='draft', tracking=True, required=True, group_expand='_group_expand_state')

    notes = fields.Text(string='Medical Notes')

    # Consultation / prescription (doctor)
    chief_complaint = fields.Text(string='Chief Complaint')
    diagnosis = fields.Text(string='Diagnosis')
    advice = fields.Text(string='Advice')
    follow_up_date = fields.Date(string='Follow-up Date', tracking=True)
    investigation_ids = fields.One2many('clinic.lab.test', 'appointment_id', string='Investigations')
    prescription_ids = fields.One2many('clinic.prescription.line', 'appointment_id', string='Prescriptions')
    queue_ids = fields.One2many('clinic.queue', 'appointment_id', string='Queue Entries')
    reminder_sent = fields.Boolean(string='Reminder Sent', default=False, copy=False)

    # Invoice & Payment fields
    invoice_id = fields.Many2one('account.move', string='Invoice', readonly=True)
    invoice_count = fields.Integer(string='Invoices', compute='_compute_invoice_count')
    payment_state = fields.Selection(related='invoice_id.payment_state', string='Payment Status', readonly=True, store=True)

    def _group_expand_state(self, states, domain, order=None):
        return [key for key, val in self._fields['state'].selection]

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('clinic.appointment') or 'New'
        return super().create(vals_list)

    # ------------------------------------------------------------------
    # Computes & constraints
    # ------------------------------------------------------------------
    @api.depends('appointment_date', 'duration')
    def _compute_end_date(self):
        for rec in self:
            if rec.appointment_date:
                rec.end_date = rec.appointment_date + timedelta(hours=rec.duration or 0.5)
            else:
                rec.end_date = False

    @api.constrains('appointment_date', 'duration', 'doctor_id', 'state')
    def _check_doctor_overlap(self):
        for rec in self:
            if rec.state == 'cancelled' or not rec.doctor_id:
                continue
            if self.search_count([
                ('id', '!=', rec.id),
                ('doctor_id', '=', rec.doctor_id.id),
                ('state', '!=', 'cancelled'),
                ('appointment_date', '<', rec.end_date),
                ('end_date', '>', rec.appointment_date),
            ]):
                raise ValidationError(
                    f"Dr. {rec.doctor_id.name} already has an appointment in this time slot.")

    @api.depends('invoice_id')
    def _compute_invoice_count(self):
        for rec in self:
            rec.invoice_count = 1 if rec.invoice_id else 0

    # ------------------------------------------------------------------
    # Helpers used by portal / website controllers
    # ------------------------------------------------------------------
    @api.model
    def _get_booking_tz(self):
        return (self.env.user.tz
                or self.env['ir.config_parameter'].sudo().get_param('clinic.default_tz')
                or 'Asia/Dhaka')

    @api.model
    def _local_str_to_utc(self, value, tz_name):
        """'2026-11-05T10:00' (user's local time) -> naive UTC datetime"""
        local = pytz.timezone(tz_name).localize(datetime.strptime(value, '%Y-%m-%dT%H:%M'))
        return local.astimezone(pytz.utc).replace(tzinfo=None)

    @api.model
    def _validate_booking(self, doctor, start_utc, tz_name):
        """Return an error message, or False if the slot can be booked. Call on a sudo env."""
        if not doctor.exists():
            return "Invalid doctor selected."
        if start_utc <= fields.Datetime.now():
            return "Please choose a future date and time."
        if self.search_count([
            ('doctor_id', '=', doctor.id),
            ('state', '!=', 'cancelled'),
            ('appointment_date', '<', start_utc + timedelta(hours=0.5)),
            ('end_date', '>', start_utc),
        ]):
            return "This time slot is already booked. Please pick another."
        if doctor.schedule_ids:
            local_date = pytz.utc.localize(start_utc).astimezone(pytz.timezone(tz_name)).date()
            if start_utc not in [s['utc'] for s in doctor.get_available_slots(local_date, tz_name)]:
                return "The doctor is not available at that time."
        return False

    # ------------------------------------------------------------------
    # Workflow
    # ------------------------------------------------------------------
    def action_confirm(self):
        self.write({'state': 'confirmed'})

    def action_start(self):
        self.write({'state': 'in_progress'})
        Queue = self.env['clinic.queue']
        for rec in self:
            queue = rec.queue_ids[:1]
            if queue:
                queue.state = 'in_consultation'
            else:
                Queue.create({
                    'patient_id': rec.patient_id.id,
                    'doctor_id': rec.doctor_id.id,
                    'appointment_id': rec.id,
                    'state': 'in_consultation',
                })

    def action_done(self):
        for rec in self.filtered(lambda r: r.state != 'done'):
            rec.queue_ids.filtered(lambda q: q.state != 'cancelled').write({'state': 'done'})
            rec.write({'state': 'done'})

    def action_cancel(self):
        self.write({'state': 'cancelled'})
        self.queue_ids.filtered(lambda q: q.state not in ('done', 'cancelled')).write({'state': 'cancelled'})

    # ------------------------------------------------------------------
    # Invoice & payment
    # ------------------------------------------------------------------
    def action_create_invoice(self):
        self.ensure_one()

        if self.invoice_id:
            raise UserError("An invoice already exists for this appointment.")

        if not self.doctor_id.income_account:
            raise UserError("Please configure an Income Account on the Doctor's profile first.")

        if not self.patient_id.partner_id:
            partner = self.env['res.partner'].create({
                'name': self.patient_id.name,
                'phone': self.patient_id.phone,
                'email': self.patient_id.email,
            })
            self.patient_id.partner_id = partner.id

        invoice_vals = {
            'move_type': 'out_invoice',
            'partner_id': self.patient_id.partner_id.id,
            'invoice_date': fields.Date.today(),
            'clinic_appointment_id': self.id,
            'invoice_line_ids': [(0, 0, {
                'name': f"Consultation Fee - Dr. {self.doctor_id.name} ({self.name})",
                'quantity': 1,
                'price_unit': self.doctor_id.consultation_fee,
                'account_id': self.doctor_id.income_account.id,
            })],
        }
        invoice = self.env['account.move'].create(invoice_vals)
        invoice.action_post()
        self.invoice_id = invoice.id

        return {
            'type': 'ir.actions.act_window',
            'name': 'Invoice',
            'res_model': 'account.move',
            'res_id': invoice.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_view_invoice(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Invoice',
            'res_model': 'account.move',
            'res_id': self.invoice_id.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_register_payment(self):
        self.ensure_one()
        return {
            'name': 'Register Payment',
            'type': 'ir.actions.act_window',
            'res_model': 'account.payment.register',
            'view_mode': 'form',
            'context': {
                'active_model': 'account.move',
                'active_ids': [self.invoice_id.id],
            },
            'target': 'new',
        }

    # ------------------------------------------------------------------
    # Cron
    # ------------------------------------------------------------------
    @api.model
    def _cron_send_appointment_reminders(self):
        today = fields.Date.context_today(self)
        tomorrow = today + timedelta(days=1)
        start_of_tomorrow = datetime.combine(tomorrow, datetime.min.time())
        end_of_tomorrow = datetime.combine(tomorrow, datetime.max.time())

        appointments = self.search([
            ('appointment_date', '>=', start_of_tomorrow),
            ('appointment_date', '<=', end_of_tomorrow),
            ('state', 'in', ('draft', 'confirmed')),
            ('reminder_sent', '=', False),
            ('patient_id.email', '!=', False),
        ])

        template = self.env.ref('clinic_management.mail_template_appointment_reminder', raise_if_not_found=False)
        if not template:
            return

        for appt in appointments:
            template.send_mail(appt.id, force_send=False)
            appt.reminder_sent = True
            appt.message_post(body="Reminder email successfully sent to the patient.")