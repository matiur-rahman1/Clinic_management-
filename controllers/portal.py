from odoo import fields, http
from odoo.exceptions import AccessDenied
from odoo.http import request
from odoo.addons.portal.controllers.portal import CustomerPortal
from urllib.parse import quote_plus


class ClinicPortal(CustomerPortal):

    def _get_patient(self):
        user = request.env.user
        partner = user.partner_id
        Patient = request.env['clinic.patient'].sudo()
        patient = Patient.search([('partner_id', '=', partner.id)], limit=1)
        if not patient:
            # Logged-in user without a patient record yet: create one so /my/clinic works.
            patient = Patient.create({
                'name': partner.name or user.name,
                'email': partner.email or user.login,
                'phone': partner.phone,
                'partner_id': partner.id,
            })
        return patient

    @http.route(['/my/clinic'], type='http', auth="public", website=True)
    def portal_my_clinic(self, **kw):
        if request.env.user._is_public():
            return request.redirect('/clinic/login')
        patient = self._get_patient()
        if not patient:
            return request.redirect('/my')
        partner = patient.partner_id
        env = request.env
        appointments = env['clinic.appointment'].sudo().search(
            [('patient_id', '=', patient.id)], order='appointment_date desc')
        now = fields.Datetime.now()
        upcoming = appointments.filtered(
            lambda a: a.state == 'in_progress'
            or (a.state in ('draft', 'confirmed') and a.appointment_date and a.appointment_date >= now))
        today = fields.Date.context_today(env['clinic.appointment'])
        follow_ups = appointments.filtered(lambda a: a.follow_up_date and a.follow_up_date >= today
                                           and a.state != 'cancelled').sorted('follow_up_date')
        values = {
            'patient': patient,
            'follow_up': follow_ups[:1],
            'next_appt': upcoming.sorted('appointment_date')[:1],
            'doctors': env['clinic.doctor'].sudo().search([], order='name asc'),
            'appointments': appointments,
            'prescriptions': env['clinic.prescription.line'].sudo().search(
                [('patient_id', '=', patient.id)], order='id desc'),
            'invoices': env['account.move'].sudo().search(
                [('partner_id', '=', partner.id), ('move_type', '=', 'out_invoice'),
                 ('state', '!=', 'cancel')], order='invoice_date desc'),
            'page_name': 'home',
            'success': kw.get('success'),
            'error': kw.get('error'),
        }
        return request.render("clinic_management.portal_my_clinic", values)

    @http.route(['/my/clinic/book'], type='http', auth="user", website=True, methods=['POST'], csrf=True)
    def portal_book_appointment(self, **post):
        patient = self._get_patient()
        if not patient:
            return request.redirect('/my')

        Appointment = request.env['clinic.appointment'].sudo()
        tz_name = Appointment._get_booking_tz()
        try:
            doctor = request.env['clinic.doctor'].sudo().browse(int(post.get('doctor_id')))
            start = Appointment._local_str_to_utc(post.get('appointment_date'), tz_name)
        except (TypeError, ValueError):
            return request.redirect('/my/clinic?error=Invalid+booking+data')

        error = Appointment._validate_booking(doctor, start, tz_name)
        if error:
            return request.redirect('/my/clinic?error=' + quote_plus(error))

        Appointment.create({'patient_id': patient.id, 'doctor_id': doctor.id,
                            'appointment_date': start, 'state': 'draft'})
        return request.redirect('/my/clinic?success=1')

    @http.route(['/my/clinic/cancel/<int:appt_id>'], type='http', auth="user", website=True,
                methods=['POST'], csrf=True)
    def portal_cancel_appointment(self, appt_id, **post):
        patient = self._get_patient()
        appt = request.env['clinic.appointment'].sudo().browse(appt_id).exists()
        if not patient or not appt or appt.patient_id != patient:
            return request.redirect('/my/clinic?error=Appointment+not+found')
        if appt.state not in ('draft', 'confirmed'):
            return request.redirect('/my/clinic?error=This+appointment+cannot+be+cancelled')
        appt.action_cancel()
        appt.message_post(body="Cancelled by the patient from the portal.")
        return request.redirect('/my/clinic?success=1')

    @http.route(['/my/clinic/rx/<int:appt_id>'], type='http', auth="user", website=True)
    def portal_download_rx(self, appt_id, **kw):
        patient = self._get_patient()
        appt = request.env['clinic.appointment'].sudo().browse(appt_id).exists()
        if not patient or not appt or appt.patient_id != patient or not appt.prescription_ids:
            return request.redirect('/my/clinic?error=Prescription+not+found')
        pdf, _fmt = request.env['ir.actions.report'].sudo()._render_qweb_pdf(
            'clinic_management.action_report_prescription', [appt.id])
        filename = 'Prescription-%s.pdf' % appt.name.replace('/', '-')
        return request.make_response(pdf, headers=[
            ('Content-Type', 'application/pdf'),
            ('Content-Length', len(pdf)),
            ('Content-Disposition', 'attachment; filename="%s"' % filename),
        ])

    # ---------------- Patient login page ----------------
    def _login_values(self, **extra):
        user = request.env.user
        try:
            can_signup = request.env['res.users']._get_signup_invitation_scope() == 'b2c'
        except Exception:
            can_signup = False
        vals = {
            'logged_in': not user._is_public(),
            'user_name': user.name,
            'can_signup': can_signup,
            'error': None,
            'login': '',
        }
        vals.update(extra)
        return vals

    @http.route(['/clinic/login'], type='http', auth="public", website=True, sitemap=False)
    def clinic_login(self, **kw):
        return request.render('clinic_management.clinic_login_page', self._login_values())

    @http.route(['/clinic/login/submit'], type='http', auth="public", website=True,
                methods=['POST'], csrf=True, sitemap=False)
    def clinic_login_submit(self, **post):
        login = (post.get('login') or '').strip()
        password = post.get('password') or ''
        try:
            request.session.authenticate(request.db, {'type': 'password', 'login': login, 'password': password})
        except AccessDenied:
            return request.render('clinic_management.clinic_login_page', self._login_values(
                error='Wrong email or password. Please try again.', login=login))
        return request.redirect('/my/clinic')