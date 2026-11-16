import pytz

from odoo import models, fields, api


class ClinicQueue(models.Model):
    _name = 'clinic.queue'
    _description = 'Patient Queue'
    _rec_name = 'token_number'
    _order = 'check_in_time asc'

    token_number = fields.Char(string='Token', readonly=True, copy=False, default='New')
    patient_id = fields.Many2one('clinic.patient', string='Patient', required=True)
    doctor_id = fields.Many2one('clinic.doctor', string='Doctor')
    check_in_time = fields.Datetime(string='Check-in Time', default=fields.Datetime.now)

    # Link to the Appointment
    appointment_id = fields.Many2one('clinic.appointment', string='Linked Appointment', readonly=True)

    state = fields.Selection([
        ('waiting', 'Waiting'),
        ('in_consultation', 'In Consultation'),
        ('done', 'Done'),
        ('cancelled', 'Cancelled')
    ], string='Status', default='waiting', required=True, group_expand='_group_expand_state')

    # Live display helpers (not stored)
    patient_initials = fields.Char(compute='_compute_live')
    time_label = fields.Char(string='Checked in', compute='_compute_live')
    wait_minutes = fields.Integer(string='Waiting (min)', compute='_compute_live')
    wait_level = fields.Selection([('ok', 'OK'), ('warn', 'Long'), ('bad', 'Very long')],
                                  compute='_compute_live')
    queue_position = fields.Integer(string='Position in line', compute='_compute_live')
    is_next = fields.Boolean(string='Next up', compute='_compute_live')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('token_number', 'New') == 'New':
                vals['token_number'] = self.env['ir.sequence'].next_by_code('clinic.queue') or 'New'
        return super().create(vals_list)

    def _group_expand_state(self, states, domain, order=None):
        return [key for key, val in self._fields['state'].selection]

    # ------------------------------------------------------------------
    # Live info
    # ------------------------------------------------------------------
    def _compute_live(self):
        now = fields.Datetime.now()
        tz = pytz.timezone(self.env['clinic.appointment']._get_booking_tz())
        today_start = self.env['clinic.doctor']._today_range_utc()[0]

        # Position in line per doctor (today's waiting patients only)
        waiting = self.sudo().search(
            [('state', '=', 'waiting'), ('check_in_time', '>=', today_start)],
            order='check_in_time, id')
        position, counters = {}, {}
        for q in waiting:
            key = q.doctor_id.id or 0
            counters[key] = counters.get(key, 0) + 1
            position[q.id] = counters[key]

        for rec in self:
            words = (rec.patient_id.name or '').split()
            rec.patient_initials = ''.join(w[0] for w in words[:2]).upper() or '?'

            if rec.check_in_time:
                local = pytz.utc.localize(rec.check_in_time).astimezone(tz)
                rec.time_label = local.strftime('%I:%M %p').lstrip('0')
            else:
                rec.time_label = ''

            minutes = 0
            if rec.state in ('waiting', 'in_consultation') and rec.check_in_time:
                minutes = max(int((now - rec.check_in_time).total_seconds() // 60), 0)
            rec.wait_minutes = minutes
            if rec.state != 'waiting' or minutes < 15:
                rec.wait_level = 'ok'
            elif minutes < 30:
                rec.wait_level = 'warn'
            else:
                rec.wait_level = 'bad'

            rec.queue_position = position.get(rec.id, 0)
            rec.is_next = position.get(rec.id) == 1

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def action_start_consultation(self):
        self.write({'state': 'in_consultation'})

    def action_done(self):
        self.write({'state': 'done'})

    def action_cancel(self):
        self.write({'state': 'cancelled'})

    # Create and Open Appointment
    def action_create_appointment(self):
        self.ensure_one()

        # Appointment already exists: just open it
        if self.appointment_id:
            return {
                'type': 'ir.actions.act_window',
                'name': 'Appointment',
                'res_model': 'clinic.appointment',
                'res_id': self.appointment_id.id,
                'view_mode': 'form',
                'target': 'current',
            }

        # Otherwise create a new one
        appointment = self.env['clinic.appointment'].create({
            'patient_id': self.patient_id.id,
            'doctor_id': self.doctor_id.id,
            'appointment_date': fields.Datetime.now(),
            'state': 'in_progress',
        })

        self.appointment_id = appointment.id
        self.state = 'in_consultation'

        return {
            'type': 'ir.actions.act_window',
            'name': 'Appointment',
            'res_model': 'clinic.appointment',
            'res_id': appointment.id,
            'view_mode': 'form',
            'target': 'current',
        }