from odoo import http
from odoo.http import request
from odoo.tools import email_normalize
from datetime import datetime


class WebsiteAppointment(http.Controller):

    @http.route('/book-appointment', type='http', auth="public", website=True)
    def book_appointment_form(self, **kw):
        return request.render('clinic_management.website_appointment_form', {
            'doctors': request.env['clinic.doctor'].sudo().search([]),
            'error': kw.get('error'),
            'success': kw.get('success'),
        })

    @http.route('/clinic/slots', type='json', auth="public", website=True)
    def available_slots(self, doctor_id, date):
        """date: 'YYYY-MM-DD' -> {'has_schedule': bool, 'slots': [{'value', 'label'}]}"""
        Appointment = request.env['clinic.appointment'].sudo()
        try:
            doctor = request.env['clinic.doctor'].sudo().browse(int(doctor_id)).exists()
            day = datetime.strptime(date, '%Y-%m-%d').date()
        except (TypeError, ValueError):
            return {'has_schedule': False, 'slots': []}
        if not doctor:
            return {'has_schedule': False, 'slots': []}
        slots = doctor.get_available_slots(day, Appointment._get_booking_tz())
        return {
            'has_schedule': bool(doctor.schedule_ids),
            'slots': [{'value': s['value'], 'label': s['label']} for s in slots],
        }

    @http.route('/book-appointment/submit', type='http', auth="public", website=True,
                methods=['POST'], csrf=True)
    def book_appointment_submit(self, **post):
        name = (post.get('name') or '').strip()
        email = email_normalize(post.get('email') or '')
        phone = (post.get('phone') or '').strip()

        def back(msg):
            return request.redirect('/book-appointment?error=' + msg.replace(' ', '+'))

        if not (name and email and phone and post.get('doctor_id') and post.get('appointment_date')):
            return back('Missing required fields')

        Appointment = request.env['clinic.appointment'].sudo()
        tz_name = Appointment._get_booking_tz()
        try:
            doctor = request.env['clinic.doctor'].sudo().browse(int(post['doctor_id']))
            start = Appointment._local_str_to_utc(post['appointment_date'], tz_name)
        except (TypeError, ValueError):
            return back('Invalid date or doctor')

        error = Appointment._validate_booking(doctor, start, tz_name)
        if error:
            return back(error)

        partner = request.env['res.partner'].sudo().search([('email', '=ilike', email)], limit=1)
        # Registered user-er email diye onno keu book korte parbe na
        if partner and partner.user_ids:
            return back('This email belongs to a registered account. Please log in to book')
        if not partner:
            partner = request.env['res.partner'].sudo().create(
                {'name': name, 'email': email, 'phone': phone})

        patient = request.env['clinic.patient'].sudo().search(
            [('partner_id', '=', partner.id)], limit=1)
        if not patient:
            patient = request.env['clinic.patient'].sudo().create(
                {'name': name, 'email': email, 'phone': phone, 'partner_id': partner.id})

        Appointment.create({
            'patient_id': patient.id,
            'doctor_id': doctor.id,
            'appointment_date': start,
            'state': 'draft',
        })
        return request.redirect(
            '/book-appointment?success=Your+appointment+has+been+booked+successfully!+We+will+contact+you+soon.')